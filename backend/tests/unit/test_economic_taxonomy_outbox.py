from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.models.economic_taxonomy_runtime import (
    GenerationInputManifest,
    InterpretationSet,
    MetricsRevision,
    ReaderCapabilityManifest,
    ReaderSnapshotBundle,
    ServingGeneration,
    ServingGenerationEvent,
    TaxonomyAuthority,
    TaxonomyProjectionEvent,
)
from app.models.theme import ThemeCluster, ThemeConstituent
from app.services.economic_taxonomy_runtime import (
    EconomicTaxonomyRuntimeService,
    ProjectionPayloadConflict,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _generation(db_session, *, events):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:publisher", reason="outbox fixture")
    taxonomy = repo.seal_draft(draft.id)
    manifest = GenerationInputManifest(
        status="unsealed",
        semantic_invalidation_revision=0,
        committed_revision_tuples=[],
        selections=[],
        created_by="test:publisher",
    )
    db_session.add(manifest)
    db_session.flush()
    manifest.seal(semantic_hash="manifest", artifact_integrity_hash="manifest-artifact")
    interpretation = InterpretationSet(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        created_by="test:publisher",
    )
    db_session.add(interpretation)
    db_session.flush()
    interpretation.seal(
        semantic_hash="interpretation",
        artifact_integrity_hash="interpretation-artifact",
    )
    metrics = MetricsRevision(
        status="unsealed",
        interpretation_set_id=interpretation.id,
        generation_input_manifest_id=manifest.id,
        formula_version=f"metrics-{uuid4()}",
        as_of=NOW,
        created_by="test:publisher",
    )
    snapshot = ReaderSnapshotBundle(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        payload={},
        created_by="test:publisher",
    )
    capability = ReaderCapabilityManifest(
        backend_contract=1,
        frontend_contract=1,
        migration_version=str(uuid4()),
        consumer_test_hash=str(uuid4()),
        verified_by="test:publisher",
    )
    db_session.add_all([metrics, snapshot, capability])
    db_session.flush()
    metrics.seal(semantic_hash="metrics", artifact_integrity_hash="metrics-artifact")
    snapshot.seal(semantic_hash="snapshot", artifact_integrity_hash="snapshot-artifact")
    generation = ServingGeneration(
        taxonomy_version_id=taxonomy.id,
        interpretation_set_id=interpretation.id,
        metrics_revision_id=metrics.id,
        generation_input_manifest_id=manifest.id,
        reader_snapshot_bundle_id=snapshot.id,
        reader_capability_manifest_id=capability.id,
        semantic_hash=str(uuid4()),
        artifact_integrity_hash=str(uuid4()),
        created_by="test:publisher",
    )
    db_session.add(generation)
    db_session.flush()
    for sequence, event_type in enumerate(events, 1):
        db_session.add(
            ServingGenerationEvent(
                serving_generation_id=generation.id,
                sequence_number=sequence,
                event_type=event_type,
                actor="test:publisher",
                details={},
            )
        )
    db_session.flush()
    return taxonomy, generation


def _stage(service, *, generation_id=None, lineage="post:1", revision=1, epoch=10):
    return service.stage_projection(
        generation_id=generation_id,
        source_lineage=lineage,
        projection_revision=revision,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
        payload={"themes": ["memory"]},
        staged_epoch=epoch,
        origin_representation="economic",
        selected_interpretation_version="interpretation:1",
        mapping_version="mapping:1",
    )


def test_retry_after_epoch_change_reuses_logical_event(db_session):
    service = EconomicTaxonomyRuntimeService(db_session)

    first = _stage(service, revision=2, epoch=10)
    retry = _stage(service, revision=2, epoch=11)

    assert retry.id == first.id
    assert db_session.query(TaxonomyProjectionEvent).count() == 1


def test_same_logical_event_cannot_change_replacement_payload(db_session):
    service = EconomicTaxonomyRuntimeService(db_session)
    _stage(service, revision=2)

    with pytest.raises(ProjectionPayloadConflict, match="projection_payload_conflict"):
        service.stage_projection(
            generation_id=None,
            source_lineage="post:1",
            projection_revision=2,
            projection_kind="legacy_theme",
            projection_version=1,
            target="legacy",
            payload={"themes": ["copper"]},
            staged_epoch=11,
            origin_representation="economic",
            selected_interpretation_version="interpretation:1",
            mapping_version="mapping:1",
        )


def test_older_delivery_cannot_restore_state(db_session):
    service = EconomicTaxonomyRuntimeService(db_session)

    service.apply_replacement(
        target="legacy",
        source_lineage="post:1",
        projection_kind="legacy_theme",
        projection_revision=2,
        payload={"themes": ["new"]},
        origin_representation="economic",
    )
    applied = service.apply_replacement(
        target="legacy",
        source_lineage="post:1",
        projection_kind="legacy_theme",
        projection_revision=1,
        payload={"themes": ["old"]},
        origin_representation="economic",
    )

    assert applied is False
    assert service.current_payload(
        target="legacy", source_lineage="post:1", projection_kind="legacy_theme"
    ) == {"themes": ["new"]}


def test_empty_replacement_retracts_only_its_lineage(db_session):
    service = EconomicTaxonomyRuntimeService(db_session)
    for lineage in ("a", "b"):
        service.apply_replacement(
            target="legacy",
            source_lineage=lineage,
            projection_kind="legacy_theme",
            projection_revision=1,
            payload={"themes": ["memory"]},
            origin_representation="economic",
        )
    service.apply_replacement(
        target="legacy",
        source_lineage="a",
        projection_kind="legacy_theme",
        projection_revision=2,
        payload={"themes": []},
        origin_representation="economic",
    )

    assert service.supporting_lineages(
        target="legacy", projection_kind="legacy_theme", theme="memory"
    ) == {"b"}


def test_legacy_theme_delivery_materializes_and_retracts_legacy_reader_rows(
    db_session,
):
    service = EconomicTaxonomyRuntimeService(db_session)
    theme_id = uuid4()
    first = service.stage_projection(
        generation_id=None,
        source_lineage="post:1",
        projection_revision=1,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
        payload={
            "themes": [str(theme_id)],
            "theme_details": [
                {
                    "economic_theme_id": str(theme_id),
                    "display_name": "AI Memory",
                    "definition": "Memory exposed to AI infrastructure demand.",
                    "lifecycle": "established",
                    "constituents": ["MU"],
                }
            ],
        },
        staged_epoch=10,
        origin_representation="economic",
        selected_interpretation_version="interpretation:1",
        mapping_version="mapping:1",
    )

    service.apply_projection_event(first, authority_epoch=10, now=NOW)

    cluster = db_session.scalar(
        select(ThemeCluster).where(
            ThemeCluster.pipeline == "technical",
            ThemeCluster.canonical_key == f"economic_{theme_id.hex}",
        )
    )
    assert cluster.display_name == "AI Memory"
    assert cluster.lifecycle_state == "active"
    assert cluster.is_active is True
    assert len(cluster.discovery_source) <= ThemeCluster.discovery_source.type.length
    constituent = db_session.scalar(
        select(ThemeConstituent).where(
            ThemeConstituent.theme_cluster_id == cluster.id,
            ThemeConstituent.symbol == "MU",
        )
    )
    assert constituent.is_active is True
    fundamental = db_session.scalar(
        select(ThemeCluster).where(
            ThemeCluster.pipeline == "fundamental",
            ThemeCluster.canonical_key == f"economic_{theme_id.hex}",
        )
    )
    assert fundamental.display_name == "AI Memory"
    assert fundamental.is_active is True
    assert {
        row.symbol
        for row in db_session.scalars(
            select(ThemeConstituent).where(
                ThemeConstituent.theme_cluster_id == fundamental.id,
                ThemeConstituent.is_active.is_(True),
            )
        )
    } == {"MU"}

    second_source = service.stage_projection(
        generation_id=None,
        source_lineage="post:2",
        projection_revision=1,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
        payload={
            "themes": [str(theme_id)],
            "theme_details": [
                {
                    "economic_theme_id": str(theme_id),
                    "display_name": "AI Memory",
                    "definition": "Memory exposed to AI infrastructure demand.",
                    "lifecycle": "established",
                    "constituents": ["WDC"],
                }
            ],
        },
        staged_epoch=10,
        origin_representation="economic",
        selected_interpretation_version="interpretation:1",
        mapping_version="mapping:1",
    )
    service.apply_projection_event(second_source, authority_epoch=10, now=NOW)

    retraction = service.stage_projection(
        generation_id=None,
        source_lineage="post:1",
        projection_revision=2,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
        payload={"themes": [], "theme_details": []},
        staged_epoch=10,
        origin_representation="economic",
        selected_interpretation_version="interpretation:2",
        mapping_version="mapping:2",
    )
    service.apply_projection_event(retraction, authority_epoch=10, now=NOW)

    assert cluster.is_active is True
    assert constituent.is_active is False
    assert (
        db_session.scalar(
            select(ThemeConstituent).where(
                ThemeConstituent.theme_cluster_id == cluster.id,
                ThemeConstituent.symbol == "WDC",
            )
        ).is_active
        is True
    )

    final_retraction = service.stage_projection(
        generation_id=None,
        source_lineage="post:2",
        projection_revision=2,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
        payload={"themes": [], "theme_details": []},
        staged_epoch=10,
        origin_representation="economic",
        selected_interpretation_version="interpretation:2",
        mapping_version="mapping:2",
    )
    service.apply_projection_event(final_retraction, authority_epoch=10, now=NOW)

    assert cluster.is_active is False
    assert fundamental.is_active is False


def _legacy_theme_event(service, lineage, revision, theme_id, name, symbols):
    return service.stage_projection(
        generation_id=None,
        source_lineage=lineage,
        projection_revision=revision,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
        payload={
            "themes": [str(theme_id)] if theme_id else [],
            "theme_details": (
                [
                    {
                        "economic_theme_id": str(theme_id),
                        "display_name": name,
                        "definition": None,
                        "lifecycle": "established",
                        "constituents": list(symbols),
                    }
                ]
                if theme_id
                else []
            ),
        },
        staged_epoch=10,
        origin_representation="economic",
        selected_interpretation_version=f"interpretation:{revision}",
        mapping_version="mapping:1",
    )


def test_legacy_theme_delivery_recomputes_only_affected_themes(db_session):
    service = EconomicTaxonomyRuntimeService(db_session)
    memory, power = uuid4(), uuid4()
    service.apply_projection_event(
        _legacy_theme_event(service, "post:1", 1, memory, "AI Memory", ["MU"]),
        authority_epoch=10,
        now=NOW,
    )
    memory_clusters = db_session.scalars(
        select(ThemeCluster).where(
            ThemeCluster.canonical_key == f"economic_{memory.hex}"
        )
    ).all()
    assert len(memory_clusters) == 2
    for cluster in memory_clusters:
        cluster.display_name = "untouched sentinel"
    db_session.flush()

    service.apply_projection_event(
        _legacy_theme_event(service, "post:2", 1, power, "AI Power", ["VST"]),
        authority_epoch=10,
        now=NOW,
    )

    assert {cluster.display_name for cluster in memory_clusters} == {
        "untouched sentinel"
    }
    power_clusters = db_session.scalars(
        select(ThemeCluster).where(
            ThemeCluster.canonical_key == f"economic_{power.hex}"
        )
    ).all()
    assert {(row.pipeline, row.display_name) for row in power_clusters} == {
        ("technical", "AI Power"),
        ("fundamental", "AI Power"),
    }

    service.apply_projection_event(
        _legacy_theme_event(service, "post:1", 2, None, None, []),
        authority_epoch=10,
        now=NOW,
    )

    assert {cluster.is_active for cluster in memory_clusters} == {False}
    assert {cluster.is_active for cluster in power_clusters} == {True}


def test_delivery_eligibility_comes_from_publication_history(db_session):
    taxonomy, published_generation = _generation(
        db_session, events=("prepared", "published", "superseded")
    )
    _other_taxonomy, abandoned_generation = _generation(
        db_session, events=("prepared", "abandoned")
    )
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=1,
            authority_epoch=10,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            rollback_state="ready",
        )
    )
    service = EconomicTaxonomyRuntimeService(db_session)
    published = _stage(service, generation_id=published_generation.id, lineage="a")
    abandoned = _stage(service, generation_id=abandoned_generation.id, lineage="b")
    db_session.commit()

    claims = service.claim_deliveries_from_published_generations(
        worker_id="worker:1", expected_epoch=10, now=NOW, limit=10
    )

    assert {claim.projection_event_id for claim in claims} == {published.id}
    assert abandoned.id not in {claim.projection_event_id for claim in claims}


def test_delivery_limit_is_applied_after_terminal_events_are_excluded(db_session):
    taxonomy, generation = _generation(db_session, events=("prepared", "published"))
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=1,
            authority_epoch=10,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            rollback_state="ready",
        )
    )
    service = EconomicTaxonomyRuntimeService(db_session)
    first = _stage(service, generation_id=generation.id, lineage="post:first")
    db_session.commit()
    first_claim = service.claim_deliveries_from_published_generations(
        worker_id="worker:1", expected_epoch=10, now=NOW, limit=1
    )[0]
    db_session.commit()
    service.apply_delivery(first_claim, expected_epoch=10, now=NOW)
    db_session.commit()

    second = _stage(service, generation_id=generation.id, lineage="post:second")
    db_session.commit()

    claims = service.claim_deliveries_from_published_generations(
        worker_id="worker:1", expected_epoch=10, now=NOW, limit=1
    )

    assert first.id != second.id
    assert [claim.projection_event_id for claim in claims] == [second.id]


def test_delivery_limit_is_applied_after_active_leases_are_excluded(db_session):
    taxonomy, generation = _generation(db_session, events=("prepared", "published"))
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=1,
            authority_epoch=10,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            rollback_state="ready",
        )
    )
    service = EconomicTaxonomyRuntimeService(db_session)
    first = _stage(service, generation_id=generation.id, lineage="post:leased")
    db_session.commit()
    service.claim_deliveries_from_published_generations(
        worker_id="worker:1", expected_epoch=10, now=NOW, limit=1
    )
    db_session.commit()
    if db_session.get_bind().dialect.name == "sqlite":
        db_session.execute(
            update(TaxonomyProjectionEvent)
            .where(TaxonomyProjectionEvent.id == first.id)
            .values(created_at=NOW - timedelta(minutes=1))
        )
        db_session.commit()

    second = _stage(service, generation_id=generation.id, lineage="post:available")
    db_session.commit()

    claims = service.claim_deliveries_from_published_generations(
        worker_id="worker:2", expected_epoch=10, now=NOW, limit=1
    )

    assert first.id != second.id
    assert [claim.projection_event_id for claim in claims] == [second.id]


def test_apply_delivery_is_a_non_recursive_complete_replacement(db_session):
    taxonomy, generation = _generation(db_session, events=("prepared", "published"))
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=1,
            authority_epoch=10,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            rollback_state="ready",
        )
    )
    service = EconomicTaxonomyRuntimeService(db_session)
    staged = _stage(service, generation_id=generation.id)
    db_session.commit()
    claim = service.claim_deliveries_from_published_generations(
        worker_id="worker:1", expected_epoch=10, now=NOW, limit=1
    )[0]
    db_session.commit()
    before = db_session.query(TaxonomyProjectionEvent).count()

    result = service.apply_delivery(claim, expected_epoch=10, now=NOW)
    db_session.commit()

    assert result.outcome == "success"
    assert result.applied is True
    assert (
        service.current_payload(
            target="legacy", source_lineage="post:1", projection_kind="legacy_theme"
        )["origin_representation"]
        == "economic"
    )
    assert db_session.query(TaxonomyProjectionEvent).count() == before
    assert service.generation_acknowledged(generation.id) is True
    assert staged.id == claim.projection_event_id


def test_shadow_projection_is_never_live_claimable(db_session):
    taxonomy, generation = _generation(db_session, events=("prepared", "published"))
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=1,
            authority_epoch=10,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            rollback_state="ready",
        )
    )
    service = EconomicTaxonomyRuntimeService(db_session)
    service.stage_projection(
        generation_id=generation.id,
        source_lineage="post:shadow",
        projection_revision=1,
        projection_kind="legacy_theme",
        projection_version=1,
        target="legacy",
        payload={"themes": ["memory"]},
        staged_epoch=10,
        origin_representation="economic",
        selected_interpretation_version="interpretation:1",
        mapping_version="mapping:1",
        delivery_scope="shadow",
    )
    db_session.commit()

    assert (
        service.claim_deliveries_from_published_generations(
            worker_id="worker:1", expected_epoch=10, now=NOW, limit=10
        )
        == []
    )
