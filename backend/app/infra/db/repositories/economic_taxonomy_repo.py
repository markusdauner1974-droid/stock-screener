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
    EconomicThemeRelationship,
    EconomicThemeRevision,
    FacetDimension,
    FacetValue,
    ImmutableSnapshot,
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
        return {
            "themes": _sorted_records(themes),
            "aliases": _sorted_records(aliases),
            "dimensions": _sorted_records(dimensions),
            "facets": _sorted_records(facets),
            "relationships": _sorted_records(relationships),
            "mappings": [],
            "policies": _sorted_records(policies),
        }

    def _validate_snapshot(self, taxonomy_version_id: UUID) -> None:
        theme_ids = set(self._theme_keys(taxonomy_version_id))
        relationships = self._rows(
            EconomicThemeRelationship, taxonomy_version_id
        )
        for relationship in relationships:
            if (
                relationship.source_theme_id not in theme_ids
                or relationship.target_theme_id not in theme_ids
            ):
                raise SnapshotValidationError("same_snapshot_reference")

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

        for kinds in pair_kinds.values():
            if "distinct" in kinds and kinds & {"equivalent", "specialization"}:
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
    "EconomicTaxonomyRepository",
    "GraphInvariantViolation",
    "ImmutableSnapshot",
    "SEMANTIC_HASH_FIELDS",
    "SnapshotValidationError",
]
