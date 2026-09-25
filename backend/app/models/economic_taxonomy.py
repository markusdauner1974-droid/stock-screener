"""Stable Economic Theme identities and version-owned semantic snapshots."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    inspect,
)
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.database import Base


class ImmutableSnapshot(ValueError):
    """Raised when sealed or version-owned semantic state would be mutated."""


class TaxonomyVersion(Base):
    __tablename__ = "economic_taxonomy_versions"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    parent_version_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_versions.id", ondelete="RESTRICT"),
    )
    status = Column(String(16), nullable=False, default="draft")
    semantic_hash = Column(String(64))
    artifact_integrity_hash = Column(String(64))
    created_by = Column(String(200), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sealed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','sealed')", name="ck_economic_taxonomy_version_status"
        ),
    )


class EconomicTheme(Base):
    __tablename__ = "economic_themes"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    semantic_key = Column(Uuid(as_uuid=True), nullable=False, unique=True, default=uuid4)
    identity_origin = Column(String(80), nullable=False, default="economic_taxonomy")
    created_by = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EconomicThemeRevision(Base):
    __tablename__ = "economic_theme_revisions"

    taxonomy_version_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    theme_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_themes.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    display_name = Column(String(240), nullable=False)
    definition = Column(Text, nullable=False)
    mechanism = Column(Text, nullable=False)
    lifecycle = Column(String(24), nullable=False)
    lifecycle_policy_version = Column(String(80), nullable=False)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('provisional','established','dormant','reactivated','retired')",
            name="ck_economic_theme_revision_lifecycle",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_theme_revision_logical_row",
        ),
    )


class EconomicThemeAlias(Base):
    __tablename__ = "economic_theme_aliases"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    taxonomy_version_id = Column(Uuid(as_uuid=True), nullable=False)
    theme_id = Column(Uuid(as_uuid=True), nullable=False)
    alias = Column(String(240), nullable=False)
    normalized_alias = Column(String(240), nullable=False)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ("taxonomy_version_id", "theme_id"),
            (
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_alias_same_snapshot_theme",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "theme_id",
            "normalized_alias",
            name="uq_economic_alias_per_theme_snapshot",
        ),
    )


class FacetDimension(Base):
    __tablename__ = "economic_facet_dimensions"

    taxonomy_version_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key = Column(String(80), primary_key=True)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    definition = Column(Text, nullable=False)
    inclusion_semantics = Column(Text, nullable=False)
    exclusion_semantics = Column(Text, nullable=False)
    value_type = Column(String(40), nullable=False)
    cardinality = Column(String(24), nullable=False)
    scope = Column(String(40), nullable=False)
    normalization_policy = Column(String(80), nullable=False)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "cardinality IN ('one','many')",
            name="ck_economic_facet_dimension_cardinality",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_facet_dimension_logical_row",
        ),
    )


class FacetValue(Base):
    __tablename__ = "economic_facet_values"

    taxonomy_version_id = Column(Uuid(as_uuid=True), primary_key=True)
    dimension_key = Column(String(80), primary_key=True)
    normalized_value = Column(String(240), primary_key=True)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    display_value = Column(String(240), nullable=False)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ("taxonomy_version_id", "dimension_key"),
            (
                "economic_facet_dimensions.taxonomy_version_id",
                "economic_facet_dimensions.key",
            ),
            ondelete="CASCADE",
            name="fk_economic_facet_value_same_snapshot_dimension",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_facet_value_logical_row",
        ),
    )


class EconomicThemeFacet(Base):
    __tablename__ = "economic_theme_facets"

    taxonomy_version_id = Column(Uuid(as_uuid=True), primary_key=True)
    theme_id = Column(Uuid(as_uuid=True), primary_key=True)
    dimension_key = Column(String(80), primary_key=True)
    normalized_value = Column(String(240), primary_key=True)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ("taxonomy_version_id", "theme_id"),
            (
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_theme_facet_same_snapshot_theme",
        ),
        ForeignKeyConstraint(
            ("taxonomy_version_id", "dimension_key", "normalized_value"),
            (
                "economic_facet_values.taxonomy_version_id",
                "economic_facet_values.dimension_key",
                "economic_facet_values.normalized_value",
            ),
            ondelete="CASCADE",
            name="fk_economic_theme_facet_same_snapshot_value",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_theme_facet_logical_row",
        ),
    )


class EconomicThemeRelationship(Base):
    __tablename__ = "economic_theme_relationships"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    taxonomy_version_id = Column(Uuid(as_uuid=True), nullable=False)
    source_theme_id = Column(Uuid(as_uuid=True), nullable=False)
    target_theme_id = Column(Uuid(as_uuid=True), nullable=False)
    kind = Column(String(32), nullable=False)
    direction = Column(String(24), nullable=False)
    discriminator = Column(String(240), nullable=False, default="")
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ("taxonomy_version_id", "source_theme_id"),
            (
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_relationship_same_snapshot_source",
        ),
        ForeignKeyConstraint(
            ("taxonomy_version_id", "target_theme_id"),
            (
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_relationship_same_snapshot_target",
        ),
        CheckConstraint(
            "kind IN ('specialization','equivalent','distinct')",
            name="ck_economic_relationship_kind",
        ),
        CheckConstraint(
            "source_theme_id <> target_theme_id",
            name="ck_economic_relationship_distinct_endpoints",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "source_theme_id",
            "target_theme_id",
            "kind",
            "direction",
            "discriminator",
            name="uq_economic_relationship_canonical",
        ),
    )


class TaxonomyPolicy(Base):
    __tablename__ = "economic_taxonomy_policies"

    taxonomy_version_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    policy_kind = Column(String(80), primary_key=True)
    policy_version = Column(String(120), nullable=False)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_taxonomy_policy_logical_row",
        ),
    )


class LegacyIdentityDisposition(Base):
    __tablename__ = "economic_legacy_identity_dispositions"

    taxonomy_version_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("economic_taxonomy_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    legacy_theme_cluster_id = Column(Integer, primary_key=True)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    disposition = Column(String(40), nullable=False)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "disposition IN ('mapped','split_required','merged_equivalent',"
            "'not_a_theme','deferred')",
            name="ck_economic_legacy_identity_disposition",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_legacy_disposition_logical_row",
        ),
    )


class LegacyDestinationMapping(Base):
    __tablename__ = "economic_legacy_destination_mappings"

    taxonomy_version_id = Column(Uuid(as_uuid=True), primary_key=True)
    legacy_theme_cluster_id = Column(Integer, primary_key=True)
    destination_theme_id = Column(Uuid(as_uuid=True), primary_key=True)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ("taxonomy_version_id", "legacy_theme_cluster_id"),
            (
                "economic_legacy_identity_dispositions.taxonomy_version_id",
                "economic_legacy_identity_dispositions.legacy_theme_cluster_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_legacy_destination_disposition",
        ),
        ForeignKeyConstraint(
            ("taxonomy_version_id", "destination_theme_id"),
            (
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_legacy_destination_same_snapshot_theme",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_legacy_destination_logical_row",
        ),
    )


class LegacyClaimAllocation(Base):
    __tablename__ = "economic_legacy_claim_allocations"

    taxonomy_version_id = Column(Uuid(as_uuid=True), primary_key=True)
    legacy_theme_cluster_id = Column(Integer, primary_key=True)
    allocation_kind = Column(String(40), primary_key=True)
    allocation_key = Column(String(500), primary_key=True)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    destination_theme_id = Column(Uuid(as_uuid=True))
    reviewed_exclusion = Column(String(80))
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ("taxonomy_version_id", "legacy_theme_cluster_id"),
            (
                "economic_legacy_identity_dispositions.taxonomy_version_id",
                "economic_legacy_identity_dispositions.legacy_theme_cluster_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_legacy_allocation_disposition",
        ),
        ForeignKeyConstraint(
            (
                "taxonomy_version_id",
                "legacy_theme_cluster_id",
                "destination_theme_id",
            ),
            (
                "economic_legacy_destination_mappings.taxonomy_version_id",
                "economic_legacy_destination_mappings.legacy_theme_cluster_id",
                "economic_legacy_destination_mappings.destination_theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_legacy_allocation_destination",
        ),
        CheckConstraint(
            "(destination_theme_id IS NOT NULL AND reviewed_exclusion IS NULL) OR "
            "(destination_theme_id IS NULL AND reviewed_exclusion IS NOT NULL)",
            name="ck_economic_legacy_allocation_resolution",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_legacy_allocation_logical_row",
        ),
    )


class EconomicThemeRedirect(Base):
    __tablename__ = "economic_theme_redirects"

    taxonomy_version_id = Column(Uuid(as_uuid=True), primary_key=True)
    source_theme_id = Column(Uuid(as_uuid=True), primary_key=True)
    target_theme_id = Column(Uuid(as_uuid=True), nullable=False)
    logical_row_id = Column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    reason = Column(Text, nullable=False)
    created_by = Column(String(200), nullable=False)
    review_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ("taxonomy_version_id", "source_theme_id"),
            (
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_redirect_same_snapshot_source",
        ),
        ForeignKeyConstraint(
            ("taxonomy_version_id", "target_theme_id"),
            (
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ),
            ondelete="CASCADE",
            name="fk_economic_redirect_same_snapshot_target",
        ),
        CheckConstraint(
            "source_theme_id <> target_theme_id",
            name="ck_economic_redirect_distinct_endpoints",
        ),
        UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_redirect_logical_row",
        ),
    )


ECONOMIC_VERSION_OWNED_MODELS = (
    EconomicThemeRevision,
    EconomicThemeAlias,
    FacetDimension,
    FacetValue,
    EconomicThemeFacet,
    EconomicThemeRelationship,
    TaxonomyPolicy,
    LegacyIdentityDisposition,
    LegacyDestinationMapping,
    LegacyClaimAllocation,
    EconomicThemeRedirect,
)

ECONOMIC_TAXONOMY_TABLES = [
    TaxonomyVersion.__table__,
    EconomicTheme.__table__,
    EconomicThemeRevision.__table__,
    EconomicThemeAlias.__table__,
    FacetDimension.__table__,
    FacetValue.__table__,
    EconomicThemeFacet.__table__,
    EconomicThemeRelationship.__table__,
    TaxonomyPolicy.__table__,
    LegacyIdentityDisposition.__table__,
    LegacyDestinationMapping.__table__,
    LegacyClaimAllocation.__table__,
    EconomicThemeRedirect.__table__,
]


@event.listens_for(Session, "before_flush")
def _protect_economic_taxonomy_snapshots(session, _flush_context, _instances):
    for theme in session.dirty:
        if not isinstance(theme, EconomicTheme):
            continue
        if inspect(theme).attrs.semantic_key.history.has_changes():
            raise ImmutableSnapshot("theme_semantic_key_immutable")

    for version in session.dirty | session.deleted:
        if not isinstance(version, TaxonomyVersion):
            continue
        state = inspect(version)
        prior_statuses = state.attrs.status.history.deleted
        prior_status = prior_statuses[0] if prior_statuses else version.status
        if prior_status == "sealed":
            raise ImmutableSnapshot("sealed_snapshot_immutable")

    for row in session.new | session.dirty | session.deleted:
        if not isinstance(row, ECONOMIC_VERSION_OWNED_MODELS):
            continue
        state = inspect(row)
        history = state.attrs.taxonomy_version_id.history
        if row in session.dirty and history.has_changes():
            raise ImmutableSnapshot("version_owned_row_move")
        prior_ids = history.deleted
        version_id = prior_ids[0] if prior_ids else row.taxonomy_version_id
        if version_id is None:
            continue
        with session.no_autoflush:
            version = session.get(TaxonomyVersion, version_id)
        if version is not None and version.status == "sealed":
            raise ImmutableSnapshot("sealed_snapshot_immutable")


_CREATE_VERSION_TRIGGER_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION economic_taxonomy_reject_sealed_version_mutation()
    RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'DELETE' AND OLD.status = 'sealed' THEN
        RAISE EXCEPTION 'sealed_snapshot_immutable';
      END IF;
      IF TG_OP = 'UPDATE' THEN
        IF OLD.id IS DISTINCT FROM NEW.id THEN
          RAISE EXCEPTION 'taxonomy_version_identity_immutable';
        END IF;
        IF OLD.status = 'sealed' THEN
          RAISE EXCEPTION 'sealed_snapshot_immutable';
        END IF;
      END IF;
      RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")

_CREATE_OWNED_TRIGGER_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION economic_taxonomy_reject_sealed_owned_mutation()
    RETURNS trigger AS $$
    DECLARE
      target_version uuid;
      target_status text;
    BEGIN
      IF TG_OP = 'UPDATE' AND NEW.taxonomy_version_id IS DISTINCT FROM OLD.taxonomy_version_id THEN
        RAISE EXCEPTION 'version_owned_row_move';
      END IF;
      target_version := CASE WHEN TG_OP = 'DELETE' THEN OLD.taxonomy_version_id ELSE NEW.taxonomy_version_id END;
      SELECT status INTO target_status
        FROM economic_taxonomy_versions
        WHERE id = target_version
        FOR KEY SHARE;
      IF target_status = 'sealed' THEN
        RAISE EXCEPTION 'sealed_snapshot_immutable';
      END IF;
      RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")

_CREATE_THEME_IDENTITY_TRIGGER_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION economic_taxonomy_reject_theme_identity_mutation()
    RETURNS trigger AS $$
    BEGIN
      IF OLD.id IS DISTINCT FROM NEW.id OR OLD.semantic_key IS DISTINCT FROM NEW.semantic_key THEN
        RAISE EXCEPTION 'theme_semantic_key_immutable';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")

event.listen(TaxonomyVersion.__table__, "after_create", _CREATE_VERSION_TRIGGER_FUNCTION)
event.listen(TaxonomyVersion.__table__, "after_create", _CREATE_OWNED_TRIGGER_FUNCTION)
event.listen(
    EconomicTheme.__table__, "after_create", _CREATE_THEME_IDENTITY_TRIGGER_FUNCTION
)
event.listen(
    EconomicTheme.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trg_economic_theme_identity_immutable
        BEFORE UPDATE ON economic_themes
        FOR EACH ROW EXECUTE FUNCTION economic_taxonomy_reject_theme_identity_mutation();
        """
    ).execute_if(dialect="postgresql"),
)
event.listen(
    TaxonomyVersion.__table__,
    "after_create",
    DDL(
        """
        CREATE TRIGGER trg_economic_taxonomy_version_immutable
        BEFORE UPDATE OR DELETE ON economic_taxonomy_versions
        FOR EACH ROW EXECUTE FUNCTION economic_taxonomy_reject_sealed_version_mutation();
        """
    ).execute_if(dialect="postgresql"),
)

for _owned_model in ECONOMIC_VERSION_OWNED_MODELS:
    event.listen(
        _owned_model.__table__,
        "after_create",
        DDL(
            f"""
            CREATE TRIGGER trg_{_owned_model.__tablename__}_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON {_owned_model.__tablename__}
            FOR EACH ROW EXECUTE FUNCTION economic_taxonomy_reject_sealed_owned_mutation();
            """
        ).execute_if(dialect="postgresql"),
    )
