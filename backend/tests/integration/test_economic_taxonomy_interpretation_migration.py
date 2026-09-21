from __future__ import annotations

import importlib.util
from pathlib import Path
from datetime import datetime, timezone

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.database import engine as application_engine
from app.models.economic_taxonomy_runtime import (
    EvidencePacket,
    SourceFamily,
    SourceLineage,
)


VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name):
    path = VERSIONS / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_interpretation_migration_builds_append_only_runtime_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.sqlite'}")
    core = _load("20260921_0046_economic_taxonomy_core.py")
    runtime = _load("20260921_0047_economic_taxonomy_interpretations.py")
    try:
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            core.op = operations
            runtime.op = operations
            core.upgrade()
            runtime.upgrade()

        schema = inspect(engine)
        assert runtime.revision == "20260921_0047"
        assert runtime.down_revision == "20260921_0046"
        assert {
            "economic_source_families",
            "economic_source_lineages",
            "economic_evidence_packets",
            "economic_processing_requests",
            "economic_extraction_artifacts",
            "economic_claim_review_artifacts",
            "economic_classification_attempts",
            "economic_classification_attempt_events",
            "economic_claim_assignments",
            "economic_interpretation_sets",
            "economic_interpretation_selections",
            "economic_theme_observations",
            "economic_theme_constituent_exposures",
            "economic_theme_signal_observations",
            "economic_theme_embeddings",
            "economic_metrics_revisions",
            "economic_theme_metrics",
        }.issubset(schema.get_table_names())

        attempt_uniques = schema.get_unique_constraints(
            "economic_classification_attempts"
        )
        assert any(
            "input_taxonomy_version_id" in constraint["column_names"]
            for constraint in attempt_uniques
        )
    finally:
        engine.dispose()


def _packet(lineage_id, suffix):
    return EvidencePacket(
        source_lineage_id=lineage_id,
        packet_hash=f"packet-{suffix}",
        evidence_content_fingerprint=f"content-{suffix}",
        capture_route="integration-test",
        captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        original_text_ref=f"sha256:{suffix}",
        attachment_hashes=[],
        extracted_text_hashes=[],
        grounding_snapshot={},
        preparation_version="prep-v1",
        source_metadata={},
        available_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        precedence_state="effective",
    )


@pytest.mark.skipif(
    application_engine.dialect.name != "postgresql",
    reason="requires PostgreSQL row locks",
)
def test_evidence_ordinal_allocator_serializes_on_the_lineage_row():
    factory = sessionmaker(bind=application_engine, expire_on_commit=False)
    setup = factory()
    family = SourceFamily(
        provider="x",
        canonical_source_key="x:post:concurrent",
        canonical_item_id="concurrent",
    )
    setup.add(family)
    setup.flush()
    lineage = SourceLineage(source_family_id=family.id)
    setup.add(lineage)
    setup.commit()
    lineage_id = lineage.id
    setup.close()

    locker = factory()
    contender = factory()
    try:
        first = _packet(lineage_id, "first")
        locker.add(first)
        locker.flush()
        assert first.evidence_revision_ordinal == 1

        contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
        contender.add(_packet(lineage_id, "blocked"))
        with pytest.raises(DBAPIError):
            contender.flush()
        contender.rollback()

        locker.commit()
        second = _packet(lineage_id, "second")
        contender.add(second)
        contender.flush()
        assert second.evidence_revision_ordinal == 2
        contender.commit()
    finally:
        locker.rollback()
        contender.rollback()
        locker.close()
        contender.close()


@pytest.mark.skipif(
    application_engine.dialect.name != "postgresql",
    reason="requires PostgreSQL immutable triggers",
)
def test_database_trigger_rejects_direct_runtime_payload_mutation():
    factory = sessionmaker(bind=application_engine, expire_on_commit=False)
    session = factory()
    family = SourceFamily(
        provider="x",
        canonical_source_key="x:post:immutable",
        canonical_item_id="immutable",
    )
    session.add(family)
    session.flush()
    lineage = SourceLineage(source_family_id=family.id)
    session.add(lineage)
    session.flush()
    packet = _packet(lineage.id, "immutable")
    session.add(packet)
    session.commit()
    packet_id = packet.id
    session.close()

    connection = application_engine.connect()
    transaction = connection.begin()
    try:
        with pytest.raises(DBAPIError, match="runtime_payload_immutable"):
            connection.execute(
                update(EvidencePacket)
                .where(EvidencePacket.id == packet_id)
                .values(packet_hash="changed")
            )
    finally:
        transaction.rollback()
        connection.close()
