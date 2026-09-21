"""Reviewed, durable structural operations for Economic Taxonomy snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
    SnapshotValidationError,
)
from app.models.economic_taxonomy import (
    EconomicThemeFacet,
    EconomicThemeRelationship,
    EconomicThemeRevision,
    TaxonomyVersion,
)
from app.models.economic_taxonomy_runtime import (
    ServingGenerationEvent,
    TaxonomyOperationEvent,
    TaxonomyOperationPreview,
    TaxonomyOperationRequest,
)
from app.services.economic_taxonomy_fence import producer_write


class TaxonomyOperationError(ValueError):
    """Base error for reviewed structural operations."""


class TaxonomyReviewForbidden(TaxonomyOperationError):
    pass


class OperationPreviewChanged(TaxonomyOperationError):
    pass


class OperationPreviewInvalid(TaxonomyOperationError):
    pass


@dataclass(frozen=True, slots=True)
class OperationPreviewResult:
    preview_id: UUID
    request_id: UUID
    candidate_taxonomy_version_id: UUID
    actor_subject: str
    before_semantic_hash: str
    before_artifact_integrity_hash: str
    after_semantic_hash: str
    after_artifact_integrity_hash: str
    preview_hash: str
    destination_count: int
    unallocated_claim_ids: tuple[str, ...]
    validation_errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperationApplyResult:
    operation_request_id: UUID
    taxonomy_version_id: UUID
    semantic_hash: str
    artifact_integrity_hash: str
    processing_head_revision: int


_UNTRUSTED_ACTOR_KEYS = frozenset(
    {"actor", "actor_subject", "created_by", "reviewer", "reviewed_by"}
)


def _clean_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _clean_payload(item)
            for key, item in value.items()
            if str(key) not in _UNTRUSTED_ACTOR_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_clean_payload(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaxonomyOperationError(f"{name}_required")
    return value.strip()


class EconomicTaxonomyOperationService:
    """Preview and atomically accept reviewed semantic changes.

    A preview owns an unsealed candidate snapshot.  Apply re-hashes that exact
    draft under the shared producer fence before sealing it and moving only the
    processing pointer.  Serving authority is never changed here.
    """

    def __init__(self, session: Session):
        self.session = session

    def preview_operation(
        self,
        request: Mapping[str, Any],
        *,
        principal: AdminPrincipal,
        expected_epoch: int,
    ) -> OperationPreviewResult:
        self._require_reviewer(principal)
        payload = _clean_payload(dict(request))
        operation_kind = _required_text(payload.get("operation_kind"), "operation_kind")

        with producer_write(
            self.session,
            expected_epoch=expected_epoch,
            allowed_modes={"shadow", "dual", "economic"},
        ) as authority:
            base_version_id = authority.processing_taxonomy_version_id
            if base_version_id is None:
                raise TaxonomyOperationError("processing_taxonomy_head_missing")
            repo = EconomicTaxonomyRepository(self.session)
            base = self.session.get(TaxonomyVersion, base_version_id)
            if base is None or base.status != "sealed":
                raise TaxonomyOperationError("processing_taxonomy_head_unsealed")

            request_hash = _hash(
                {
                    "operation_kind": operation_kind,
                    "base_taxonomy_version_id": str(base_version_id),
                    "request_payload": payload,
                    "actor_subject": principal.subject,
                }
            )
            existing_request = self.session.scalar(
                select(TaxonomyOperationRequest).where(
                    TaxonomyOperationRequest.request_hash == request_hash
                )
            )
            if existing_request is not None:
                existing_preview = self.session.scalar(
                    select(TaxonomyOperationPreview).where(
                        TaxonomyOperationPreview.operation_request_id
                        == existing_request.id
                    )
                )
                if existing_preview is None:
                    raise TaxonomyOperationError("operation_preview_missing")
                return self._preview_result(existing_request, existing_preview)

            operation_request = TaxonomyOperationRequest(
                operation_kind=operation_kind,
                base_taxonomy_version_id=base_version_id,
                request_payload=payload,
                request_hash=request_hash,
                actor_subject=principal.subject,
                auth_method=principal.auth_method,
            )
            self.session.add(operation_request)
            self.session.flush()

            candidate = repo.clone_draft(
                base_version_id,
                actor=principal.subject,
                reason=f"Preview {operation_kind} operation {operation_request.id}",
            )
            assignments, mappings, affected, unallocated = self._apply_request(
                repo,
                candidate.id,
                operation_kind,
                payload,
                actor=principal.subject,
            )
            validation_errors: list[str] = []
            try:
                repo._validate_snapshot(candidate.id)
            except (SnapshotValidationError, ValueError) as exc:
                validation_errors.append(str(exc))

            before_semantic = base.semantic_hash or repo.semantic_hash(base.id)
            before_artifact = (
                base.artifact_integrity_hash or repo.artifact_integrity_hash(base.id)
            )
            after_semantic = repo.semantic_hash(candidate.id)
            after_artifact = repo.artifact_integrity_hash(candidate.id)
            compatibility_intents = sorted(
                str(item) for item in payload.get("compatibility_intents", [])
            )
            incompatible = bool(
                payload.get("incompatible_with_prepared_generation", False)
            )
            preview_payload = {
                "request_hash": request_hash,
                "candidate_taxonomy_version_id": str(candidate.id),
                "before_semantic_hash": before_semantic,
                "before_artifact_integrity_hash": before_artifact,
                "after_semantic_hash": after_semantic,
                "after_artifact_integrity_hash": after_artifact,
                "affected_identities": affected,
                "assignments": assignments,
                "mappings": mappings,
                "compatibility_intents": compatibility_intents,
                "validation_errors": validation_errors,
                "incompatible_with_prepared_generation": incompatible,
            }
            preview = TaxonomyOperationPreview(
                operation_request_id=operation_request.id,
                candidate_taxonomy_version_id=candidate.id,
                preview_hash=_hash(preview_payload),
                before_semantic_hash=before_semantic,
                before_artifact_integrity_hash=before_artifact,
                after_semantic_hash=after_semantic,
                after_artifact_integrity_hash=after_artifact,
                affected_identities=affected,
                assignments=assignments,
                mappings=mappings,
                compatibility_intents=compatibility_intents,
                validation_errors=validation_errors,
                incompatible_with_prepared_generation=incompatible,
            )
            self.session.add(preview)
            self.session.flush()
            self._append_event(
                operation_request.id,
                "previewed",
                principal=principal,
                reason="Durable operation preview created.",
                payload={
                    "preview_id": str(preview.id),
                    "preview_hash": preview.preview_hash,
                    "candidate_taxonomy_version_id": str(candidate.id),
                },
            )
            return OperationPreviewResult(
                preview_id=preview.id,
                request_id=operation_request.id,
                candidate_taxonomy_version_id=candidate.id,
                actor_subject=principal.subject,
                before_semantic_hash=before_semantic,
                before_artifact_integrity_hash=before_artifact,
                after_semantic_hash=after_semantic,
                after_artifact_integrity_hash=after_artifact,
                preview_hash=preview.preview_hash,
                destination_count=len(
                    {
                        mapping["destination_theme_id"]
                        for mapping in mappings
                        if mapping.get("destination_theme_id")
                    }
                ),
                unallocated_claim_ids=tuple(unallocated),
                validation_errors=tuple(validation_errors),
            )

    def apply_operation(
        self,
        preview_id: UUID,
        *,
        principal: AdminPrincipal,
        reason: str,
        expected_epoch: int,
    ) -> OperationApplyResult:
        self._require_reviewer(principal)
        reason = _required_text(reason, "reason")
        with producer_write(
            self.session,
            expected_epoch=expected_epoch,
            allowed_modes={"shadow", "dual", "economic"},
        ) as authority:
            preview = self.session.execute(
                select(TaxonomyOperationPreview)
                .where(TaxonomyOperationPreview.id == preview_id)
                .with_for_update()
            ).scalar_one_or_none()
            if preview is None:
                raise TaxonomyOperationError("operation_preview_not_found")
            request = self.session.get(
                TaxonomyOperationRequest, preview.operation_request_id
            )
            if request is None:
                raise TaxonomyOperationError("operation_request_not_found")
            applied = self.session.scalar(
                select(TaxonomyOperationEvent).where(
                    TaxonomyOperationEvent.operation_request_id == request.id,
                    TaxonomyOperationEvent.event_type == "applied",
                )
            )
            if applied is not None:
                payload = applied.event_payload
                version = self.session.get(
                    TaxonomyVersion, UUID(payload["taxonomy_version_id"])
                )
                return OperationApplyResult(
                    operation_request_id=request.id,
                    taxonomy_version_id=version.id,
                    semantic_hash=version.semantic_hash,
                    artifact_integrity_hash=version.artifact_integrity_hash,
                    processing_head_revision=int(payload["processing_head_revision"]),
                )
            if authority.processing_taxonomy_version_id != request.base_taxonomy_version_id:
                raise OperationPreviewChanged("operation_preview_changed: processing_head")
            if preview.validation_errors:
                raise OperationPreviewInvalid("operation_preview_invalid")

            repo = EconomicTaxonomyRepository(self.session)
            candidate = self.session.get(
                TaxonomyVersion, preview.candidate_taxonomy_version_id
            )
            if candidate is None or candidate.status != "draft":
                raise OperationPreviewChanged("operation_preview_changed: candidate")
            if (
                repo.semantic_hash(candidate.id) != preview.after_semantic_hash
                or repo.artifact_integrity_hash(candidate.id)
                != preview.after_artifact_integrity_hash
            ):
                raise OperationPreviewChanged("operation_preview_changed")

            self._append_event(
                request.id,
                "reviewed",
                principal=principal,
                reason=reason,
                payload={"preview_hash": preview.preview_hash},
            )
            sealed = repo.seal_draft(candidate.id)
            authority.processing_taxonomy_version_id = sealed.id
            authority.processing_head_revision += 1

            publication = EconomicTaxonomyPublicationRepository(self.session)
            if (
                preview.incompatible_with_prepared_generation
                and self._has_prepared_generation()
            ):
                publication.append_semantic_invalidation(
                    reason=f"taxonomy operation {request.id}: {reason}",
                    actor=principal.subject,
                )
            publication.append_source_revision(
                producer_kind="economic_taxonomy",
                logical_source_key=f"taxonomy_operation:{request.id}",
                revision_kind=(
                    "lifecycle_change"
                    if request.operation_kind == "lifecycle_override"
                    else "structural_operation"
                ),
                revision_number=1,
                content_hash=preview.preview_hash,
                authority_epoch=authority.authority_epoch,
            )
            self._append_event(
                request.id,
                "applied",
                principal=principal,
                reason=reason,
                payload={
                    "preview_id": str(preview.id),
                    "preview_hash": preview.preview_hash,
                    "taxonomy_version_id": str(sealed.id),
                    "semantic_hash": sealed.semantic_hash,
                    "artifact_integrity_hash": sealed.artifact_integrity_hash,
                    "processing_head_revision": authority.processing_head_revision,
                },
            )
            self.session.flush()
            return OperationApplyResult(
                operation_request_id=request.id,
                taxonomy_version_id=sealed.id,
                semantic_hash=sealed.semantic_hash,
                artifact_integrity_hash=sealed.artifact_integrity_hash,
                processing_head_revision=authority.processing_head_revision,
            )

    def _apply_request(
        self,
        repo: EconomicTaxonomyRepository,
        version_id: UUID,
        operation_kind: str,
        payload: Mapping[str, Any],
        *,
        actor: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
        assignments: list[dict[str, Any]] = []
        mappings: list[dict[str, Any]] = []
        affected: list[str] = []
        unallocated: list[str] = []

        if operation_kind == "rename":
            theme_id = UUID(_required_text(payload.get("theme_id"), "theme_id"))
            revision = self._revision(version_id, theme_id)
            revision.display_name = _required_text(
                payload.get("display_name"), "display_name"
            )
            affected.append(str(theme_id))
        elif operation_kind in {"lifecycle_override", "retire"}:
            theme_id = UUID(_required_text(payload.get("theme_id"), "theme_id"))
            revision = self._revision(version_id, theme_id)
            revision.lifecycle = (
                "retired"
                if operation_kind == "retire"
                else _required_text(payload.get("lifecycle"), "lifecycle")
            )
            if payload.get("lifecycle_policy_version") is not None:
                revision.lifecycle_policy_version = _required_text(
                    payload.get("lifecycle_policy_version"),
                    "lifecycle_policy_version",
                )
            affected.append(str(theme_id))
        elif operation_kind == "merge":
            source_id = UUID(
                _required_text(payload.get("source_theme_id"), "source_theme_id")
            )
            target_id = UUID(
                _required_text(payload.get("target_theme_id"), "target_theme_id")
            )
            repo.add_theme_redirect(
                version_id,
                source_theme_id=source_id,
                target_theme_id=target_id,
                actor=actor,
                reason=str(payload.get("merge_reason") or "reviewed merge"),
            )
            self._revision(version_id, source_id).lifecycle = "retired"
            affected.extend((str(source_id), str(target_id)))
            mappings.append(
                {
                    "mapping_kind": "theme_redirect",
                    "source_theme_id": str(source_id),
                    "destination_theme_id": str(target_id),
                }
            )
        elif operation_kind in {"legacy_split", "legacy_disposition"}:
            legacy_id = int(payload["legacy_theme_cluster_id"])
            disposition = (
                "split_required"
                if operation_kind == "legacy_split"
                else _required_text(payload.get("disposition"), "disposition")
            )
            repo.set_legacy_disposition(
                version_id, legacy_id, disposition=disposition, actor=actor
            )
            destinations = [
                UUID(str(value)) for value in payload.get("destination_theme_ids", [])
            ]
            for destination_id in destinations:
                repo.add_legacy_destination(
                    version_id, legacy_id, destination_id, actor=actor
                )
                mappings.append(
                    {
                        "mapping_kind": "legacy_destination",
                        "legacy_theme_cluster_id": legacy_id,
                        "destination_theme_id": str(destination_id),
                    }
                )
            allocated_keys: set[str] = set()
            for allocation in payload.get("allocations", []):
                allocation_key = _required_text(
                    allocation.get("allocation_key"), "allocation_key"
                )
                destination_value = allocation.get("destination_theme_id")
                destination_id = (
                    UUID(str(destination_value))
                    if destination_value is not None
                    else None
                )
                exclusion = allocation.get("reviewed_exclusion")
                repo.allocate_legacy_claim(
                    version_id,
                    legacy_id,
                    allocation_kind=str(allocation.get("allocation_kind") or "claim"),
                    allocation_key=allocation_key,
                    destination_theme_id=destination_id,
                    reviewed_exclusion=(str(exclusion) if exclusion is not None else None),
                    actor=actor,
                )
                normalized = {
                    "legacy_theme_cluster_id": legacy_id,
                    "allocation_kind": str(
                        allocation.get("allocation_kind") or "claim"
                    ),
                    "allocation_key": allocation_key,
                    "destination_theme_id": (
                        str(destination_id) if destination_id else None
                    ),
                    "reviewed_exclusion": exclusion,
                }
                assignments.append(normalized)
                allocated_keys.add(allocation_key)
            declared_claims = {str(value) for value in payload.get("claim_ids", [])}
            unallocated = sorted(declared_claims - allocated_keys)
            if unallocated:
                raise TaxonomyOperationError("split_has_unallocated_claims")
            affected.append(f"legacy_theme_cluster:{legacy_id}")
        elif operation_kind == "relationship_correction":
            relationship = EconomicThemeRelationship(
                taxonomy_version_id=version_id,
                source_theme_id=UUID(str(payload["source_theme_id"])),
                target_theme_id=UUID(str(payload["target_theme_id"])),
                kind=_required_text(payload.get("kind"), "kind"),
                direction=_required_text(payload.get("direction"), "direction"),
                discriminator=str(payload.get("discriminator") or ""),
                created_by=actor,
            )
            self.session.add(relationship)
            self.session.flush()
            affected.extend(
                (str(relationship.source_theme_id), str(relationship.target_theme_id))
            )
        elif operation_kind == "facet_correction":
            theme_id = UUID(str(payload["theme_id"]))
            dimension_key = _required_text(
                payload.get("dimension_key"), "dimension_key"
            )
            value = _required_text(payload.get("normalized_value"), "normalized_value")
            action = str(payload.get("action") or "assign")
            if action == "remove":
                row = self.session.get(
                    EconomicThemeFacet, (version_id, theme_id, dimension_key, value)
                )
                if row is None:
                    raise TaxonomyOperationError("facet_assignment_not_found")
                self.session.delete(row)
                self.session.flush()
            else:
                repo.assign_facet(
                    version_id, theme_id, dimension_key, value, actor=actor
                )
            affected.append(str(theme_id))
        else:
            raise TaxonomyOperationError("unsupported_operation_kind")

        return assignments, mappings, sorted(set(affected)), unallocated

    def _revision(self, version_id: UUID, theme_id: UUID) -> EconomicThemeRevision:
        revision = self.session.get(EconomicThemeRevision, (version_id, theme_id))
        if revision is None:
            raise TaxonomyOperationError("theme_revision_not_found")
        return revision

    def _append_event(
        self,
        request_id: UUID,
        event_type: str,
        *,
        principal: AdminPrincipal,
        reason: str,
        payload: Mapping[str, Any],
    ) -> TaxonomyOperationEvent:
        current = self.session.scalar(
            select(func.max(TaxonomyOperationEvent.sequence_number)).where(
                TaxonomyOperationEvent.operation_request_id == request_id
            )
        )
        event = TaxonomyOperationEvent(
            operation_request_id=request_id,
            sequence_number=int(current or 0) + 1,
            event_type=event_type,
            actor_subject=principal.subject,
            reason=reason,
            event_payload=dict(payload),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def _has_prepared_generation(self) -> bool:
        events = self.session.scalars(
            select(ServingGenerationEvent).order_by(
                ServingGenerationEvent.serving_generation_id,
                ServingGenerationEvent.sequence_number,
            )
        ).all()
        latest: dict[UUID, str] = {}
        for event in events:
            latest[event.serving_generation_id] = event.event_type
        return "prepared" in latest.values()

    @staticmethod
    def _require_reviewer(principal: AdminPrincipal) -> None:
        if not principal.can_review_taxonomy:
            raise TaxonomyReviewForbidden("taxonomy_review_forbidden")

    @staticmethod
    def _preview_result(
        request: TaxonomyOperationRequest, preview: TaxonomyOperationPreview
    ) -> OperationPreviewResult:
        destinations = {
            item.get("destination_theme_id")
            for item in preview.mappings
            if item.get("destination_theme_id")
        }
        return OperationPreviewResult(
            preview_id=preview.id,
            request_id=request.id,
            candidate_taxonomy_version_id=preview.candidate_taxonomy_version_id,
            actor_subject=request.actor_subject,
            before_semantic_hash=preview.before_semantic_hash,
            before_artifact_integrity_hash=preview.before_artifact_integrity_hash,
            after_semantic_hash=preview.after_semantic_hash,
            after_artifact_integrity_hash=preview.after_artifact_integrity_hash,
            preview_hash=preview.preview_hash,
            destination_count=len(destinations),
            unallocated_claim_ids=(),
            validation_errors=tuple(preview.validation_errors),
        )


__all__ = [
    "EconomicTaxonomyOperationService",
    "OperationApplyResult",
    "OperationPreviewChanged",
    "OperationPreviewInvalid",
    "OperationPreviewResult",
    "TaxonomyOperationError",
    "TaxonomyReviewForbidden",
]
