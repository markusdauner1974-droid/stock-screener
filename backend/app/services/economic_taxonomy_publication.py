"""Bounded, crash-safe publication for Economic Taxonomy generations.

The coordinator deliberately owns three separate transactions: capture under a
short exclusive fence, preparation without that fence, and a final short
compare-and-set publication.  Provider calls and delivery waits never occur in
the fenced transactions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
    PublicationInvariantError,
)
from app.models.economic_taxonomy import TaxonomyVersion
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    GenerationInputManifest,
    InterpretationSelection,
    InterpretationSet,
    MetricsRevision,
    ReaderCapabilityManifest,
    ReaderSnapshotBundle,
    ReaderSnapshotEntry,
    ReaderSnapshotPointer,
    ServingGeneration,
    ServingGenerationEvent,
    TaxonomyAuthority,
    TaxonomyProjectionDeliveryAttempt,
    TaxonomyProjectionDeliveryEvent,
    TaxonomyProjectionEvent,
    TaxonomySourceRevisionLog,
)
from app.services.economic_taxonomy_fence import exclusive_publication
from app.services.economic_taxonomy_interpretations import (
    EconomicTaxonomyInterpretationService,
)
from app.services.economic_taxonomy_runtime import EconomicTaxonomyRuntimeService
from app.services.economic_theme_metrics_service import EconomicThemeMetricsService
from app.services.ui_snapshot_service import (
    GenerationSnapshotInputs,
    build_snapshot_bundle,
)


class PublicationError(RuntimeError):
    """Base error for a publication that did not switch authority."""


class PublicationForbidden(PermissionError):
    pass


class ManifestChanged(PublicationError):
    pass


class CompatibilityNotAcknowledged(PublicationError):
    pass


class ReaderCapabilityRejected(PublicationError):
    pass


class BenchmarkRejected(PublicationError):
    pass


class InjectedPublicationCrash(RuntimeError):
    """Fault used by recovery tests after a durable commit."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PublicationCutoff:
    manifest_id: UUID
    manifest_semantic_hash: str
    processing_taxonomy_version_id: UUID
    processing_head_revision: int
    expected_parent_generation_id: UUID | None
    semantic_invalidation_revision: int
    authority_epoch: int
    committed_revision_tuples: tuple[tuple[Any, ...], ...]


@dataclass(frozen=True, slots=True)
class PreparationContext:
    manifest_id: UUID
    taxonomy_version_id: UUID
    interpretation_set_id: UUID
    metrics_revision_id: UUID
    reader_snapshot_bundle_id: UUID
    expected_parent_generation_id: UUID | None
    staged_epoch: int
    target_mode: str


@dataclass(frozen=True, slots=True)
class CompatibilityProjection:
    source_lineage: str
    projection_kind: str
    projection_version: int
    target: str
    payload: Mapping[str, Any]
    origin_representation: str
    selected_interpretation_version: str
    mapping_version: str
    projection_revision: int | None = None


@dataclass(frozen=True, slots=True)
class PreparedGeneration:
    id: UUID
    manifest_id: UUID
    taxonomy_version_id: UUID
    interpretation_set_id: UUID
    metrics_revision_id: UUID
    reader_snapshot_bundle_id: UUID
    target_mode: str

    def load(self, session: Session) -> ServingGeneration:
        row = session.get(ServingGeneration, self.id)
        if row is None:
            raise KeyError(f"serving generation {self.id} not found")
        return row


@dataclass(frozen=True, slots=True)
class PublishedGeneration:
    id: UUID
    authority_epoch: int
    mode: str
    rollback_state: str


CompatibilityBuilder = Callable[
    [Session, PreparationContext], Sequence[CompatibilityProjection]
]
BenchmarkVerifier = Callable[[Session, PreparationContext], Mapping[str, Any] | bool]


class EconomicTaxonomyPublicationCoordinator:
    REQUIRED_BACKEND_CONTRACT = 1
    REQUIRED_FRONTEND_CONTRACT = 1
    REQUIRED_MIGRATION_VERSION = "0054"
    READER_KEYS = ("economic_taxonomy", "economic_themes")

    def __init__(
        self,
        session_factory,
        *,
        clock: Callable[[], datetime] = _utcnow,
        compatibility_builder: CompatibilityBuilder | None = None,
        benchmark_verifier: BenchmarkVerifier | None = None,
    ):
        self.session_factory = session_factory
        self.clock = clock
        self.compatibility_builder = (
            compatibility_builder or self._default_compatibility_builder
        )
        self.benchmark_verifier = benchmark_verifier or (
            lambda _session, _context: {
                "passed": True,
                "basis": "verified_reader_capability",
            }
        )

    def capture_cutoff(
        self,
        *,
        principal: AdminPrincipal,
        selections: Sequence[Mapping[str, Any]] | None = None,
    ) -> PublicationCutoff:
        self._require_admin(principal)
        with self.session_factory() as session:
            with exclusive_publication(session) as authority:
                if authority.processing_taxonomy_version_id is None:
                    raise PublicationInvariantError(
                        "processing_taxonomy_version_required"
                    )
                taxonomy = session.get(
                    TaxonomyVersion, authority.processing_taxonomy_version_id
                )
                if taxonomy is None or taxonomy.status != "sealed":
                    raise PublicationInvariantError(
                        "sealed_processing_taxonomy_required"
                    )
                selected = (
                    [dict(value) for value in selections]
                    if selections is not None
                    else self._current_selections(session, authority)
                )
                manifest = EconomicTaxonomyPublicationRepository(
                    session
                ).capture_manifest(
                    actor=principal.subject,
                    selections=selected,
                    authority=authority,
                )
                session.flush()
                cutoff = PublicationCutoff(
                    manifest_id=manifest.id,
                    manifest_semantic_hash=str(manifest.semantic_hash),
                    processing_taxonomy_version_id=taxonomy.id,
                    processing_head_revision=authority.processing_head_revision,
                    expected_parent_generation_id=authority.serving_generation_id,
                    semantic_invalidation_revision=(
                        authority.semantic_invalidation_revision
                    ),
                    authority_epoch=authority.authority_epoch,
                    committed_revision_tuples=tuple(
                        tuple(value) for value in manifest.committed_revision_tuples
                    ),
                )
                session.commit()
            return cutoff

    def prepare_generation(
        self,
        cutoff: PublicationCutoff,
        *,
        principal: AdminPrincipal,
        reader_capability_manifest_id: UUID,
        target_mode: str | None = None,
    ) -> PreparedGeneration:
        self._require_admin(principal)
        target_mode = target_mode or self._current_mode()
        if target_mode not in {"legacy", "shadow", "dual", "economic"}:
            raise PublicationInvariantError("invalid_target_mode")

        interpretation = EconomicTaxonomyInterpretationService(
            self.session_factory
        ).build_interpretation_set(cutoff.manifest_id, actor=principal.subject)

        with self.session_factory() as session:
            manifest = session.get(GenerationInputManifest, cutoff.manifest_id)
            taxonomy = session.get(
                TaxonomyVersion, cutoff.processing_taxonomy_version_id
            )
            capability = session.get(
                ReaderCapabilityManifest, reader_capability_manifest_id
            )
            if manifest is None or manifest.status != "sealed":
                raise PublicationInvariantError("sealed_manifest_required")
            if manifest.semantic_hash != cutoff.manifest_semantic_hash:
                raise PublicationInvariantError("captured_manifest_hash_changed")
            if taxonomy is None or taxonomy.status != "sealed":
                raise PublicationInvariantError("sealed_processing_taxonomy_required")
            self._verify_capability(capability)
            self._require_prior_acknowledgement(
                session, cutoff.expected_parent_generation_id
            )

            metrics = EconomicThemeMetricsService(session).calculate_metrics(
                taxonomy_version_id=taxonomy.id,
                interpretation_set_id=interpretation.id,
                generation_input_manifest_id=manifest.id,
                as_of=self.clock(),
                actor=principal.subject,
            )
            snapshots = build_snapshot_bundle(
                session,
                GenerationSnapshotInputs(
                    taxonomy_version_id=taxonomy.id,
                    interpretation_set_id=interpretation.id,
                    generation_input_manifest_id=manifest.id,
                    metrics_revision_id=metrics.id,
                    created_by=principal.subject,
                ),
            )
            context = PreparationContext(
                manifest_id=manifest.id,
                taxonomy_version_id=taxonomy.id,
                interpretation_set_id=interpretation.id,
                metrics_revision_id=metrics.id,
                reader_snapshot_bundle_id=snapshots.id,
                expected_parent_generation_id=cutoff.expected_parent_generation_id,
                staged_epoch=cutoff.authority_epoch,
                target_mode=target_mode,
            )
            benchmark = self.benchmark_verifier(session, context)
            if benchmark is False or (
                isinstance(benchmark, Mapping)
                and not bool(benchmark.get("passed", False))
            ):
                raise BenchmarkRejected("economic_taxonomy_benchmark_failed")

            projections = self._assign_projection_revisions(
                session, self.compatibility_builder(session, context)
            )
            expected_projections = [
                self._projection_descriptor(value) for value in projections
            ]
            semantic_payload = {
                "taxonomy_hash": taxonomy.semantic_hash,
                "manifest_hash": manifest.semantic_hash,
                "interpretation_hash": interpretation.semantic_hash,
                "metrics_hash": metrics.semantic_hash,
                "snapshot_hash": snapshots.semantic_hash,
                "target_mode": target_mode,
                "expected_projections": expected_projections,
            }
            artifact_payload = {
                **semantic_payload,
                "taxonomy_artifact_hash": taxonomy.artifact_integrity_hash,
                "manifest_artifact_hash": manifest.artifact_integrity_hash,
                "interpretation_artifact_hash": interpretation.artifact_integrity_hash,
                "metrics_artifact_hash": metrics.artifact_integrity_hash,
                "snapshot_artifact_hash": snapshots.artifact_integrity_hash,
                "created_by": principal.subject,
            }
            details = {
                "target_mode": target_mode,
                "processing_taxonomy_version_id": str(taxonomy.id),
                "processing_head_revision": cutoff.processing_head_revision,
                "expected_parent_generation_id": (
                    str(cutoff.expected_parent_generation_id)
                    if cutoff.expected_parent_generation_id
                    else None
                ),
                "semantic_invalidation_revision": (
                    cutoff.semantic_invalidation_revision
                ),
                "manifest_semantic_hash": manifest.semantic_hash,
                "component_hashes": {
                    "taxonomy": taxonomy.semantic_hash,
                    "manifest": manifest.semantic_hash,
                    "interpretation": interpretation.semantic_hash,
                    "metrics": metrics.semantic_hash,
                    "snapshot": snapshots.semantic_hash,
                },
                "component_artifact_hashes": {
                    "taxonomy": taxonomy.artifact_integrity_hash,
                    "manifest": manifest.artifact_integrity_hash,
                    "interpretation": interpretation.artifact_integrity_hash,
                    "metrics": metrics.artifact_integrity_hash,
                    "snapshot": snapshots.artifact_integrity_hash,
                },
                "expected_projections": expected_projections,
                "benchmark": dict(benchmark)
                if isinstance(benchmark, Mapping)
                else {"passed": True},
            }
            generation = EconomicTaxonomyPublicationRepository(
                session
            ).prepare_generation(
                taxonomy_version_id=taxonomy.id,
                interpretation_set_id=interpretation.id,
                metrics_revision_id=metrics.id,
                generation_input_manifest_id=manifest.id,
                reader_snapshot_bundle_id=snapshots.id,
                reader_capability_manifest_id=capability.id,
                semantic_hash=_hash(semantic_payload),
                artifact_integrity_hash=_hash(artifact_payload),
                actor=principal.subject,
                prepared_details=details,
            )
            session.flush()
            runtime = EconomicTaxonomyRuntimeService(session)
            for projection in projections:
                runtime.stage_projection(
                    generation_id=generation.id,
                    source_lineage=projection.source_lineage,
                    projection_revision=int(projection.projection_revision),
                    projection_kind=projection.projection_kind,
                    projection_version=projection.projection_version,
                    target=projection.target,
                    payload=projection.payload,
                    staged_epoch=cutoff.authority_epoch,
                    origin_representation=projection.origin_representation,
                    selected_interpretation_version=(
                        projection.selected_interpretation_version
                    ),
                    mapping_version=projection.mapping_version,
                    delivery_scope="candidate",
                )
            session.commit()
            return PreparedGeneration(
                id=generation.id,
                manifest_id=manifest.id,
                taxonomy_version_id=taxonomy.id,
                interpretation_set_id=interpretation.id,
                metrics_revision_id=metrics.id,
                reader_snapshot_bundle_id=snapshots.id,
                target_mode=target_mode,
            )

    def publish_generation(
        self,
        generation_id: UUID,
        *,
        principal: AdminPrincipal,
        notify_delivery_workers: Callable[[], Any] | None = None,
        before_commit: Callable[[], Any] | None = None,
    ) -> PublishedGeneration:
        self._require_admin(principal)
        changed: str | None = None
        result: PublishedGeneration | None = None
        with self.session_factory() as session:  # noqa: SIM117
            with exclusive_publication(session) as authority:
                generation = session.get(ServingGeneration, generation_id)
                if generation is None:
                    raise KeyError(f"serving generation {generation_id} not found")
                events = self._generation_events(session, generation.id)
                event_types = {event.event_type for event in events}
                if "published" in event_types:
                    result = PublishedGeneration(
                        id=generation.id,
                        authority_epoch=authority.authority_epoch,
                        mode=authority.mode,
                        rollback_state=authority.rollback_state,
                    )
                elif "abandoned" in event_types:
                    raise ManifestChanged("generation_abandoned")
                else:
                    prepared = next(
                        (event for event in events if event.event_type == "prepared"),
                        None,
                    )
                    if prepared is None:
                        raise PublicationInvariantError("generation_not_prepared")
                    changed = self._publication_change_reason(
                        session, authority, generation, prepared.details
                    )
                    if changed is not None:
                        self._append_generation_event(
                            session,
                            generation.id,
                            "abandoned",
                            principal.subject,
                            {"reason": changed},
                        )
                    else:
                        self._verify_generation(
                            session, authority, generation, prepared.details
                        )
                        previous_id = authority.serving_generation_id
                        target_mode = str(prepared.details["target_mode"])
                        next_epoch = authority.authority_epoch + 1
                        self._switch_reader_pointers(
                            session,
                            generation=generation,
                            authority_epoch=next_epoch,
                        )
                        authority.serving_generation_id = generation.id
                        authority.processing_taxonomy_version_id = (
                            generation.taxonomy_version_id
                        )
                        authority.mode = target_mode
                        authority.authority_epoch = next_epoch
                        authority.cutover_catch_up_cursor = list(
                            session.get(
                                GenerationInputManifest,
                                generation.generation_input_manifest_id,
                            ).committed_revision_tuples
                        )
                        projection_count = session.scalar(
                            select(func.count(TaxonomyProjectionEvent.id)).where(
                                TaxonomyProjectionEvent.serving_generation_id
                                == generation.id,
                                TaxonomyProjectionEvent.delivery_scope == "candidate",
                            )
                        )
                        authority.rollback_state = (
                            "temporarily_unavailable"
                            if target_mode != "legacy" and int(projection_count or 0)
                            else "ready"
                        )
                        authority.rollback_reason = (
                            "compatibility_delivery_pending"
                            if authority.rollback_state == "temporarily_unavailable"
                            else None
                        )
                        authority.writes_fenced = False
                        self._append_generation_event(
                            session,
                            generation.id,
                            "published",
                            principal.subject,
                            {
                                "authority_epoch": next_epoch,
                                "mode": target_mode,
                                "manifest_id": str(
                                    generation.generation_input_manifest_id
                                ),
                            },
                        )
                        if previous_id is not None:
                            self._append_generation_event(
                                session,
                                previous_id,
                                "superseded",
                                principal.subject,
                                {"by_generation_id": str(generation.id)},
                            )
                        if before_commit is not None:
                            before_commit()
                        result = PublishedGeneration(
                            id=generation.id,
                            authority_epoch=next_epoch,
                            mode=target_mode,
                            rollback_state=authority.rollback_state,
                        )
                session.commit()

        if changed is not None:
            raise ManifestChanged(changed)
        if result is None:
            raise PublicationError("publication_result_missing")
        EconomicTaxonomyRuntimeService.notify_delivery_workers(notify_delivery_workers)
        return result

    def prepare_cutover(
        self, cutoff: PublicationCutoff, **kwargs
    ) -> PreparedGeneration:
        return self.prepare_generation(cutoff, target_mode="economic", **kwargs)

    def publish_cutover(self, generation_id: UUID, **kwargs) -> PublishedGeneration:
        return self.publish_generation(generation_id, **kwargs)

    def abandon(
        self,
        generation_id: UUID,
        *,
        principal: AdminPrincipal,
        reason: str,
    ) -> None:
        self._require_admin(principal)
        if not reason.strip():
            raise ValueError("abandon_reason_required")
        with self.session_factory() as session:
            generation = session.get(ServingGeneration, generation_id)
            if generation is None:
                raise KeyError(f"serving generation {generation_id} not found")
            event_types = {
                event.event_type
                for event in self._generation_events(session, generation.id)
            }
            if "published" in event_types:
                raise PublicationError("published_generation_cannot_be_abandoned")
            if "abandoned" not in event_types:
                self._append_generation_event(
                    session,
                    generation.id,
                    "abandoned",
                    principal.subject,
                    {"reason": reason},
                )
            session.commit()

    def rollback(
        self,
        *,
        principal: AdminPrincipal,
        reader_capability_manifest_id: UUID | None = None,
        reason: str = "operator_requested_rollback",
    ) -> PublishedGeneration:
        self._require_admin(principal)
        with self.session_factory() as session:
            authority = session.get(TaxonomyAuthority, 1)
            if authority is None or authority.serving_generation_id is None:
                raise PublicationError("serving_generation_required_for_rollback")
            current_id = authority.serving_generation_id
            current = session.get(ServingGeneration, current_id)
            if current is None:
                raise PublicationError("serving_generation_missing")
            capability_id = reader_capability_manifest_id or (
                current.reader_capability_manifest_id
            )
            selections = list(
                session.get(
                    GenerationInputManifest,
                    current.generation_input_manifest_id,
                ).selections
            )
            healthy = EconomicTaxonomyRuntimeService(session).generation_acknowledged(
                current_id
            )

        if not healthy:
            self._begin_rollback_recovery(
                generation_id=current_id,
                principal=principal,
                reason=reason,
            )
            try:
                self._rebuild_legacy_projections(current_id, principal=principal)
            except Exception as exc:
                self._mark_rollback_recovery_failed(str(exc))
                raise

        cutoff = self.capture_cutoff(principal=principal, selections=selections)
        prepared = self.prepare_generation(
            cutoff,
            principal=principal,
            reader_capability_manifest_id=capability_id,
            target_mode="legacy",
        )
        return self.publish_generation(prepared.id, principal=principal)

    def refresh_rollback_availability(self) -> str:
        """Promote rollback readiness after asynchronous mirrors catch up."""

        with self.session_factory() as session:  # noqa: SIM117
            with exclusive_publication(session) as authority:
                generation_id = authority.serving_generation_id
                if generation_id is None:
                    state = authority.rollback_state
                elif EconomicTaxonomyRuntimeService(session).generation_acknowledged(
                    generation_id
                ):
                    authority.rollback_state = "ready"
                    authority.rollback_reason = None
                    state = "ready"
                else:
                    authority.rollback_state = "temporarily_unavailable"
                    authority.rollback_reason = "compatibility_delivery_pending"
                    state = authority.rollback_state
                session.commit()
                return state

    def _publication_change_reason(
        self,
        session: Session,
        authority: TaxonomyAuthority,
        generation: ServingGeneration,
        details: Mapping[str, Any],
    ) -> str | None:
        manifest = session.get(
            GenerationInputManifest, generation.generation_input_manifest_id
        )
        validation = EconomicTaxonomyPublicationRepository(session).validate_manifest(
            manifest
        )
        if not validation.valid:
            return validation.error
        if str(authority.processing_taxonomy_version_id) != str(
            details.get("processing_taxonomy_version_id")
        ):
            return "processing_taxonomy_changed"
        if authority.processing_head_revision != int(
            details.get("processing_head_revision", -1)
        ):
            return "processing_head_changed"
        return None

    def _verify_generation(
        self,
        session: Session,
        authority: TaxonomyAuthority,
        generation: ServingGeneration,
        details: Mapping[str, Any],
    ) -> None:
        taxonomy = session.get(TaxonomyVersion, generation.taxonomy_version_id)
        manifest = session.get(
            GenerationInputManifest, generation.generation_input_manifest_id
        )
        interpretation = session.get(
            InterpretationSet, generation.interpretation_set_id
        )
        metrics = session.get(MetricsRevision, generation.metrics_revision_id)
        snapshots = session.get(
            ReaderSnapshotBundle, generation.reader_snapshot_bundle_id
        )
        capability = session.get(
            ReaderCapabilityManifest, generation.reader_capability_manifest_id
        )
        if any(
            value is None
            for value in (taxonomy, manifest, interpretation, metrics, snapshots)
        ):
            raise PublicationInvariantError("generation_reference_missing")
        if taxonomy.status != "sealed" or any(
            value.status != "sealed"
            for value in (manifest, interpretation, metrics, snapshots)
        ):
            raise PublicationInvariantError("generation_payload_unsealed")
        component_hashes = details.get("component_hashes", {})
        actual_hashes = {
            "taxonomy": taxonomy.semantic_hash,
            "manifest": manifest.semantic_hash,
            "interpretation": interpretation.semantic_hash,
            "metrics": metrics.semantic_hash,
            "snapshot": snapshots.semantic_hash,
        }
        if component_hashes != actual_hashes:
            raise PublicationInvariantError("generation_component_hash_changed")
        artifact_hashes = details.get("component_artifact_hashes", {})
        actual_artifact_hashes = {
            "taxonomy": taxonomy.artifact_integrity_hash,
            "manifest": manifest.artifact_integrity_hash,
            "interpretation": interpretation.artifact_integrity_hash,
            "metrics": metrics.artifact_integrity_hash,
            "snapshot": snapshots.artifact_integrity_hash,
        }
        if artifact_hashes != actual_artifact_hashes:
            raise PublicationInvariantError("generation_artifact_hash_changed")
        semantic_payload = {
            "taxonomy_hash": taxonomy.semantic_hash,
            "manifest_hash": manifest.semantic_hash,
            "interpretation_hash": interpretation.semantic_hash,
            "metrics_hash": metrics.semantic_hash,
            "snapshot_hash": snapshots.semantic_hash,
            "target_mode": details.get("target_mode"),
            "expected_projections": list(details.get("expected_projections", [])),
        }
        if generation.semantic_hash != _hash(semantic_payload):
            raise PublicationInvariantError("generation_semantic_hash_changed")
        artifact_payload = {
            **semantic_payload,
            "taxonomy_artifact_hash": taxonomy.artifact_integrity_hash,
            "manifest_artifact_hash": manifest.artifact_integrity_hash,
            "interpretation_artifact_hash": interpretation.artifact_integrity_hash,
            "metrics_artifact_hash": metrics.artifact_integrity_hash,
            "snapshot_artifact_hash": snapshots.artifact_integrity_hash,
            "created_by": generation.created_by,
        }
        if generation.artifact_integrity_hash != _hash(artifact_payload):
            raise PublicationInvariantError("generation_artifact_integrity_changed")
        if manifest.semantic_hash != details.get("manifest_semantic_hash"):
            raise PublicationInvariantError("manifest_hash_changed")
        self._verify_snapshot_entries(session, snapshots)
        self._verify_capability(capability)
        self._require_prior_acknowledgement(session, authority.serving_generation_id)
        self._verify_staged_projections(session, generation, details)

    def _verify_snapshot_entries(
        self, session: Session, bundle: ReaderSnapshotBundle
    ) -> None:
        entries = session.scalars(
            select(ReaderSnapshotEntry)
            .where(ReaderSnapshotEntry.reader_snapshot_bundle_id == bundle.id)
            .order_by(
                ReaderSnapshotEntry.snapshot_kind, ReaderSnapshotEntry.resource_key
            )
        ).all()
        if {entry.snapshot_kind for entry in entries} != set(self.READER_KEYS):
            raise PublicationInvariantError("reader_snapshot_incomplete")
        actual = [
            {
                "snapshot_kind": entry.snapshot_kind,
                "resource_key": entry.resource_key,
                "payload_hash": _hash(entry.payload),
            }
            for entry in entries
        ]
        if any(
            entry.payload_hash != item["payload_hash"]
            for entry, item in zip(entries, actual, strict=True)
        ):
            raise PublicationInvariantError("reader_snapshot_entry_hash_changed")
        indexed = sorted(
            bundle.payload.get("entries", []),
            key=lambda value: (value["snapshot_kind"], value["resource_key"]),
        )
        if indexed != actual:
            raise PublicationInvariantError("reader_snapshot_index_changed")

    def _verify_staged_projections(
        self,
        session: Session,
        generation: ServingGeneration,
        details: Mapping[str, Any],
    ) -> None:
        expected = list(details.get("expected_projections", []))
        rows = session.scalars(
            select(TaxonomyProjectionEvent)
            .where(
                TaxonomyProjectionEvent.serving_generation_id == generation.id,
                TaxonomyProjectionEvent.delivery_scope == "candidate",
            )
            .order_by(
                TaxonomyProjectionEvent.source_lineage,
                TaxonomyProjectionEvent.projection_kind,
                TaxonomyProjectionEvent.target_representation,
                TaxonomyProjectionEvent.projection_revision,
            )
        ).all()
        actual = [self._event_descriptor(row) for row in rows]
        if actual != expected:
            raise PublicationInvariantError("candidate_projection_set_changed")

    def _switch_reader_pointers(
        self,
        session: Session,
        *,
        generation: ServingGeneration,
        authority_epoch: int,
    ) -> None:
        bundle_keys = set(
            session.scalars(
                select(ReaderSnapshotEntry.snapshot_kind).where(
                    ReaderSnapshotEntry.reader_snapshot_bundle_id
                    == generation.reader_snapshot_bundle_id
                )
            )
        )
        if bundle_keys != set(self.READER_KEYS):
            raise PublicationInvariantError("reader_snapshot_incomplete")
        for reader_key in self.READER_KEYS:
            pointer = session.get(ReaderSnapshotPointer, reader_key)
            if pointer is None:
                pointer = ReaderSnapshotPointer(reader_key=reader_key)
                session.add(pointer)
            pointer.serving_generation_id = generation.id
            pointer.reader_snapshot_bundle_id = generation.reader_snapshot_bundle_id
            pointer.authority_epoch = authority_epoch

    def _assign_projection_revisions(
        self,
        session: Session,
        projections: Sequence[CompatibilityProjection],
    ) -> list[CompatibilityProjection]:
        assigned: list[CompatibilityProjection] = []
        seen: set[tuple[str, str, str]] = set()
        for projection in sorted(
            projections,
            key=lambda value: (
                value.source_lineage,
                value.projection_kind,
                value.target,
            ),
        ):
            key = (
                projection.source_lineage,
                projection.projection_kind,
                projection.target,
            )
            if key in seen:
                raise PublicationInvariantError("duplicate_candidate_projection")
            seen.add(key)
            revision = projection.projection_revision
            if revision is None:
                latest = session.scalar(
                    select(func.max(TaxonomyProjectionEvent.projection_revision)).where(
                        TaxonomyProjectionEvent.source_lineage
                        == projection.source_lineage,
                        TaxonomyProjectionEvent.projection_kind
                        == projection.projection_kind,
                        TaxonomyProjectionEvent.target_representation
                        == projection.target,
                    )
                )
                revision = int(latest or 0) + 1
            assigned.append(replace(projection, projection_revision=revision))
        return assigned

    @staticmethod
    def _projection_descriptor(
        projection: CompatibilityProjection,
    ) -> dict[str, Any]:
        payload = {
            **dict(projection.payload),
            "origin_representation": projection.origin_representation,
            "selected_interpretation_version": (
                projection.selected_interpretation_version
            ),
            "mapping_version": projection.mapping_version,
        }
        return {
            "source_lineage": projection.source_lineage,
            "projection_revision": projection.projection_revision,
            "projection_kind": projection.projection_kind,
            "projection_version": projection.projection_version,
            "target": projection.target,
            "payload_hash": _hash(payload),
        }

    @staticmethod
    def _event_descriptor(event: TaxonomyProjectionEvent) -> dict[str, Any]:
        return {
            "source_lineage": event.source_lineage,
            "projection_revision": event.projection_revision,
            "projection_kind": event.projection_kind,
            "projection_version": event.projection_version,
            "target": event.target_representation,
            "payload_hash": event.payload_hash,
        }

    def _default_compatibility_builder(
        self, session: Session, context: PreparationContext
    ) -> Sequence[CompatibilityProjection]:
        # Carry forward every latest parent projection, then replace the
        # economic-to-legacy theme projection from the newly selected
        # interpretation.  This keeps Social and other producer-owned lineages
        # complete without treating route provenance as independent evidence.
        manifest = session.get(GenerationInputManifest, context.manifest_id)
        current: dict[str, set[str]] = {}
        for lineage_id, theme_id in session.execute(
            select(
                InterpretationSelection.source_lineage_id,
                ClaimAssignment.economic_theme_id,
            )
            .join(
                ClaimAssignment,
                ClaimAssignment.classification_attempt_id
                == InterpretationSelection.selected_classification_attempt_id,
            )
            .where(
                InterpretationSelection.interpretation_set_id
                == context.interpretation_set_id
            )
        ):
            current.setdefault(str(lineage_id), set()).add(str(theme_id))
        for value in manifest.selections or []:
            if value.get("lineage"):
                current.setdefault(str(value["lineage"]), set())

        projections: dict[tuple[str, str, str], CompatibilityProjection] = {}
        previous_theme_lineages: set[str] = set()
        if context.expected_parent_generation_id is not None:
            parent_rows = session.scalars(
                select(TaxonomyProjectionEvent)
                .where(
                    TaxonomyProjectionEvent.serving_generation_id
                    == context.expected_parent_generation_id,
                    TaxonomyProjectionEvent.delivery_scope == "candidate",
                )
                .order_by(TaxonomyProjectionEvent.projection_revision)
            ).all()
            for event in parent_rows:
                key = (
                    event.source_lineage,
                    event.projection_kind,
                    event.target_representation,
                )
                if (
                    event.projection_kind == "legacy_theme"
                    and event.target_representation == "legacy"
                ):
                    previous_theme_lineages.add(event.source_lineage)
                    continue
                payload = dict(event.payload)
                selected_version = str(
                    payload.pop(
                        "selected_interpretation_version",
                        context.interpretation_set_id,
                    )
                )
                mapping_version = str(
                    payload.pop("mapping_version", context.taxonomy_version_id)
                )
                origin = str(
                    payload.pop("origin_representation", event.origin_representation)
                )
                projections[key] = CompatibilityProjection(
                    source_lineage=event.source_lineage,
                    projection_kind=event.projection_kind,
                    projection_version=event.projection_version,
                    target=event.target_representation,
                    payload=payload,
                    origin_representation=origin,
                    selected_interpretation_version=selected_version,
                    mapping_version=mapping_version,
                )

        for lineage in sorted(set(current) | previous_theme_lineages):
            key = (lineage, "legacy_theme", "legacy")
            projections[key] = CompatibilityProjection(
                source_lineage=lineage,
                projection_kind="legacy_theme",
                projection_version=1,
                target="legacy",
                payload={"themes": sorted(current.get(lineage, set()))},
                origin_representation="economic",
                selected_interpretation_version=str(context.interpretation_set_id),
                mapping_version=str(context.taxonomy_version_id),
            )
        return list(projections.values())

    def _require_prior_acknowledgement(
        self, session: Session, generation_id: UUID | None
    ) -> None:
        if generation_id is None:
            return
        if not EconomicTaxonomyRuntimeService(session).generation_acknowledged(
            generation_id
        ):
            raise CompatibilityNotAcknowledged(
                "prior_generation_compatibility_not_acknowledged"
            )

    def _verify_capability(self, capability: ReaderCapabilityManifest | None) -> None:
        if capability is None:
            raise ReaderCapabilityRejected("reader_capability_missing")
        if (
            capability.backend_contract != self.REQUIRED_BACKEND_CONTRACT
            or capability.frontend_contract != self.REQUIRED_FRONTEND_CONTRACT
            or capability.migration_version != self.REQUIRED_MIGRATION_VERSION
            or not capability.consumer_test_hash.strip()
        ):
            raise ReaderCapabilityRejected("reader_capability_incompatible")

    @staticmethod
    def _generation_events(
        session: Session, generation_id: UUID
    ) -> list[ServingGenerationEvent]:
        return list(
            session.scalars(
                select(ServingGenerationEvent)
                .where(ServingGenerationEvent.serving_generation_id == generation_id)
                .order_by(ServingGenerationEvent.sequence_number)
            )
        )

    def _append_generation_event(
        self,
        session: Session,
        generation_id: UUID,
        event_type: str,
        actor: str,
        details: Mapping[str, Any],
    ) -> ServingGenerationEvent:
        latest = session.scalar(
            select(func.max(ServingGenerationEvent.sequence_number)).where(
                ServingGenerationEvent.serving_generation_id == generation_id
            )
        )
        event = ServingGenerationEvent(
            serving_generation_id=generation_id,
            sequence_number=int(latest or 0) + 1,
            event_type=event_type,
            actor=actor,
            details=dict(details),
        )
        session.add(event)
        session.flush()
        return event

    def _begin_rollback_recovery(
        self,
        *,
        generation_id: UUID,
        principal: AdminPrincipal,
        reason: str,
    ) -> None:
        with self.session_factory() as session:  # noqa: SIM117
            with exclusive_publication(session) as authority:
                authority.writes_fenced = True
                authority.rollback_state = "rollback_recovery"
                authority.rollback_reason = reason
                latest = session.scalar(
                    select(func.max(TaxonomySourceRevisionLog.revision_number)).where(
                        TaxonomySourceRevisionLog.producer_kind == "publication",
                        TaxonomySourceRevisionLog.logical_source_key
                        == f"rollback:{generation_id}",
                        TaxonomySourceRevisionLog.revision_kind == "rollback_recovery",
                    )
                )
                EconomicTaxonomyPublicationRepository(session).append_source_revision(
                    producer_kind="publication",
                    logical_source_key=f"rollback:{generation_id}",
                    revision_kind="rollback_recovery",
                    revision_number=int(latest or 0) + 1,
                    content_hash=_hash(
                        {
                            "generation_id": str(generation_id),
                            "reason": reason,
                            "actor": principal.subject,
                        }
                    ),
                    authority_epoch=authority.authority_epoch,
                )
                session.commit()

    def _rebuild_legacy_projections(
        self, generation_id: UUID, *, principal: AdminPrincipal
    ) -> None:
        with self.session_factory() as session:
            authority = session.get(TaxonomyAuthority, 1)
            rows = session.scalars(
                select(TaxonomyProjectionEvent)
                .where(
                    TaxonomyProjectionEvent.serving_generation_id == generation_id,
                    TaxonomyProjectionEvent.delivery_scope == "candidate",
                )
                .order_by(
                    TaxonomyProjectionEvent.source_lineage,
                    TaxonomyProjectionEvent.projection_kind,
                    TaxonomyProjectionEvent.projection_revision,
                )
            ).all()
            runtime = EconomicTaxonomyRuntimeService(session)
            now = self.clock()
            for event in rows:
                completed = session.scalar(
                    select(TaxonomyProjectionDeliveryEvent.id)
                    .join(
                        TaxonomyProjectionDeliveryAttempt,
                        TaxonomyProjectionDeliveryAttempt.id
                        == TaxonomyProjectionDeliveryEvent.delivery_attempt_id,
                    )
                    .where(
                        TaxonomyProjectionDeliveryAttempt.projection_event_id
                        == event.id,
                        TaxonomyProjectionDeliveryEvent.outcome.in_(
                            ("success", "stale_noop")
                        ),
                    )
                )
                if completed is not None:
                    continue
                attempt_number = (
                    int(
                        session.scalar(
                            select(
                                func.max(
                                    TaxonomyProjectionDeliveryAttempt.attempt_number
                                )
                            ).where(
                                TaxonomyProjectionDeliveryAttempt.projection_event_id
                                == event.id
                            )
                        )
                        or 0
                    )
                    + 1
                )
                attempt = TaxonomyProjectionDeliveryAttempt(
                    projection_event_id=event.id,
                    attempt_number=attempt_number,
                    claimed_epoch=authority.authority_epoch,
                    lease_token=uuid4(),
                    lease_owner=f"rollback-recovery:{principal.subject}",
                    lease_expires_at=now + timedelta(minutes=5),
                )
                session.add(attempt)
                session.flush()
                applied = runtime.apply_replacement(
                    target=event.target_representation,
                    source_lineage=event.source_lineage,
                    projection_kind=event.projection_kind,
                    projection_revision=event.projection_revision,
                    payload=event.payload,
                    origin_representation=event.origin_representation,
                    projection_event_id=event.id,
                )
                session.add(
                    TaxonomyProjectionDeliveryEvent(
                        delivery_attempt_id=attempt.id,
                        outcome="success" if applied else "stale_noop",
                        details={"rollback_recovery": True},
                    )
                )
            session.flush()
            if not runtime.generation_acknowledged(generation_id):
                raise CompatibilityNotAcknowledged(
                    "rollback_recovery_projection_incomplete"
                )
            authority.rollback_state = "recovered"
            authority.rollback_reason = None
            session.commit()

    def _mark_rollback_recovery_failed(self, reason: str) -> None:
        with self.session_factory() as session:  # noqa: SIM117
            with exclusive_publication(session) as authority:
                authority.writes_fenced = True
                authority.rollback_state = "recovery_failed"
                authority.rollback_reason = reason
                session.commit()

    def _current_mode(self) -> str:
        with self.session_factory() as session:
            authority = session.get(TaxonomyAuthority, 1)
            return authority.mode if authority is not None else "legacy"

    @staticmethod
    def _current_selections(
        session: Session, authority: TaxonomyAuthority
    ) -> list[dict[str, Any]]:
        if authority.serving_generation_id is None:
            return []
        generation = session.get(ServingGeneration, authority.serving_generation_id)
        if generation is None:
            return []
        manifest = session.get(
            GenerationInputManifest, generation.generation_input_manifest_id
        )
        return list(manifest.selections or []) if manifest is not None else []

    @staticmethod
    def _require_admin(principal: AdminPrincipal) -> None:
        if not principal.can_review_taxonomy:
            raise PublicationForbidden("taxonomy_publication_forbidden")


__all__ = [
    "BenchmarkRejected",
    "CompatibilityNotAcknowledged",
    "CompatibilityProjection",
    "EconomicTaxonomyPublicationCoordinator",
    "InjectedPublicationCrash",
    "ManifestChanged",
    "PreparationContext",
    "PreparedGeneration",
    "PublicationCutoff",
    "PublicationError",
    "PublicationForbidden",
    "PublishedGeneration",
    "ReaderCapabilityRejected",
]
