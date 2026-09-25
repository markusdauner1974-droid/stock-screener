from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
    GraphInvariantViolation,
    ImmutableSnapshot,
    SnapshotValidationError,
)
from app.models.economic_taxonomy import (
    ECONOMIC_TAXONOMY_TABLES,
    EconomicTheme,
    EconomicThemeAlias,
    EconomicThemeRevision,
    FacetDimension,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=ECONOMIC_TAXONOMY_TABLES)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def repo(session):
    return EconomicTaxonomyRepository(session)


def _draft_with_two_themes(repo):
    draft = repo.create_draft(actor="test:author", reason="test snapshot")
    copper = repo.create_theme(
        draft.id,
        display_name="Copper",
        definition="Economic exposure to copper demand and pricing.",
        mechanism="Copper market economics",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
    )
    miners = repo.create_theme(
        draft.id,
        display_name="Copper Miners",
        definition="Producers whose economics depend on copper mining.",
        mechanism="Copper mine production",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
    )
    return draft, copper, miners


@pytest.fixture
def sealed_version(repo, session):
    draft, copper, miners = _draft_with_two_themes(repo)
    repo.add_alias(draft.id, copper.id, "Copper Exposure")
    repo.add_dimension(
        draft.id,
        key="industry",
        definition="Primary industry boundary.",
        inclusion_semantics="Include economic production industries.",
        exclusion_semantics="Exclude customer end markets.",
        value_type="text",
        cardinality="many",
        scope="theme",
        normalization_policy="casefold-v1",
    )
    repo.add_facet_value(draft.id, "industry", "mining", "Mining")
    repo.assign_facet(draft.id, miners.id, "industry", "mining")
    repo.add_specialization(draft.id, narrower=miners.id, broader=copper.id)
    repo.add_policy(draft.id, "resolver", "resolver-v1")
    sealed = repo.seal_draft(draft.id)
    session.commit()
    return sealed


def test_semantic_clone_hash_ignores_ids_and_audit_metadata(
    repo, sealed_version
):
    clone = repo.clone_draft(
        sealed_version.id, actor="test:cloner", reason="clone for change"
    )

    assert repo.semantic_hash(clone.id) == repo.semantic_hash(sealed_version.id)
    assert repo.artifact_integrity_hash(clone.id) != repo.artifact_integrity_hash(
        sealed_version.id
    )


def test_clone_contains_complete_semantic_snapshot(repo, sealed_version):
    clone = repo.clone_draft(
        sealed_version.id, actor="test:cloner", reason="complete clone"
    )
    source = repo.load_snapshot(sealed_version.id)
    copied = repo.load_snapshot(clone.id)

    for collection in (
        "themes",
        "aliases",
        "dimensions",
        "facet_values",
        "theme_facets",
        "relationships",
        "policies",
    ):
        assert len(copied[collection]) == len(source[collection])


def test_sealed_snapshot_cannot_reopen(repo, sealed_version):
    with pytest.raises(ImmutableSnapshot, match="sealed_snapshot_immutable"):
        repo.set_status(sealed_version.id, "draft")


def test_sealed_snapshot_rejects_owned_row_insert(repo, sealed_version):
    theme_id = repo.load_snapshot(sealed_version.id)["themes"][0]["theme_id"]

    with pytest.raises(ImmutableSnapshot, match="sealed_snapshot_immutable"):
        repo.add_alias(sealed_version.id, theme_id, "Late Alias")


def test_specialization_cycle_is_rejected(repo):
    draft, copper, miners = _draft_with_two_themes(repo)
    repo.add_specialization(draft.id, narrower=copper.id, broader=miners.id)
    repo.add_specialization(draft.id, narrower=miners.id, broader=copper.id)

    with pytest.raises(GraphInvariantViolation, match="specialization_cycle"):
        repo.seal_draft(draft.id)


def test_distinct_cannot_contradict_specialization(repo):
    draft, copper, miners = _draft_with_two_themes(repo)
    repo.add_specialization(draft.id, narrower=miners.id, broader=copper.id)
    repo.add_relationship(
        draft.id,
        source_theme_id=copper.id,
        target_theme_id=miners.id,
        kind="distinct",
        direction="symmetric",
        discriminator="legal structure",
    )

    with pytest.raises(
        GraphInvariantViolation, match="contradictory_relationship_assertion"
    ):
        repo.seal_draft(draft.id)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("definition", "Revised semantic boundary."),
        ("inclusion_semantics", "Include only producers."),
        ("exclusion_semantics", "Exclude services."),
        ("value_type", "controlled_text"),
        ("cardinality", "one"),
        ("scope", "constituent"),
        ("normalization_policy", "casefold-v2"),
    ],
)
def test_each_dimension_semantic_field_changes_catalog_and_snapshot_hash(
    repo, field, value
):
    draft = repo.create_draft(actor="test:author", reason="dimension hash")
    repo.add_dimension(
        draft.id,
        key="industry",
        definition="Industry boundary.",
        inclusion_semantics="Include industries.",
        exclusion_semantics="Exclude products.",
        value_type="text",
        cardinality="many",
        scope="theme",
        normalization_policy="casefold-v1",
    )
    before_catalog = repo.facet_catalog_semantic_hash(draft.id)
    before_snapshot = repo.semantic_hash(draft.id)

    repo.update_dimension(draft.id, "industry", **{field: value})

    assert repo.facet_catalog_semantic_hash(draft.id) != before_catalog
    assert repo.semantic_hash(draft.id) != before_snapshot


def test_audit_metadata_does_not_change_semantic_hash(repo, session):
    draft, copper, _miners = _draft_with_two_themes(repo)
    before = repo.semantic_hash(draft.id)
    revision = session.scalar(
        select(EconomicThemeRevision).where(
            EconomicThemeRevision.taxonomy_version_id == draft.id,
            EconomicThemeRevision.theme_id == copper.id,
        )
    )

    revision.review_comment = "Audit-only reviewer note."
    session.flush()

    assert repo.semantic_hash(draft.id) == before


def test_row_cannot_move_between_versions(repo, session):
    first, copper, _miners = _draft_with_two_themes(repo)
    second = repo.create_draft(actor="test:author", reason="other snapshot")
    revision = session.scalar(
        select(EconomicThemeRevision).where(
            EconomicThemeRevision.taxonomy_version_id == first.id,
            EconomicThemeRevision.theme_id == copper.id,
        )
    )

    revision.taxonomy_version_id = second.id
    with pytest.raises(ImmutableSnapshot, match="version_owned_row_move"):
        session.flush()


def test_stable_theme_semantic_key_cannot_change(repo, session):
    _draft, copper, _miners = _draft_with_two_themes(repo)
    stable_identity = session.get(EconomicTheme, copper.id)
    stable_identity.semantic_key = uuid4()

    with pytest.raises(ImmutableSnapshot, match="theme_semantic_key_immutable"):
        session.flush()


def test_cross_snapshot_alias_reference_is_rejected(repo):
    first, copper, _miners = _draft_with_two_themes(repo)
    second = repo.create_draft(actor="test:author", reason="other snapshot")

    with pytest.raises(SnapshotValidationError, match="same_snapshot_reference"):
        repo.add_alias(second.id, copper.id, "Cross-snapshot alias")


def test_relationship_endpoints_must_exist_in_same_snapshot(repo):
    draft, copper, _miners = _draft_with_two_themes(repo)

    with pytest.raises(SnapshotValidationError, match="same_snapshot_reference"):
        repo.add_relationship(
            draft.id,
            source_theme_id=copper.id,
            target_theme_id=uuid4(),
            kind="distinct",
            direction="symmetric",
            discriminator="different mechanism",
        )


def test_semantic_relationship_discriminator_changes_hash(repo, session):
    draft, copper, miners = _draft_with_two_themes(repo)
    relationship = repo.add_relationship(
        draft.id,
        source_theme_id=copper.id,
        target_theme_id=miners.id,
        kind="distinct",
        direction="symmetric",
        discriminator="business model",
    )
    before = repo.semantic_hash(draft.id)

    relationship.discriminator = "economic transmission mechanism"
    session.flush()

    assert repo.semantic_hash(draft.id) != before


def test_model_tables_use_composite_same_snapshot_foreign_keys():
    alias_targets = {
        tuple(foreign_key.column.name for foreign_key in constraint.elements)
        for constraint in EconomicThemeAlias.__table__.foreign_key_constraints
    }
    revision_primary_key = tuple(
        column.name for column in EconomicThemeRevision.__table__.primary_key.columns
    )
    dimension_primary_key = tuple(
        column.name for column in FacetDimension.__table__.primary_key.columns
    )

    assert ("taxonomy_version_id", "theme_id") in alias_targets
    assert revision_primary_key == ("taxonomy_version_id", "theme_id")
    assert dimension_primary_key == ("taxonomy_version_id", "key")


def test_core_migration_creates_same_snapshot_schema(tmp_path):
    database_path = tmp_path / "economic-taxonomy.sqlite"
    migrated_engine = create_engine(f"sqlite:///{database_path}")
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260921_0046_economic_taxonomy_core.py"
    )
    try:
        spec = importlib.util.spec_from_file_location(
            "economic_taxonomy_core_migration", migration_path
        )
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with migrated_engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        schema = inspect(migrated_engine)
        assert {
            "economic_taxonomy_versions",
            "economic_themes",
            "economic_theme_revisions",
            "economic_theme_aliases",
            "economic_facet_dimensions",
            "economic_facet_values",
            "economic_theme_facets",
            "economic_theme_relationships",
            "economic_taxonomy_policies",
        }.issubset(schema.get_table_names())
        alias_foreign_keys = schema.get_foreign_keys("economic_theme_aliases")
        assert any(
            foreign_key["constrained_columns"]
            == ["taxonomy_version_id", "theme_id"]
            for foreign_key in alias_foreign_keys
        )
    finally:
        migrated_engine.dispose()
