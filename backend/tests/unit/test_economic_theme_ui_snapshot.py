from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app.models.economic_taxonomy import EconomicTheme
from app.models.economic_taxonomy_runtime import (
    DevelopmentSelectionRevision,
    ImmutableRuntimePayload,
    MetricsRevision,
    ReaderSnapshotEntry,
    ThemeMetric,
)
from app.services.economic_taxonomy_snapshot_builder import (
    GenerationSnapshotInputs,
    SnapshotBundleError,
    build_snapshot_bundle,
)

from .economic_taxonomy_reader_helpers import seed_generation


def test_build_snapshot_bundle_seals_immutable_payload_rows(db_session):
    seeded = seed_generation(db_session)
    entries = db_session.query(ReaderSnapshotEntry).filter_by(
        reader_snapshot_bundle_id=seeded["bundle"].id
    ).all()

    assert seeded["bundle"].status == "sealed"
    assert {(row.snapshot_kind, row.resource_key) for row in entries} == {
        ("economic_themes", "catalog"),
        ("economic_taxonomy", "review"),
    }
    original = entries[0].payload.copy()
    db_session.add(
        DevelopmentSelectionRevision(
            development_identity=uuid4(),
            revision_number=1,
            selected=False,
            payload={},
        )
    )
    db_session.flush()
    assert entries[0].payload == original

    entries[0].payload = {"changed": True}
    with pytest.raises(ImmutableRuntimePayload, match="sealed_payload_immutable"):
        db_session.flush()


def test_snapshot_rejects_metric_theme_outside_taxonomy(db_session):
    seeded = seed_generation(db_session)
    rogue = EconomicTheme(created_by="test:reader")
    db_session.add(rogue)
    db_session.flush()
    metrics = MetricsRevision(
        status="unsealed",
        interpretation_set_id=seeded["interpretation"].id,
        generation_input_manifest_id=seeded["manifest"].id,
        formula_version="metrics-rogue",
        as_of=datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc),
        created_by="test:reader",
    )
    db_session.add(metrics)
    db_session.flush()
    db_session.add(
        ThemeMetric(
            metrics_revision_id=metrics.id,
            economic_theme_id=rogue.id,
            ranking_view="technical_attention",
            available=False,
            components={"availability": "unavailable"},
        )
    )
    db_session.flush()
    metrics.seal(
        semantic_hash="rogue-metrics",
        artifact_integrity_hash="rogue-metrics-artifact",
    )
    db_session.flush()
    with pytest.raises(SnapshotBundleError, match="snapshot_reference_not_in_taxonomy"):
        build_snapshot_bundle(
            db_session,
            GenerationSnapshotInputs(
                taxonomy_version_id=seeded["taxonomy"].id,
                interpretation_set_id=seeded["interpretation"].id,
                generation_input_manifest_id=seeded["manifest"].id,
                metrics_revision_id=metrics.id,
                created_by="test:reader",
            ),
        )
