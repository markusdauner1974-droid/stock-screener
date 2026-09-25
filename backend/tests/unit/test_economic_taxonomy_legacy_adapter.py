from __future__ import annotations

import pytest

from app.models.economic_taxonomy_runtime import (
    TaxonomyAuthority,
    TaxonomyProjectionEvent,
    TaxonomySourceRevisionLog,
)
from app.services.economic_taxonomy_fence import AuthorityModeRejected
from app.services.economic_taxonomy_runtime import EconomicTaxonomyRuntimeService
from app.services.theme_discovery_service import ThemeDiscoveryService


def test_fenced_legacy_write_commits_domain_revision_and_shadow_projection(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_head_revision=1,
            authority_epoch=7,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()
    runtime = EconomicTaxonomyRuntimeService(db_session)

    with runtime.legacy_producer_write(
        expected_epoch=7,
        logical_source_key="theme_cluster:42",
        revision_kind="legacy_theme_update",
        content_hash="hash-1",
        auto_commit=True,
    ) as write:
        write.stage_compatibility_projection(
            source_lineage="legacy-theme:42",
            projection_revision=1,
            projection_kind="economic_theme",
            projection_version=1,
            target="economic",
            payload={"legacy_theme_cluster_id": 42},
            origin_representation="legacy",
        )

    revision = db_session.query(TaxonomySourceRevisionLog).one()
    projection = db_session.query(TaxonomyProjectionEvent).one()
    assert revision.authority_epoch == 7
    assert projection.delivery_scope == "shadow"


def test_legacy_mode_records_revision_without_staging_comparison(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="legacy",
            processing_head_revision=1,
            authority_epoch=3,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()

    with EconomicTaxonomyRuntimeService(db_session).legacy_producer_write(
        expected_epoch=3,
        logical_source_key="theme_cluster:42",
        revision_kind="legacy_theme_update",
        content_hash=lambda: "hash-after-domain-mutation",
        auto_commit=True,
    ) as write:
        event = write.stage_next_compatibility_projection(
            source_lineage="legacy-theme:42",
            projection_kind="economic_theme",
            projection_version=1,
            target="economic",
            payload={"legacy_theme_cluster_id": 42},
        )

    assert event is None
    assert db_session.query(TaxonomyProjectionEvent).count() == 0
    assert db_session.query(TaxonomySourceRevisionLog).one().content_hash == (
        "hash-after-domain-mutation"
    )


def test_shadow_projections_allocate_monotonic_revisions(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_head_revision=1,
            authority_epoch=7,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()
    runtime = EconomicTaxonomyRuntimeService(db_session)

    for payload in ({"themes": ["memory"]}, {"themes": []}):
        with runtime.legacy_producer_write(
            expected_epoch=7,
            logical_source_key="theme_pipeline:technical",
            revision_kind="metrics_refresh",
            content_hash="hash",
            auto_commit=True,
        ) as write:
            write.stage_next_compatibility_projection(
                source_lineage="legacy-theme-pipeline:technical",
                projection_kind="metrics_refresh",
                projection_version=1,
                target="economic",
                payload=payload,
            )

    assert [
        event.projection_revision
        for event in db_session.query(TaxonomyProjectionEvent).order_by(
            TaxonomyProjectionEvent.projection_revision
        )
    ] == [1, 2]


def test_theme_discovery_mutation_records_revision_and_shadow_payload(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_head_revision=1,
            authority_epoch=7,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()

    result = ThemeDiscoveryService(
        db_session, pipeline="technical"
    ).promote_candidate_themes(expected_authority_epoch=7)

    revision = db_session.query(TaxonomySourceRevisionLog).one()
    projection = db_session.query(TaxonomyProjectionEvent).one()
    assert result["scanned"] == 0
    assert revision.logical_source_key == "legacy-theme-pipeline:technical"
    assert revision.revision_kind == "candidate_promotion"
    assert projection.source_lineage == (
        "legacy-theme-pipeline:technical:candidate_promotion"
    )
    assert projection.delivery_scope == "shadow"
    assert projection.payload["scanned"] == 0


def test_legacy_writer_is_rejected_after_economic_cutover(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_head_revision=1,
            authority_epoch=8,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()

    with (
        pytest.raises(AuthorityModeRejected),
        EconomicTaxonomyRuntimeService(db_session).legacy_producer_write(
            expected_epoch=8,
            logical_source_key="theme_cluster:42",
            revision_kind="legacy_theme_update",
            content_hash="hash-1",
            auto_commit=True,
        ),
    ):
        pass


def test_mirror_origin_suppresses_reverse_projection(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="dual",
            processing_head_revision=1,
            authority_epoch=7,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()

    with EconomicTaxonomyRuntimeService(db_session).legacy_producer_write(
        expected_epoch=7,
        logical_source_key="mirror:42",
        revision_kind="legacy_theme_update",
        content_hash="hash-1",
        auto_commit=True,
        origin_representation="economic",
    ) as write:
        event = write.stage_compatibility_projection(
            source_lineage="legacy-theme:42",
            projection_revision=1,
            projection_kind="economic_theme",
            projection_version=1,
            target="economic",
            payload={"legacy_theme_cluster_id": 42},
            origin_representation="economic",
        )

    assert event is None
    assert db_session.query(TaxonomyProjectionEvent).count() == 0
