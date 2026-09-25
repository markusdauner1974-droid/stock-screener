from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
    PublicationInvariantError,
)
from app.models.economic_taxonomy import (
    ECONOMIC_TAXONOMY_TABLES,
    TaxonomyVersion,
)
from app.models.economic_taxonomy_runtime import (
    ECONOMIC_TAXONOMY_RUNTIME_TABLES,
    GenerationInputManifest,
    ImmutableRuntimePayload,
    InterpretationSet,
    MetricsRevision,
    ReaderCapabilityManifest,
    ReaderSnapshotBundle,
    ServingGenerationEvent,
    TaxonomyAuthority,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[*ECONOMIC_TAXONOMY_TABLES, *ECONOMIC_TAXONOMY_RUNTIME_TABLES],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _sealed_payloads(db):
    taxonomy = TaxonomyVersion(
        status="sealed",
        semantic_hash="taxonomy-semantic",
        artifact_integrity_hash="taxonomy-artifact",
        created_by="operator:alice",
        reason="test",
        sealed_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )
    db.add(taxonomy)
    db.flush()
    manifest = GenerationInputManifest(
        status="unsealed",
        expected_parent_generation_id=None,
        semantic_invalidation_revision=3,
        committed_revision_tuples=[],
        selections=[],
        created_by="operator:alice",
    )
    db.add(manifest)
    db.flush()
    manifest.seal(
        semantic_hash="manifest-semantic", artifact_integrity_hash="manifest-artifact"
    )
    db.flush()
    interpretation = InterpretationSet(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        created_by="operator:alice",
    )
    db.add(interpretation)
    db.flush()
    interpretation.seal(
        semantic_hash="interpretation-semantic",
        artifact_integrity_hash="interpretation-artifact",
    )
    metrics = MetricsRevision(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        interpretation_set_id=interpretation.id,
        formula_version="metrics-v1",
        as_of=datetime(2026, 9, 21, tzinfo=timezone.utc),
        created_by="operator:alice",
    )
    snapshots = ReaderSnapshotBundle(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        payload={},
        created_by="operator:alice",
    )
    capability = ReaderCapabilityManifest(
        backend_contract=1,
        frontend_contract=1,
        migration_version="0048",
        consumer_test_hash="tests-1",
        verified_by="operator:alice",
    )
    db.add_all([metrics, snapshots, capability])
    db.flush()
    metrics.seal(semantic_hash="metrics-semantic", artifact_integrity_hash="metrics-artifact")
    snapshots.seal(
        semantic_hash="snapshots-semantic", artifact_integrity_hash="snapshots-artifact"
    )
    db.flush()
    return taxonomy, manifest, interpretation, metrics, snapshots, capability


def test_processing_head_is_not_the_serving_pointer(db):
    authority = TaxonomyAuthority(
        id=1,
        mode="shadow",
        processing_head_revision=22,
        authority_epoch=7,
        writes_fenced=False,
        rollback_state="ready",
    )
    db.add(authority)
    db.flush()

    assert authority.processing_head_revision == 22
    assert authority.serving_generation_id is None


def test_manifest_normalizes_exact_committed_inputs_before_sealing(db):
    manifest = GenerationInputManifest(
        status="unsealed",
        expected_parent_generation_id=None,
        semantic_invalidation_revision=3,
        committed_revision_tuples=[
            ["social", "post-2", "decision", 4, "hash-b"],
            ["content", "post-1", "evidence", 2, "hash-a"],
        ],
        selections=[
            {"lineage": "lineage-b", "evidence_packet_id": "packet-b"},
            {"lineage": "lineage-a", "evidence_packet_id": "packet-a"},
        ],
        created_by="operator:alice",
    )
    db.add(manifest)
    db.flush()
    manifest.seal(semantic_hash="semantic", artifact_integrity_hash="artifact")
    db.flush()

    assert manifest.committed_revision_tuples[0][1] == "post-1"
    assert manifest.selections[0]["lineage"] == "lineage-a"
    manifest.selections = []
    with pytest.raises(ImmutableRuntimePayload, match="sealed_payload_immutable"):
        db.flush()


def test_serving_generation_requires_one_sealed_manifest(db):
    taxonomy, manifest, interpretation, metrics, snapshots, capability = _sealed_payloads(db)
    repo = EconomicTaxonomyPublicationRepository(db)

    generation = repo.prepare_generation(
        taxonomy_version_id=taxonomy.id,
        interpretation_set_id=interpretation.id,
        metrics_revision_id=metrics.id,
        generation_input_manifest_id=manifest.id,
        reader_snapshot_bundle_id=snapshots.id,
        reader_capability_manifest_id=capability.id,
        semantic_hash="generation-semantic",
        artifact_integrity_hash="generation-artifact",
        actor="operator:alice",
    )
    db.flush()

    assert generation.generation_input_manifest_id == manifest.id
    assert [event.event_type for event in generation.events] == ["prepared"]


def test_generation_rejects_payloads_from_different_manifest(db):
    taxonomy, manifest, interpretation, metrics, snapshots, capability = _sealed_payloads(db)
    other = GenerationInputManifest(
        status="unsealed",
        semantic_invalidation_revision=3,
        committed_revision_tuples=[],
        selections=[],
        created_by="operator:alice",
    )
    db.add(other)
    db.flush()
    other.seal(semantic_hash="other", artifact_integrity_hash="other-artifact")
    db.flush()
    metrics.generation_input_manifest_id = other.id
    # This deliberate fixture mismatch must be installed without changing a
    # sealed row through the ORM guard.
    db.expunge(metrics)
    db.query(MetricsRevision).filter(MetricsRevision.id == metrics.id).update(
        {MetricsRevision.generation_input_manifest_id: other.id},
        synchronize_session=False,
    )
    db.flush()

    with pytest.raises(PublicationInvariantError, match="manifest_mismatch"):
        EconomicTaxonomyPublicationRepository(db).prepare_generation(
            taxonomy_version_id=taxonomy.id,
            interpretation_set_id=interpretation.id,
            metrics_revision_id=metrics.id,
            generation_input_manifest_id=manifest.id,
            reader_snapshot_bundle_id=snapshots.id,
            reader_capability_manifest_id=capability.id,
            semantic_hash="generation-semantic",
            artifact_integrity_hash="generation-artifact",
            actor="operator:alice",
        )


def test_generation_payload_and_events_are_immutable(db):
    taxonomy, manifest, interpretation, metrics, snapshots, capability = _sealed_payloads(db)
    repo = EconomicTaxonomyPublicationRepository(db)
    generation = repo.prepare_generation(
        taxonomy_version_id=taxonomy.id,
        interpretation_set_id=interpretation.id,
        metrics_revision_id=metrics.id,
        generation_input_manifest_id=manifest.id,
        reader_snapshot_bundle_id=snapshots.id,
        reader_capability_manifest_id=capability.id,
        semantic_hash="generation-semantic",
        artifact_integrity_hash="generation-artifact",
        actor="operator:alice",
    )
    db.commit()
    generation.semantic_hash = "changed"
    with pytest.raises(ImmutableRuntimePayload, match="runtime_payload_immutable"):
        db.flush()
    db.rollback()
    event_row = db.query(ServingGenerationEvent).one()
    event_row.event_type = "published"
    with pytest.raises(ImmutableRuntimePayload, match="runtime_payload_immutable"):
        db.flush()

