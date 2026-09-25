"""Reviewed legacy migration and fail-closed Economic Taxonomy benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.infra.db.models.social_analysis import SocialThemeAssociation
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
)
from app.models.economic_taxonomy import (
    EconomicThemeRevision,
    LegacyClaimAllocation,
    LegacyDestinationMapping,
    LegacyIdentityDisposition,
    TaxonomyVersion,
)
from app.models.economic_taxonomy_runtime import (
    TaxonomyMigrationProgressEvent,
    TaxonomyMigrationReview,
    TaxonomyMigrationRun,
    TaxonomySourceRevisionLog,
)
from app.models.theme import ThemeCluster, ThemeConstituent, ThemeMention
from app.models.theme_intelligence import (
    ThemeDevelopmentObservation,
    ThemeDevelopmentTheme,
)
from app.services.economic_taxonomy_fence import producer_write
from app.utils.file_hashing import canonical_json_sha256 as _hash


class EconomicTaxonomyMigrationError(ValueError):
    """Base error for durable legacy migration."""


class MigrationReviewForbidden(EconomicTaxonomyMigrationError):
    pass


class MigrationInputError(EconomicTaxonomyMigrationError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    migration_run_id: UUID
    entries: tuple[tuple[str, str, str, int, str, str], ...]
    semantic_hash: str


_DISPOSITIONS = {
    "mapped",
    "split_required",
    "merged_equivalent",
    "not_a_theme",
    "deferred",
}


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationInputError(f"{name}_required")
    return value.strip()


class EconomicTaxonomyMigrationService:
    """Seal migration inputs and apply only authenticated reviewed mappings."""

    def __init__(
        self,
        session: Session,
        *,
        principal: AdminPrincipal,
        expected_epoch: int,
    ):
        self.session = session
        self.principal = principal
        self.expected_epoch = expected_epoch

    def build_migration(self, dataset: dict[str, Any]) -> TaxonomyMigrationRun:
        self._require_reviewer()
        normalized = self._normalize_dataset(dataset)
        taxonomy_id = UUID(normalized["taxonomy_version_id"])
        taxonomy = self.session.get(TaxonomyVersion, taxonomy_id)
        if taxonomy is None or taxonomy.status != "draft":
            raise MigrationInputError("draft_migration_taxonomy_required")
        repository = EconomicTaxonomyRepository(self.session)
        taxonomy_semantic_hash = repository.semantic_hash(taxonomy.id)
        taxonomy_artifact_hash = repository.artifact_integrity_hash(taxonomy.id)
        policy_bundle_hash = _hash(normalized["policy_bundle"])
        source_hashes = [
            {
                "legacy_theme_cluster_id": row["legacy_theme_cluster_id"],
                "source_hash": row["source_hash"],
            }
            for row in normalized["legacy_identities"]
        ]
        semantic_payload = {
            "dataset_manifest": normalized,
            "source_hashes": source_hashes,
            "taxonomy_semantic_hash": taxonomy_semantic_hash,
            "policy_bundle_hash": policy_bundle_hash,
            "migration_policy_version": normalized["migration_policy_version"],
        }
        input_hash = _hash(semantic_payload)
        existing = self.session.scalar(
            select(TaxonomyMigrationRun).where(
                TaxonomyMigrationRun.input_semantic_hash == input_hash
            )
        )
        if existing is not None:
            return existing

        with producer_write(
            self.session,
            expected_epoch=self.expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ) as authority:
            existing = self.session.scalar(
                select(TaxonomyMigrationRun).where(
                    TaxonomyMigrationRun.input_semantic_hash == input_hash
                )
            )
            if existing is not None:
                return existing
            run = TaxonomyMigrationRun(
                taxonomy_version_id=taxonomy.id,
                status="unsealed",
                dataset_manifest=normalized,
                source_hashes=source_hashes,
                taxonomy_semantic_hash=taxonomy_semantic_hash,
                taxonomy_artifact_integrity_hash=taxonomy_artifact_hash,
                policy_bundle=normalized["policy_bundle"],
                policy_bundle_hash=policy_bundle_hash,
                migration_policy_version=normalized["migration_policy_version"],
                input_semantic_hash=input_hash,
                identity_count=len(normalized["legacy_identities"]),
                reviewed_identity_count_cache=0,
                coverage_complete_cache=not normalized["legacy_identities"],
                created_by=self.principal.subject,
            )
            self.session.add(run)
            self.session.flush()
            run.seal(
                artifact_integrity_hash=_hash(
                    {**semantic_payload, "run_id": str(run.id)}
                )
            )
            self.session.flush()
            self._append_event(
                run,
                "started",
                reason="Migration input manifest sealed.",
                payload={
                    "input_semantic_hash": input_hash,
                    "identity_count": run.identity_count,
                },
            )
            self._append_event(
                run,
                "progress",
                reason="Legacy source snapshot admitted for review.",
                payload={"reviewed_identity_count": 0},
            )
            EconomicTaxonomyPublicationRepository(
                self.session
            ).append_source_revision(
                producer_kind="migration",
                logical_source_key=f"migration_run:{run.id}",
                revision_kind="migration_backfill",
                revision_number=1,
                content_hash=input_hash,
                authority_epoch=authority.authority_epoch,
            )
            if run.coverage_complete:
                self._append_event(
                    run,
                    "completed",
                    reason="Migration contains no legacy identities.",
                    payload={"coverage_complete": True},
                )
            self.session.flush()
            return run

    build = build_migration

    def capture_legacy_dataset(
        self,
        *,
        taxonomy_version_id: UUID,
        migration_policy_version: str,
        policy_bundle: dict[str, Any],
    ) -> dict[str, Any]:
        """Freeze legacy identity and current-claim inputs before migration."""

        self._require_reviewer()
        identities = []
        clusters = self.session.scalars(
            select(ThemeCluster).order_by(ThemeCluster.id)
        ).all()
        for cluster in clusters:
            mentions = self.session.scalars(
                select(ThemeMention)
                .where(ThemeMention.theme_cluster_id == cluster.id)
                .order_by(ThemeMention.id)
            ).all()
            constituents = self.session.scalars(
                select(ThemeConstituent)
                .where(
                    ThemeConstituent.theme_cluster_id == cluster.id,
                    ThemeConstituent.is_active.is_(True),
                )
                .order_by(ThemeConstituent.id)
            ).all()
            social = self.session.scalars(
                select(SocialThemeAssociation)
                .where(SocialThemeAssociation.theme_cluster_id == cluster.id)
                .order_by(SocialThemeAssociation.id)
            ).all()
            developments = self.session.scalars(
                select(ThemeDevelopmentTheme)
                .join(
                    ThemeDevelopmentObservation,
                    ThemeDevelopmentObservation.id
                    == ThemeDevelopmentTheme.observation_id,
                )
                .where(
                    ThemeDevelopmentTheme.theme_id == cluster.id,
                    ThemeDevelopmentObservation.superseded.is_(False),
                )
                .order_by(ThemeDevelopmentTheme.observation_id)
            ).all()
            current_claims = [
                {
                    "allocation_kind": "mention",
                    "allocation_key": f"theme_mention:{row.id}",
                }
                for row in mentions
            ]
            current_claims.extend(
                {
                    "allocation_kind": "constituent",
                    "allocation_key": f"theme_constituent:{row.id}",
                }
                for row in constituents
            )
            current_claims.extend(
                {
                    "allocation_kind": "social_association",
                    "allocation_key": f"social_theme_association:{row.id}",
                }
                for row in social
            )
            current_claims.extend(
                {
                    "allocation_kind": "development",
                    "allocation_key": (
                        f"theme_development_observation:{row.observation_id}"
                    ),
                }
                for row in developments
            )
            source_payload = {
                "cluster": {
                    "id": cluster.id,
                    "canonical_key": cluster.canonical_key,
                    "display_name": cluster.display_name,
                    "pipeline": cluster.pipeline,
                    "aliases": cluster.aliases or [],
                    "description": cluster.description,
                    "lifecycle_state": cluster.lifecycle_state,
                },
                "mentions": [
                    {
                        "id": row.id,
                        "content_item_id": row.content_item_id,
                        "canonical_theme": row.canonical_theme,
                        "pipeline": row.pipeline,
                    }
                    for row in mentions
                ],
                "constituents": [
                    {"id": row.id, "symbol": row.symbol, "is_active": row.is_active}
                    for row in constituents
                ],
                "social_associations": [
                    {"id": row.id, "state": row.state, "version": row.version}
                    for row in social
                ],
                "development_observation_ids": [
                    row.observation_id for row in developments
                ],
            }
            identities.append(
                {
                    "legacy_theme_cluster_id": cluster.id,
                    "source_hash": _hash(source_payload),
                    "current_claims": current_claims,
                }
            )
        return self._normalize_dataset(
            {
                "taxonomy_version_id": str(taxonomy_version_id),
                "migration_policy_version": migration_policy_version,
                "policy_bundle": policy_bundle,
                "legacy_identities": identities,
            }
        )

    def get(self, run_id: UUID) -> TaxonomyMigrationRun:
        run = self.session.get(TaxonomyMigrationRun, run_id)
        if run is None:
            raise MigrationInputError("migration_run_not_found")
        return run

    def review_split(
        self,
        run_id: UUID,
        legacy_theme_cluster_id: int,
        *,
        destination_theme_ids,
        allocations,
        reason: str,
    ) -> TaxonomyMigrationRun:
        return self.review_disposition(
            run_id,
            legacy_theme_cluster_id,
            disposition="split_required",
            destination_theme_ids=destination_theme_ids,
            allocations=allocations,
            reason=reason,
        )

    def review_disposition(
        self,
        run_id: UUID,
        legacy_theme_cluster_id: int,
        *,
        disposition: str,
        destination_theme_ids=(),
        allocations=(),
        reason: str,
    ) -> TaxonomyMigrationRun:
        self._require_reviewer()
        reason = _required_text(reason, "reason")
        if disposition not in _DISPOSITIONS:
            raise MigrationInputError("invalid_migration_disposition")
        destination_ids = tuple(
            sorted({UUID(str(value)) for value in destination_theme_ids}, key=str)
        )
        normalized_allocations = self._normalize_allocations(allocations)

        with producer_write(
            self.session,
            expected_epoch=self.expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ) as authority:
            run = self.session.execute(
                select(TaxonomyMigrationRun)
                .where(TaxonomyMigrationRun.id == run_id)
                .with_for_update()
            ).scalar_one_or_none()
            if run is None:
                raise MigrationInputError("migration_run_not_found")
            identity = self._identity(run, legacy_theme_cluster_id)
            self._validate_review_shape(
                run,
                identity,
                disposition=disposition,
                destination_ids=destination_ids,
                allocations=normalized_allocations,
            )
            current = self.session.get(
                LegacyIdentityDisposition,
                (run.taxonomy_version_id, legacy_theme_cluster_id),
            )
            if current is None:
                current = LegacyIdentityDisposition(
                    taxonomy_version_id=run.taxonomy_version_id,
                    legacy_theme_cluster_id=legacy_theme_cluster_id,
                    disposition=disposition,
                    created_by=self.principal.subject,
                    review_comment=reason,
                )
                self.session.add(current)
                self.session.flush()
            elif current.disposition != disposition:
                raise MigrationInputError("migration_disposition_already_reviewed")

            persisted_destination_ids = set(
                self.session.scalars(
                    select(LegacyDestinationMapping.destination_theme_id).where(
                        LegacyDestinationMapping.taxonomy_version_id
                        == run.taxonomy_version_id,
                        LegacyDestinationMapping.legacy_theme_cluster_id
                        == legacy_theme_cluster_id,
                    )
                ).all()
            )
            if not persisted_destination_ids.issubset(set(destination_ids)):
                raise MigrationInputError("migration_destination_conflict")
            for destination_id in destination_ids:
                key = (
                    run.taxonomy_version_id,
                    legacy_theme_cluster_id,
                    destination_id,
                )
                if self.session.get(LegacyDestinationMapping, key) is None:
                    self.session.add(
                        LegacyDestinationMapping(
                            taxonomy_version_id=run.taxonomy_version_id,
                            legacy_theme_cluster_id=legacy_theme_cluster_id,
                            destination_theme_id=destination_id,
                            created_by=self.principal.subject,
                            review_comment=reason,
                        )
                    )
            self.session.flush()
            for allocation in normalized_allocations:
                key = (
                    run.taxonomy_version_id,
                    legacy_theme_cluster_id,
                    allocation["allocation_kind"],
                    allocation["allocation_key"],
                )
                existing = self.session.get(LegacyClaimAllocation, key)
                if existing is not None:
                    expected_destination = allocation.get("destination_theme_id")
                    if (
                        str(existing.destination_theme_id)
                        if existing.destination_theme_id is not None
                        else None
                    ) != expected_destination or (
                        existing.reviewed_exclusion
                        != allocation.get("reviewed_exclusion")
                    ):
                        raise MigrationInputError("migration_allocation_conflict")
                    continue
                self.session.add(
                    LegacyClaimAllocation(
                        taxonomy_version_id=run.taxonomy_version_id,
                        legacy_theme_cluster_id=legacy_theme_cluster_id,
                        allocation_kind=allocation["allocation_kind"],
                        allocation_key=allocation["allocation_key"],
                        destination_theme_id=(
                            UUID(allocation["destination_theme_id"])
                            if allocation.get("destination_theme_id")
                            else None
                        ),
                        reviewed_exclusion=allocation.get("reviewed_exclusion"),
                        created_by=self.principal.subject,
                        review_comment=reason,
                    )
                )
            self.session.flush()

            persisted_destinations = self.session.scalars(
                select(LegacyDestinationMapping).where(
                    LegacyDestinationMapping.taxonomy_version_id
                    == run.taxonomy_version_id,
                    LegacyDestinationMapping.legacy_theme_cluster_id
                    == legacy_theme_cluster_id,
                )
            ).all()
            persisted_allocations = self.session.scalars(
                select(LegacyClaimAllocation).where(
                    LegacyClaimAllocation.taxonomy_version_id
                    == run.taxonomy_version_id,
                    LegacyClaimAllocation.legacy_theme_cluster_id
                    == legacy_theme_cluster_id,
                )
            ).all()
            full_allocations = sorted(
                (
                    {
                        "allocation_kind": row.allocation_kind,
                        "allocation_key": row.allocation_key,
                        "destination_theme_id": (
                            str(row.destination_theme_id)
                            if row.destination_theme_id is not None
                            else None
                        ),
                        "reviewed_exclusion": row.reviewed_exclusion,
                    }
                    for row in persisted_allocations
                ),
                key=lambda value: (
                    value["allocation_kind"], value["allocation_key"]
                ),
            )
            current_claims = {
                (row["allocation_kind"], row["allocation_key"])
                for row in identity["current_claims"]
            }
            if any(
                (row["allocation_kind"], row["allocation_key"])
                not in current_claims
                for row in full_allocations
            ):
                raise MigrationInputError("migration_allocation_conflict")

            review_revision = (
                self.session.scalar(
                    select(func.max(TaxonomyMigrationReview.review_revision)).where(
                        TaxonomyMigrationReview.migration_run_id == run.id,
                        TaxonomyMigrationReview.legacy_theme_cluster_id
                        == legacy_theme_cluster_id,
                    )
                )
                or 0
            ) + 1
            review_payload = {
                "legacy_theme_cluster_id": legacy_theme_cluster_id,
                "review_revision": review_revision,
                "disposition": disposition,
                "destination_theme_ids": sorted(
                    str(row.destination_theme_id)
                    for row in persisted_destinations
                ),
                "allocations": full_allocations,
                "reviewer_subject": self.principal.subject,
                "reason": reason,
            }
            self.session.add(
                TaxonomyMigrationReview(
                    migration_run_id=run.id,
                    legacy_theme_cluster_id=legacy_theme_cluster_id,
                    review_revision=review_revision,
                    disposition=disposition,
                    destination_theme_ids=review_payload["destination_theme_ids"],
                    allocations=full_allocations,
                    reviewer_subject=self.principal.subject,
                    reviewer_auth_method=self.principal.auth_method,
                    reason=reason,
                    semantic_hash=_hash(review_payload),
                )
            )
            self.session.flush()
            complete, reviewed_count = self._coverage(run)
            was_complete = run.coverage_complete_cache
            run.reviewed_identity_count_cache = reviewed_count
            run.coverage_complete_cache = complete
            self._append_event(
                run,
                "reviewed",
                reason=reason,
                payload=review_payload,
            )
            EconomicTaxonomyPublicationRepository(
                self.session
            ).append_source_revision(
                producer_kind="migration",
                logical_source_key=(
                    f"migration_run:{run.id}:legacy:{legacy_theme_cluster_id}"
                ),
                revision_kind="migration_review",
                revision_number=review_revision,
                content_hash=_hash(review_payload),
                authority_epoch=authority.authority_epoch,
            )
            if complete and not was_complete:
                taxonomy_repository = EconomicTaxonomyRepository(self.session)
                self._append_event(
                    run,
                    "completed",
                    reason="All legacy identities and split claims are reviewed.",
                    payload={
                        "coverage_complete": True,
                        "reviewed_identity_count": reviewed_count,
                        "output_taxonomy_semantic_hash": (
                            taxonomy_repository.semantic_hash(
                                run.taxonomy_version_id
                            )
                        ),
                        "output_taxonomy_artifact_integrity_hash": (
                            taxonomy_repository.artifact_integrity_hash(
                                run.taxonomy_version_id
                            )
                        ),
                    },
                )
            self.session.flush()
            return run

    def replay_manifest(self, run_id: UUID) -> ReplayManifest:
        self._require_reviewer()
        with producer_write(
            self.session,
            expected_epoch=self.expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ) as authority:
            run = self.session.execute(
                select(TaxonomyMigrationRun)
                .where(TaxonomyMigrationRun.id == run_id)
                .with_for_update()
            ).scalar_one_or_none()
            if run is None:
                raise MigrationInputError("migration_run_not_found")
            if not run.coverage_complete:
                raise MigrationInputError("migration_coverage_incomplete")
            latest_replay = self.session.scalar(
                select(TaxonomySourceRevisionLog)
                .where(
                    TaxonomySourceRevisionLog.producer_kind == "migration",
                    TaxonomySourceRevisionLog.logical_source_key
                    == f"migration_run:{run.id}",
                    TaxonomySourceRevisionLog.revision_kind == "migration_replay",
                )
                .order_by(TaxonomySourceRevisionLog.revision_number.desc())
                .limit(1)
            )
            replay_inputs = self._revision_entries(exclude_replay_for_run=run.id)
            replay_hash = _hash(replay_inputs)
            if latest_replay is None or latest_replay.content_hash != replay_hash:
                replay_revision = (
                    latest_replay.revision_number + 1
                    if latest_replay is not None
                    else 1
                )
                EconomicTaxonomyPublicationRepository(
                    self.session
                ).append_source_revision(
                    producer_kind="migration",
                    logical_source_key=f"migration_run:{run.id}",
                    revision_kind="migration_replay",
                    revision_number=replay_revision,
                    content_hash=replay_hash,
                    authority_epoch=authority.authority_epoch,
                )
                self._append_event(
                    run,
                    "replayed",
                    reason="Exact committed revision tuples captured.",
                    payload={
                        "replay_revision": replay_revision,
                        "input_revision_count": len(replay_inputs),
                        "input_semantic_hash": replay_hash,
                    },
                )
                self.session.flush()
            entries = self._revision_entries()
            return ReplayManifest(
                migration_run_id=run.id,
                entries=entries,
                semantic_hash=_hash(entries),
            )

    def _append_event(self, run, event_type, *, reason, payload):
        sequence = (
            self.session.scalar(
                select(
                    func.max(TaxonomyMigrationProgressEvent.sequence_number)
                ).where(TaxonomyMigrationProgressEvent.migration_run_id == run.id)
            )
            or 0
        ) + 1
        event = TaxonomyMigrationProgressEvent(
            migration_run_id=run.id,
            sequence_number=sequence,
            event_type=event_type,
            actor_subject=self.principal.subject,
            actor_auth_method=self.principal.auth_method,
            reason=reason,
            event_payload=payload,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def _normalize_dataset(self, dataset):
        if not isinstance(dataset, dict):
            raise MigrationInputError("migration_dataset_object_required")
        taxonomy_version_id = str(UUID(str(dataset.get("taxonomy_version_id"))))
        migration_policy_version = _required_text(
            dataset.get("migration_policy_version"), "migration_policy_version"
        )
        policy_bundle = dataset.get("policy_bundle")
        if not isinstance(policy_bundle, dict) or not policy_bundle:
            raise MigrationInputError("policy_bundle_required")
        identities = []
        seen = set()
        for raw in dataset.get("legacy_identities", []):
            cluster_id = int(raw["legacy_theme_cluster_id"])
            if cluster_id in seen:
                raise MigrationInputError("duplicate_legacy_identity")
            seen.add(cluster_id)
            claims = sorted(
                (
                    {
                        "allocation_kind": _required_text(
                            claim.get("allocation_kind"), "allocation_kind"
                        ),
                        "allocation_key": _required_text(
                            claim.get("allocation_key"), "allocation_key"
                        ),
                    }
                    for claim in raw.get("current_claims", [])
                ),
                key=lambda value: (
                    value["allocation_kind"],
                    value["allocation_key"],
                ),
            )
            if len({(v["allocation_kind"], v["allocation_key"]) for v in claims}) != len(
                claims
            ):
                raise MigrationInputError("duplicate_current_claim")
            identities.append(
                {
                    "legacy_theme_cluster_id": cluster_id,
                    "source_hash": _required_text(
                        raw.get("source_hash"), "source_hash"
                    ),
                    "current_claims": claims,
                }
            )
        identities.sort(key=lambda value: value["legacy_theme_cluster_id"])
        return {
            "taxonomy_version_id": taxonomy_version_id,
            "migration_policy_version": migration_policy_version,
            "policy_bundle": policy_bundle,
            "legacy_identities": identities,
        }

    def _normalize_allocations(self, allocations):
        normalized = []
        seen = set()
        for raw in allocations:
            kind = _required_text(raw.get("allocation_kind"), "allocation_kind")
            key = _required_text(raw.get("allocation_key"), "allocation_key")
            identity = (kind, key)
            if identity in seen:
                raise MigrationInputError("duplicate_migration_allocation")
            seen.add(identity)
            destination = raw.get("destination_theme_id")
            exclusion = raw.get("reviewed_exclusion")
            if (destination is None) == (exclusion is None):
                raise MigrationInputError("allocation_resolution_required")
            normalized.append(
                {
                    "allocation_kind": kind,
                    "allocation_key": key,
                    "destination_theme_id": (
                        str(UUID(str(destination))) if destination is not None else None
                    ),
                    "reviewed_exclusion": (
                        _required_text(exclusion, "reviewed_exclusion")
                        if exclusion is not None
                        else None
                    ),
                }
            )
        return sorted(
            normalized,
            key=lambda value: (
                value["allocation_kind"], value["allocation_key"]
            ),
        )

    def _validate_review_shape(
        self,
        run,
        identity,
        *,
        disposition,
        destination_ids,
        allocations,
    ):
        if disposition in {"mapped", "merged_equivalent"} and len(destination_ids) != 1:
            raise MigrationInputError("single_destination_required")
        if disposition == "split_required" and len(destination_ids) < 2:
            raise MigrationInputError("split_destinations_required")
        if disposition in {"not_a_theme", "deferred"} and destination_ids:
            raise MigrationInputError("destination_not_allowed")
        if disposition != "split_required" and allocations:
            raise MigrationInputError("split_allocations_not_allowed")
        for destination_id in destination_ids:
            if self.session.get(
                EconomicThemeRevision,
                (run.taxonomy_version_id, destination_id),
            ) is None:
                raise MigrationInputError("migration_destination_not_in_taxonomy")
        destination_strings = {str(value) for value in destination_ids}
        current_claims = {
            (row["allocation_kind"], row["allocation_key"])
            for row in identity["current_claims"]
        }
        for allocation in allocations:
            key = (
                allocation["allocation_kind"], allocation["allocation_key"]
            )
            if key not in current_claims:
                raise MigrationInputError("allocation_claim_not_current")
            destination = allocation.get("destination_theme_id")
            if destination is not None and destination not in destination_strings:
                raise MigrationInputError("allocation_destination_not_reviewed")

    def _identity(self, run, legacy_theme_cluster_id):
        return next(
            (
                row
                for row in run.dataset_manifest["legacy_identities"]
                if row["legacy_theme_cluster_id"] == legacy_theme_cluster_id
            ),
            None,
        ) or self._raise("legacy_identity_not_in_migration")

    def _coverage(self, run):
        reviewed = 0
        complete = True
        for identity in run.dataset_manifest["legacy_identities"]:
            cluster_id = identity["legacy_theme_cluster_id"]
            review = self.session.scalar(
                select(TaxonomyMigrationReview)
                .where(
                    TaxonomyMigrationReview.migration_run_id == run.id,
                    TaxonomyMigrationReview.legacy_theme_cluster_id == cluster_id,
                )
                .order_by(TaxonomyMigrationReview.review_revision.desc())
                .limit(1)
            )
            disposition = self.session.get(
                LegacyIdentityDisposition,
                (run.taxonomy_version_id, cluster_id),
            )
            if (
                review is None
                or disposition is None
                or disposition.disposition == "deferred"
            ):
                complete = False
                continue
            reviewed += 1
            destinations = self.session.scalars(
                select(LegacyDestinationMapping).where(
                    LegacyDestinationMapping.taxonomy_version_id
                    == run.taxonomy_version_id,
                    LegacyDestinationMapping.legacy_theme_cluster_id == cluster_id,
                )
            ).all()
            if disposition.disposition in {"mapped", "merged_equivalent"}:
                complete = complete and len(destinations) == 1
            elif disposition.disposition == "not_a_theme":
                complete = complete and not destinations
            elif disposition.disposition == "split_required":
                allocations = self.session.scalars(
                    select(LegacyClaimAllocation).where(
                        LegacyClaimAllocation.taxonomy_version_id
                        == run.taxonomy_version_id,
                        LegacyClaimAllocation.legacy_theme_cluster_id == cluster_id,
                    )
                ).all()
                expected = {
                    (row["allocation_kind"], row["allocation_key"])
                    for row in identity["current_claims"]
                }
                actual = {
                    (row.allocation_kind, row.allocation_key) for row in allocations
                }
                complete = complete and len(destinations) >= 2 and actual == expected
        return complete, reviewed

    def _revision_entries(self, *, exclude_replay_for_run: UUID | None = None):
        rows = self.session.scalars(select(TaxonomySourceRevisionLog)).all()
        return tuple(
            sorted(
                (
                    row.producer_kind,
                    row.logical_source_key,
                    row.revision_kind,
                    row.revision_number,
                    row.content_hash,
                    str(row.id),
                )
                for row in rows
                if not (
                    exclude_replay_for_run is not None
                    and row.producer_kind == "migration"
                    and row.logical_source_key
                    == f"migration_run:{exclude_replay_for_run}"
                    and row.revision_kind == "migration_replay"
                )
            )
        )

    def _require_reviewer(self):
        if not self.principal.can_review_taxonomy:
            raise MigrationReviewForbidden("taxonomy_review_forbidden")

    @staticmethod
    def _raise(message):
        raise MigrationInputError(message)
