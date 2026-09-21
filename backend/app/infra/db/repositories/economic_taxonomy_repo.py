"""Repository for complete, hashable, sealed Economic Theme snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.inspection import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from app.models.economic_taxonomy import (
    EconomicTheme,
    EconomicThemeAlias,
    EconomicThemeFacet,
    EconomicThemeRedirect,
    EconomicThemeRelationship,
    EconomicThemeRevision,
    FacetDimension,
    FacetValue,
    ImmutableSnapshot,
    LegacyClaimAllocation,
    LegacyDestinationMapping,
    LegacyIdentityDisposition,
    TaxonomyPolicy,
    TaxonomyVersion,
)


class SnapshotValidationError(ValueError):
    """Raised when a draft is incomplete or contains cross-snapshot references."""


class GraphInvariantViolation(SnapshotValidationError):
    """Raised when semantic graph assertions contradict one another."""


SEMANTIC_HASH_FIELDS = {
    "theme": (
        "semantic_key",
        "display_name",
        "definition",
        "mechanism",
        "lifecycle",
        "lifecycle_policy_version",
    ),
    "alias": ("theme_semantic_key", "normalized_alias"),
    "dimension": (
        "key",
        "definition",
        "value_type",
        "cardinality",
        "scope",
        "normalization_policy",
        "inclusion_semantics",
        "exclusion_semantics",
    ),
    "facet": ("theme_semantic_key", "dimension_key", "normalized_value"),
    "relationship": (
        "source_semantic_key",
        "target_semantic_key",
        "kind",
        "direction",
        "discriminator",
    ),
    "mapping": (
        "legacy_identity",
        "disposition",
        "destinations",
        "allocations",
        "redirects",
    ),
    "policy": ("policy_kind", "policy_version"),
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (UUID, datetime, date)):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sorted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda record: json.dumps(
            _jsonable(record), sort_keys=True, separators=(",", ":")
        ),
    )


class EconomicTaxonomyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_draft(
        self,
        *,
        actor: str,
        reason: str,
        parent_version_id: UUID | None = None,
    ) -> TaxonomyVersion:
        self._require_text(actor, "actor")
        self._require_text(reason, "reason")
        if parent_version_id is not None:
            self._require_version(parent_version_id)
        version = TaxonomyVersion(
            parent_version_id=parent_version_id,
            status="draft",
            created_by=actor,
            reason=reason,
        )
        self._session.add(version)
        self._session.flush()
        return version

    def create_theme(
        self,
        taxonomy_version_id: UUID,
        *,
        display_name: str,
        definition: str,
        mechanism: str,
        lifecycle: str,
        lifecycle_policy_version: str,
        semantic_key: UUID | None = None,
        actor: str = "system:economic-taxonomy-refresh",
        identity_origin: str = "economic_taxonomy",
        review_comment: str | None = None,
    ) -> EconomicTheme:
        self._assert_draft(taxonomy_version_id)
        for name, value in (
            ("display_name", display_name),
            ("definition", definition),
            ("mechanism", mechanism),
            ("lifecycle", lifecycle),
            ("lifecycle_policy_version", lifecycle_policy_version),
            ("actor", actor),
            ("identity_origin", identity_origin),
        ):
            self._require_text(value, name)
        theme = EconomicTheme(
            semantic_key=semantic_key or uuid4(),
            identity_origin=identity_origin,
            created_by=actor,
        )
        self._session.add(theme)
        self._session.flush()
        self._session.add(
            EconomicThemeRevision(
                taxonomy_version_id=taxonomy_version_id,
                theme_id=theme.id,
                display_name=display_name,
                definition=definition,
                mechanism=mechanism,
                lifecycle=lifecycle,
                lifecycle_policy_version=lifecycle_policy_version,
                created_by=actor,
                review_comment=review_comment,
            )
        )
        self._session.flush()
        return theme

    def add_alias(
        self,
        taxonomy_version_id: UUID,
        theme_id: UUID,
        alias: str,
        *,
        actor: str = "system:economic-taxonomy-refresh",
        review_comment: str | None = None,
    ) -> EconomicThemeAlias:
        self._assert_draft(taxonomy_version_id)
        self._require_theme_revision(taxonomy_version_id, theme_id)
        self._require_text(alias, "alias")
        row = EconomicThemeAlias(
            taxonomy_version_id=taxonomy_version_id,
            theme_id=theme_id,
            alias=alias.strip(),
            normalized_alias=self._normalize(alias),
            created_by=actor,
            review_comment=review_comment,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def add_dimension(
        self,
        taxonomy_version_id: UUID,
        *,
        key: str,
        definition: str,
        inclusion_semantics: str,
        exclusion_semantics: str,
        value_type: str,
        cardinality: str,
        scope: str,
        normalization_policy: str,
        actor: str = "system:economic-taxonomy-refresh",
        review_comment: str | None = None,
    ) -> FacetDimension:
        self._assert_draft(taxonomy_version_id)
        values = {
            "key": key,
            "definition": definition,
            "inclusion_semantics": inclusion_semantics,
            "exclusion_semantics": exclusion_semantics,
            "value_type": value_type,
            "cardinality": cardinality,
            "scope": scope,
            "normalization_policy": normalization_policy,
        }
        for name, value in values.items():
            self._require_text(value, name)
        row = FacetDimension(
            taxonomy_version_id=taxonomy_version_id,
            created_by=actor,
            review_comment=review_comment,
            **values,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_dimension(
        self, taxonomy_version_id: UUID, key: str, **changes: str
    ) -> FacetDimension:
        self._assert_draft(taxonomy_version_id)
        allowed = {
            "definition",
            "inclusion_semantics",
            "exclusion_semantics",
            "value_type",
            "cardinality",
            "scope",
            "normalization_policy",
            "review_comment",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported dimension fields: {sorted(unknown)}")
        row = self._session.get(FacetDimension, (taxonomy_version_id, key))
        if row is None:
            raise SnapshotValidationError("dimension_not_found")
        for name, value in changes.items():
            if name != "review_comment":
                self._require_text(value, name)
            setattr(row, name, value)
        self._session.flush()
        return row

    def add_facet_value(
        self,
        taxonomy_version_id: UUID,
        dimension_key: str,
        normalized_value: str,
        display_value: str,
        *,
        actor: str = "system:economic-taxonomy-refresh",
    ) -> FacetValue:
        self._assert_draft(taxonomy_version_id)
        if self._session.get(
            FacetDimension, (taxonomy_version_id, dimension_key)
        ) is None:
            raise SnapshotValidationError("same_snapshot_reference: dimension")
        for name, value in (
            ("normalized_value", normalized_value),
            ("display_value", display_value),
        ):
            self._require_text(value, name)
        row = FacetValue(
            taxonomy_version_id=taxonomy_version_id,
            dimension_key=dimension_key,
            normalized_value=self._normalize(normalized_value),
            display_value=display_value.strip(),
            created_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def assign_facet(
        self,
        taxonomy_version_id: UUID,
        theme_id: UUID,
        dimension_key: str,
        normalized_value: str,
        *,
        actor: str = "system:economic-taxonomy-refresh",
    ) -> EconomicThemeFacet:
        self._assert_draft(taxonomy_version_id)
        self._require_theme_revision(taxonomy_version_id, theme_id)
        normalized = self._normalize(normalized_value)
        if self._session.get(
            FacetValue, (taxonomy_version_id, dimension_key, normalized)
        ) is None:
            raise SnapshotValidationError("same_snapshot_reference: facet_value")
        row = EconomicThemeFacet(
            taxonomy_version_id=taxonomy_version_id,
            theme_id=theme_id,
            dimension_key=dimension_key,
            normalized_value=normalized,
            created_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def add_specialization(
        self,
        taxonomy_version_id: UUID,
        *,
        narrower: UUID,
        broader: UUID,
        actor: str = "system:economic-taxonomy-refresh",
    ) -> EconomicThemeRelationship:
        return self.add_relationship(
            taxonomy_version_id,
            source_theme_id=narrower,
            target_theme_id=broader,
            kind="specialization",
            direction="narrower_to_broader",
            discriminator="",
            actor=actor,
        )

    def add_relationship(
        self,
        taxonomy_version_id: UUID,
        *,
        source_theme_id: UUID,
        target_theme_id: UUID,
        kind: str,
        direction: str,
        discriminator: str,
        actor: str = "system:economic-taxonomy-refresh",
        review_comment: str | None = None,
    ) -> EconomicThemeRelationship:
        self._assert_draft(taxonomy_version_id)
        self._require_theme_revision(taxonomy_version_id, source_theme_id)
        self._require_theme_revision(taxonomy_version_id, target_theme_id)
        row = EconomicThemeRelationship(
            taxonomy_version_id=taxonomy_version_id,
            source_theme_id=source_theme_id,
            target_theme_id=target_theme_id,
            kind=kind,
            direction=direction,
            discriminator=discriminator,
            created_by=actor,
            review_comment=review_comment,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def add_policy(
        self,
        taxonomy_version_id: UUID,
        policy_kind: str,
        policy_version: str,
        *,
        actor: str = "system:economic-taxonomy-refresh",
    ) -> TaxonomyPolicy:
        self._assert_draft(taxonomy_version_id)
        self._require_text(policy_kind, "policy_kind")
        self._require_text(policy_version, "policy_version")
        row = TaxonomyPolicy(
            taxonomy_version_id=taxonomy_version_id,
            policy_kind=policy_kind,
            policy_version=policy_version,
            created_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_legacy_disposition(
        self,
        taxonomy_version_id: UUID,
        legacy_theme_cluster_id: int,
        *,
        disposition: str,
        actor: str,
        review_comment: str | None = None,
    ) -> LegacyIdentityDisposition:
        self._assert_draft(taxonomy_version_id)
        self._require_text(disposition, "disposition")
        self._require_text(actor, "actor")
        row = self._session.get(
            LegacyIdentityDisposition,
            (taxonomy_version_id, legacy_theme_cluster_id),
        )
        if row is None:
            row = LegacyIdentityDisposition(
                taxonomy_version_id=taxonomy_version_id,
                legacy_theme_cluster_id=legacy_theme_cluster_id,
                disposition=disposition,
                created_by=actor,
                review_comment=review_comment,
            )
            self._session.add(row)
        else:
            row.disposition = disposition
            row.created_by = actor
            row.review_comment = review_comment
        self._session.flush()
        return row

    def add_legacy_destination(
        self,
        taxonomy_version_id: UUID,
        legacy_theme_cluster_id: int,
        destination_theme_id: UUID,
        *,
        actor: str,
        review_comment: str | None = None,
    ) -> LegacyDestinationMapping:
        self._assert_draft(taxonomy_version_id)
        if self._session.get(
            LegacyIdentityDisposition,
            (taxonomy_version_id, legacy_theme_cluster_id),
        ) is None:
            raise SnapshotValidationError("legacy_disposition_missing")
        self._require_theme_revision(taxonomy_version_id, destination_theme_id)
        row = LegacyDestinationMapping(
            taxonomy_version_id=taxonomy_version_id,
            legacy_theme_cluster_id=legacy_theme_cluster_id,
            destination_theme_id=destination_theme_id,
            created_by=actor,
            review_comment=review_comment,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def allocate_legacy_claim(
        self,
        taxonomy_version_id: UUID,
        legacy_theme_cluster_id: int,
        *,
        allocation_kind: str,
        allocation_key: str,
        actor: str,
        destination_theme_id: UUID | None = None,
        reviewed_exclusion: str | None = None,
        review_comment: str | None = None,
    ) -> LegacyClaimAllocation:
        self._assert_draft(taxonomy_version_id)
        self._require_text(allocation_kind, "allocation_kind")
        self._require_text(allocation_key, "allocation_key")
        self._require_text(actor, "actor")
        if (destination_theme_id is None) == (reviewed_exclusion is None):
            raise ValueError("allocation_requires_one_resolution")
        if destination_theme_id is not None:
            destination = self._session.get(
                LegacyDestinationMapping,
                (
                    taxonomy_version_id,
                    legacy_theme_cluster_id,
                    destination_theme_id,
                ),
            )
            if destination is None:
                raise SnapshotValidationError("legacy_destination_missing")
        else:
            self._require_text(reviewed_exclusion or "", "reviewed_exclusion")
        row = LegacyClaimAllocation(
            taxonomy_version_id=taxonomy_version_id,
            legacy_theme_cluster_id=legacy_theme_cluster_id,
            allocation_kind=allocation_kind,
            allocation_key=allocation_key,
            destination_theme_id=destination_theme_id,
            reviewed_exclusion=reviewed_exclusion,
            created_by=actor,
            review_comment=review_comment,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def add_theme_redirect(
        self,
        taxonomy_version_id: UUID,
        *,
        source_theme_id: UUID,
        target_theme_id: UUID,
        actor: str,
        reason: str,
        review_comment: str | None = None,
    ) -> EconomicThemeRedirect:
        self._assert_draft(taxonomy_version_id)
        self._require_theme_revision(taxonomy_version_id, source_theme_id)
        self._require_theme_revision(taxonomy_version_id, target_theme_id)
        self._require_text(actor, "actor")
        self._require_text(reason, "reason")
        row = EconomicThemeRedirect(
            taxonomy_version_id=taxonomy_version_id,
            source_theme_id=source_theme_id,
            target_theme_id=target_theme_id,
            created_by=actor,
            reason=reason,
            review_comment=review_comment,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def clone_draft(
        self, source_version_id: UUID, *, actor: str, reason: str
    ) -> TaxonomyVersion:
        source = self._require_version(source_version_id)
        if source.status != "sealed":
            raise SnapshotValidationError("clone_source_must_be_sealed")
        clone = self.create_draft(
            actor=actor, reason=reason, parent_version_id=source_version_id
        )

        for row in self._rows(EconomicThemeRevision, source_version_id):
            self._session.add(
                EconomicThemeRevision(
                    taxonomy_version_id=clone.id,
                    theme_id=row.theme_id,
                    display_name=row.display_name,
                    definition=row.definition,
                    mechanism=row.mechanism,
                    lifecycle=row.lifecycle,
                    lifecycle_policy_version=row.lifecycle_policy_version,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        self._session.flush()

        for row in self._rows(EconomicThemeAlias, source_version_id):
            self._session.add(
                EconomicThemeAlias(
                    taxonomy_version_id=clone.id,
                    theme_id=row.theme_id,
                    alias=row.alias,
                    normalized_alias=row.normalized_alias,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        for row in self._rows(FacetDimension, source_version_id):
            self._session.add(
                FacetDimension(
                    taxonomy_version_id=clone.id,
                    key=row.key,
                    definition=row.definition,
                    inclusion_semantics=row.inclusion_semantics,
                    exclusion_semantics=row.exclusion_semantics,
                    value_type=row.value_type,
                    cardinality=row.cardinality,
                    scope=row.scope,
                    normalization_policy=row.normalization_policy,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        self._session.flush()

        for row in self._rows(FacetValue, source_version_id):
            self._session.add(
                FacetValue(
                    taxonomy_version_id=clone.id,
                    dimension_key=row.dimension_key,
                    normalized_value=row.normalized_value,
                    display_value=row.display_value,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        self._session.flush()

        for row in self._rows(EconomicThemeFacet, source_version_id):
            self._session.add(
                EconomicThemeFacet(
                    taxonomy_version_id=clone.id,
                    theme_id=row.theme_id,
                    dimension_key=row.dimension_key,
                    normalized_value=row.normalized_value,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        for row in self._rows(EconomicThemeRelationship, source_version_id):
            self._session.add(
                EconomicThemeRelationship(
                    taxonomy_version_id=clone.id,
                    source_theme_id=row.source_theme_id,
                    target_theme_id=row.target_theme_id,
                    kind=row.kind,
                    direction=row.direction,
                    discriminator=row.discriminator,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        for row in self._rows(TaxonomyPolicy, source_version_id):
            self._session.add(
                TaxonomyPolicy(
                    taxonomy_version_id=clone.id,
                    policy_kind=row.policy_kind,
                    policy_version=row.policy_version,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        for row in self._rows(LegacyIdentityDisposition, source_version_id):
            self._session.add(
                LegacyIdentityDisposition(
                    taxonomy_version_id=clone.id,
                    legacy_theme_cluster_id=row.legacy_theme_cluster_id,
                    disposition=row.disposition,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        self._session.flush()
        for row in self._rows(LegacyDestinationMapping, source_version_id):
            self._session.add(
                LegacyDestinationMapping(
                    taxonomy_version_id=clone.id,
                    legacy_theme_cluster_id=row.legacy_theme_cluster_id,
                    destination_theme_id=row.destination_theme_id,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        self._session.flush()
        for row in self._rows(LegacyClaimAllocation, source_version_id):
            self._session.add(
                LegacyClaimAllocation(
                    taxonomy_version_id=clone.id,
                    legacy_theme_cluster_id=row.legacy_theme_cluster_id,
                    allocation_kind=row.allocation_kind,
                    allocation_key=row.allocation_key,
                    destination_theme_id=row.destination_theme_id,
                    reviewed_exclusion=row.reviewed_exclusion,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        for row in self._rows(EconomicThemeRedirect, source_version_id):
            self._session.add(
                EconomicThemeRedirect(
                    taxonomy_version_id=clone.id,
                    source_theme_id=row.source_theme_id,
                    target_theme_id=row.target_theme_id,
                    reason=row.reason,
                    created_by=actor,
                    review_comment=row.review_comment,
                )
            )
        self._session.flush()
        return clone

    def set_status(self, taxonomy_version_id: UUID, status: str) -> TaxonomyVersion:
        version = self._require_version(taxonomy_version_id)
        if version.status == "sealed":
            raise ImmutableSnapshot("sealed_snapshot_immutable")
        if status == "sealed":
            return self.seal_draft(taxonomy_version_id)
        if status != "draft":
            raise ValueError("taxonomy version status must be draft or sealed")
        return version

    def seal_draft(self, taxonomy_version_id: UUID) -> TaxonomyVersion:
        self._session.flush()
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            lock_key = taxonomy_version_id.int & 0x7FFFFFFFFFFFFFFF
            self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))
        version = self._session.scalar(
            select(TaxonomyVersion)
            .where(TaxonomyVersion.id == taxonomy_version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if version is None:
            raise SnapshotValidationError("taxonomy_version_not_found")
        if version.status != "draft":
            raise ImmutableSnapshot("sealed_snapshot_immutable")
        self._validate_snapshot(taxonomy_version_id)
        version.semantic_hash = self.semantic_hash(taxonomy_version_id)
        version.artifact_integrity_hash = self.artifact_integrity_hash(
            taxonomy_version_id
        )
        version.status = "sealed"
        version.sealed_at = datetime.now(timezone.utc)
        self._session.flush()
        return version

    def load_snapshot(self, taxonomy_version_id: UUID) -> dict[str, Any]:
        self._session.flush()
        version = self._require_version(taxonomy_version_id)
        theme_keys = self._theme_keys(taxonomy_version_id)

        themes = []
        for row in self._rows(EconomicThemeRevision, taxonomy_version_id):
            themes.append(
                {
                    **self._row_dict(row),
                    "semantic_key": str(theme_keys[row.theme_id]),
                }
            )
        return {
            "version": self._row_dict(version),
            "themes": themes,
            "aliases": [
                self._row_dict(row)
                for row in self._rows(EconomicThemeAlias, taxonomy_version_id)
            ],
            "dimensions": [
                self._row_dict(row)
                for row in self._rows(FacetDimension, taxonomy_version_id)
            ],
            "facet_values": [
                self._row_dict(row)
                for row in self._rows(FacetValue, taxonomy_version_id)
            ],
            "theme_facets": [
                self._row_dict(row)
                for row in self._rows(EconomicThemeFacet, taxonomy_version_id)
            ],
            "relationships": [
                self._row_dict(row)
                for row in self._rows(EconomicThemeRelationship, taxonomy_version_id)
            ],
            "policies": [
                self._row_dict(row)
                for row in self._rows(TaxonomyPolicy, taxonomy_version_id)
            ],
            "legacy_dispositions": [
                self._row_dict(row)
                for row in self._rows(LegacyIdentityDisposition, taxonomy_version_id)
            ],
            "legacy_destinations": [
                self._row_dict(row)
                for row in self._rows(LegacyDestinationMapping, taxonomy_version_id)
            ],
            "legacy_claim_allocations": [
                self._row_dict(row)
                for row in self._rows(LegacyClaimAllocation, taxonomy_version_id)
            ],
            "theme_redirects": [
                self._row_dict(row)
                for row in self._rows(EconomicThemeRedirect, taxonomy_version_id)
            ],
        }

    def semantic_hash(self, taxonomy_version_id: UUID | TaxonomyVersion) -> str:
        version_id = (
            taxonomy_version_id.id
            if isinstance(taxonomy_version_id, TaxonomyVersion)
            else taxonomy_version_id
        )
        self._session.flush()
        return _canonical_hash(self._semantic_payload(version_id))

    def facet_catalog_semantic_hash(self, taxonomy_version_id: UUID) -> str:
        self._session.flush()
        dimensions = [
            {
                field: getattr(row, field)
                for field in SEMANTIC_HASH_FIELDS["dimension"]
            }
            for row in self._rows(FacetDimension, taxonomy_version_id)
        ]
        return _canonical_hash(_sorted_records(dimensions))

    def artifact_integrity_hash(self, taxonomy_version_id: UUID) -> str:
        snapshot = self.load_snapshot(taxonomy_version_id)
        version = dict(snapshot["version"])
        for operational in (
            "status",
            "semantic_hash",
            "artifact_integrity_hash",
            "sealed_at",
        ):
            version.pop(operational, None)
        payload = {
            "version": version,
            **{
                name: _sorted_records(records)
                for name, records in snapshot.items()
                if name != "version"
            },
        }
        return _canonical_hash(payload)

    def _semantic_payload(self, taxonomy_version_id: UUID) -> dict[str, Any]:
        theme_keys = self._theme_keys(taxonomy_version_id)
        themes = [
            {
                "semantic_key": str(theme_keys[row.theme_id]),
                "display_name": row.display_name,
                "definition": row.definition,
                "mechanism": row.mechanism,
                "lifecycle": row.lifecycle,
                "lifecycle_policy_version": row.lifecycle_policy_version,
            }
            for row in self._rows(EconomicThemeRevision, taxonomy_version_id)
        ]
        aliases = [
            {
                "theme_semantic_key": str(theme_keys[row.theme_id]),
                "normalized_alias": row.normalized_alias,
            }
            for row in self._rows(EconomicThemeAlias, taxonomy_version_id)
        ]
        dimensions = [
            {
                field: getattr(row, field)
                for field in SEMANTIC_HASH_FIELDS["dimension"]
            }
            for row in self._rows(FacetDimension, taxonomy_version_id)
        ]
        facets = [
            {
                "theme_semantic_key": str(theme_keys[row.theme_id]),
                "dimension_key": row.dimension_key,
                "normalized_value": row.normalized_value,
            }
            for row in self._rows(EconomicThemeFacet, taxonomy_version_id)
        ]
        relationships = [
            {
                "source_semantic_key": str(theme_keys[row.source_theme_id]),
                "target_semantic_key": str(theme_keys[row.target_theme_id]),
                "kind": row.kind,
                "direction": row.direction,
                "discriminator": row.discriminator,
            }
            for row in self._rows(EconomicThemeRelationship, taxonomy_version_id)
        ]
        policies = [
            {
                "policy_kind": row.policy_kind,
                "policy_version": row.policy_version,
            }
            for row in self._rows(TaxonomyPolicy, taxonomy_version_id)
        ]
        mappings = [
            {
                "mapping_kind": "legacy_disposition",
                "legacy_identity": row.legacy_theme_cluster_id,
                "disposition": row.disposition,
            }
            for row in self._rows(LegacyIdentityDisposition, taxonomy_version_id)
        ]
        mappings.extend(
            {
                "mapping_kind": "legacy_destination",
                "legacy_identity": row.legacy_theme_cluster_id,
                "destination_semantic_key": str(
                    theme_keys[row.destination_theme_id]
                ),
            }
            for row in self._rows(LegacyDestinationMapping, taxonomy_version_id)
        )
        mappings.extend(
            {
                "mapping_kind": "legacy_allocation",
                "legacy_identity": row.legacy_theme_cluster_id,
                "allocation_kind": row.allocation_kind,
                "allocation_key": row.allocation_key,
                "destination_semantic_key": (
                    str(theme_keys[row.destination_theme_id])
                    if row.destination_theme_id is not None
                    else None
                ),
                "reviewed_exclusion": row.reviewed_exclusion,
            }
            for row in self._rows(LegacyClaimAllocation, taxonomy_version_id)
        )
        mappings.extend(
            {
                "mapping_kind": "theme_redirect",
                "source_semantic_key": str(theme_keys[row.source_theme_id]),
                "target_semantic_key": str(theme_keys[row.target_theme_id]),
            }
            for row in self._rows(EconomicThemeRedirect, taxonomy_version_id)
        )
        return {
            "themes": _sorted_records(themes),
            "aliases": _sorted_records(aliases),
            "dimensions": _sorted_records(dimensions),
            "facets": _sorted_records(facets),
            "relationships": _sorted_records(relationships),
            "mappings": _sorted_records(mappings),
            "policies": _sorted_records(policies),
        }

    def _validate_snapshot(self, taxonomy_version_id: UUID) -> None:
        theme_ids = set(self._theme_keys(taxonomy_version_id))
        relationships = self._rows(
            EconomicThemeRelationship, taxonomy_version_id
        )
        dispositions = self._rows(LegacyIdentityDisposition, taxonomy_version_id)
        destinations = self._rows(LegacyDestinationMapping, taxonomy_version_id)
        allocations = self._rows(LegacyClaimAllocation, taxonomy_version_id)
        redirects = self._rows(EconomicThemeRedirect, taxonomy_version_id)
        for relationship in relationships:
            if (
                relationship.source_theme_id not in theme_ids
                or relationship.target_theme_id not in theme_ids
            ):
                raise SnapshotValidationError("same_snapshot_reference")
        for destination in destinations:
            if destination.destination_theme_id not in theme_ids:
                raise SnapshotValidationError("same_snapshot_reference")
        for allocation in allocations:
            if (
                allocation.destination_theme_id is not None
                and allocation.destination_theme_id not in theme_ids
            ):
                raise SnapshotValidationError("same_snapshot_reference")
        for redirect in redirects:
            if (
                redirect.source_theme_id not in theme_ids
                or redirect.target_theme_id not in theme_ids
            ):
                raise SnapshotValidationError("same_snapshot_reference")

        destinations_by_legacy: dict[int, set[UUID]] = {}
        allocations_by_legacy: dict[int, list[LegacyClaimAllocation]] = {}
        for destination in destinations:
            destinations_by_legacy.setdefault(
                destination.legacy_theme_cluster_id, set()
            ).add(destination.destination_theme_id)
        for allocation in allocations:
            allocations_by_legacy.setdefault(
                allocation.legacy_theme_cluster_id, []
            ).append(allocation)
        for disposition in dispositions:
            destination_count = len(
                destinations_by_legacy.get(disposition.legacy_theme_cluster_id, set())
            )
            allocation_count = len(
                allocations_by_legacy.get(disposition.legacy_theme_cluster_id, [])
            )
            if disposition.disposition in {"not_a_theme", "deferred"}:
                if destination_count:
                    raise SnapshotValidationError("excluded_disposition_has_destination")
            elif disposition.disposition in {"mapped", "merged_equivalent"}:
                if destination_count != 1:
                    raise SnapshotValidationError("mapping_requires_one_destination")
            elif (
                disposition.disposition == "split_required"
                and (destination_count < 2 or allocation_count == 0)
            ):
                raise SnapshotValidationError("split_requires_allocations")

        edges: dict[UUID, set[UUID]] = {}
        pair_kinds: dict[frozenset[UUID], set[str]] = {}
        for relationship in relationships:
            pair = frozenset(
                (relationship.source_theme_id, relationship.target_theme_id)
            )
            pair_kinds.setdefault(pair, set()).add(relationship.kind)
            if relationship.kind == "specialization":
                edges.setdefault(relationship.source_theme_id, set()).add(
                    relationship.target_theme_id
                )
        for redirect in redirects:
            pair = frozenset((redirect.source_theme_id, redirect.target_theme_id))
            pair_kinds.setdefault(pair, set()).add("redirect")
            edges.setdefault(redirect.source_theme_id, set()).add(
                redirect.target_theme_id
            )

        for kinds in pair_kinds.values():
            if "distinct" in kinds and kinds & {
                "equivalent",
                "specialization",
                "redirect",
            }:
                raise GraphInvariantViolation(
                    "contradictory_relationship_assertion"
                )

        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def visit(theme_id: UUID) -> None:
            if theme_id in visiting:
                raise GraphInvariantViolation("specialization_cycle")
            if theme_id in visited:
                return
            visiting.add(theme_id)
            for target_id in edges.get(theme_id, set()):
                visit(target_id)
            visiting.remove(theme_id)
            visited.add(theme_id)

        for theme_id in theme_ids:
            visit(theme_id)

    def _theme_keys(self, taxonomy_version_id: UUID) -> dict[UUID, UUID]:
        rows = self._session.execute(
            select(EconomicThemeRevision.theme_id, EconomicTheme.semantic_key)
            .join(EconomicTheme, EconomicTheme.id == EconomicThemeRevision.theme_id)
            .where(
                EconomicThemeRevision.taxonomy_version_id == taxonomy_version_id
            )
        ).all()
        return {theme_id: semantic_key for theme_id, semantic_key in rows}

    def _require_theme_revision(
        self, taxonomy_version_id: UUID, theme_id: UUID
    ) -> EconomicThemeRevision:
        row = self._session.get(
            EconomicThemeRevision, (taxonomy_version_id, theme_id)
        )
        if row is None:
            raise SnapshotValidationError("same_snapshot_reference: theme")
        return row

    def _assert_draft(self, taxonomy_version_id: UUID) -> TaxonomyVersion:
        version = self._require_version(taxonomy_version_id)
        if version.status != "draft":
            raise ImmutableSnapshot("sealed_snapshot_immutable")
        return version

    def _require_version(self, taxonomy_version_id: UUID) -> TaxonomyVersion:
        version = self._session.get(TaxonomyVersion, taxonomy_version_id)
        if version is None:
            raise SnapshotValidationError("taxonomy_version_not_found")
        return version

    def _rows(self, model, taxonomy_version_id: UUID):
        return list(
            self._session.scalars(
                select(model).where(
                    model.taxonomy_version_id == taxonomy_version_id
                )
            )
        )

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        mapper = sqlalchemy_inspect(row).mapper
        return {
            column.key: _jsonable(getattr(row, column.key))
            for column in mapper.column_attrs
        }

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().strip().split())

    @staticmethod
    def _require_text(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be non-empty")


__all__ = [
    "SEMANTIC_HASH_FIELDS",
    "EconomicTaxonomyRepository",
    "GraphInvariantViolation",
    "ImmutableSnapshot",
    "SnapshotValidationError",
]
