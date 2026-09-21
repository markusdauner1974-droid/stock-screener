from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.infra.db.models.social_analysis import (
    EconomicSocialAssociation,
    EconomicSocialAssociationRevision,
    EconomicSocialAssociationSource,
    SocialExtractionWork,
    SocialRunWork,
    SocialThemeAssociation,
)
from app.infra.db.models.social_signals import SocialSignalRun, SocialSourceRegistry
from app.models.economic_taxonomy import EconomicTheme
from app.models.economic_taxonomy_runtime import TaxonomyAuthority
from app.models.stock_universe import StockUniverse
from app.models.theme import ContentItem, ThemeCluster
from app.services.economic_source_admission import EvidenceAdmission
from app.services.economic_taxonomy_fence import AuthorityWritesFenced
from app.services.social_theme_market_service import EconomicAcceptedBasketReader
from app.services.social_theme_projection_service import EconomicSocialTaxonomyAdapter

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _global_pair(db_session):
    theme = EconomicTheme(created_by="test:social")
    security = StockUniverse(symbol="MU", market="US", is_active=True)
    db_session.add_all([theme, security])
    db_session.flush()
    return theme, security


def _legacy_association(db_session, *, name: str, state: str):
    cluster = ThemeCluster(
        name=name,
        display_name=name,
        canonical_key=name.casefold().replace(" ", "_"),
        pipeline="technical",
    )
    db_session.add(cluster)
    db_session.flush()
    association = SocialThemeAssociation(
        theme_cluster_id=cluster.id,
        market="US",
        canonical_symbol="MU",
        state=state,
        origin="social",
        decision_owner="admin",
        evidence_work_ids=[],
        policy_version="social-theme-v1",
        version=1,
        first_seen_at=NOW,
        accepted_at=NOW if state == "accepted" else None,
        updated_at=NOW,
    )
    db_session.add(association)
    db_session.flush()
    return association


def test_two_legacy_associations_bridge_one_global_membership(db_session):
    theme, security = _global_pair(db_session)
    accepted_a = _legacy_association(db_session, name="AI Memory A", state="accepted")
    accepted_b = _legacy_association(db_session, name="AI Memory B", state="accepted")

    result = EconomicSocialTaxonomyAdapter(db_session).project_legacy_associations(
        economic_theme_id=theme.id,
        security_id=security.id,
        legacy_association_ids=(accepted_a.id, accepted_b.id),
    )

    assert result.global_association_count == 1
    assert result.bridge_count == 2
    assert result.state == "accepted"
    assert result.live is True
    assert db_session.query(EconomicSocialAssociation).count() == 1
    assert db_session.query(EconomicSocialAssociationSource).count() == 2


def test_conflicting_admin_decisions_are_order_independent_and_not_live(db_session):
    theme, security = _global_pair(db_session)
    accepted = _legacy_association(db_session, name="Memory", state="accepted")
    rejected = _legacy_association(db_session, name="Memory Chips", state="rejected")
    adapter = EconomicSocialTaxonomyAdapter(db_session)

    first = adapter.project_legacy_associations(
        economic_theme_id=theme.id,
        security_id=security.id,
        legacy_association_ids=(accepted.id, rejected.id),
    )
    second = adapter.project_legacy_associations(
        economic_theme_id=theme.id,
        security_id=security.id,
        legacy_association_ids=(rejected.id, accepted.id),
    )

    assert first.state == second.state == "conflict_review_required"
    assert first.live is second.live is False
    assert db_session.query(EconomicSocialAssociationRevision).count() == 1


def test_admin_rejection_prevents_system_acceptance(db_session):
    theme, security = _global_pair(db_session)
    automatic = _legacy_association(db_session, name="Automatic Memory", state="accepted")
    automatic.decision_owner = "system"
    rejected = _legacy_association(db_session, name="Reviewed Memory", state="rejected")

    result = EconomicSocialTaxonomyAdapter(db_session).project_legacy_associations(
        economic_theme_id=theme.id,
        security_id=security.id,
        legacy_association_ids=(automatic.id, rejected.id),
    )

    assert result.state == "rejected"
    assert result.live is False


def test_pair_revision_history_is_pinned_and_decision_retry_is_idempotent(db_session):
    theme, security = _global_pair(db_session)
    adapter = EconomicSocialTaxonomyAdapter(db_session)
    association = adapter.get_or_create_association(theme.id, security.id)

    accepted = adapter.revise(
        association.id,
        state="accepted",
        idempotency_key="decision-1",
        actor="admin:test",
        reason="reviewed",
        mirror_acknowledged=True,
    )
    accepted_ref = adapter.pin_revision(accepted.id)
    rejected = adapter.revise(
        association.id,
        state="rejected",
        idempotency_key="decision-2",
        actor="admin:test",
        reason="corrected",
        mirror_acknowledged=True,
    )
    retry = adapter.revise(
        association.id,
        state="rejected",
        idempotency_key="decision-2",
        actor="admin:test",
        reason="corrected",
        mirror_acknowledged=True,
    )
    rejected_ref = adapter.pin_revision(rejected.id)

    assert [accepted.revision_number, rejected.revision_number] == [1, 2]
    assert retry.id == rejected.id
    assert adapter.membership(accepted_ref.id).state == "accepted"
    assert adapter.membership(accepted_ref.id).live is True
    assert adapter.membership(rejected_ref.id).state == "rejected"
    assert adapter.membership(rejected_ref.id).live is False

    historical = EconomicAcceptedBasketReader(
        db_session,
        economic_theme_id=theme.id,
        association_revision_ref_ids=(accepted_ref.id,),
    ).read("memory", "US")
    current = EconomicAcceptedBasketReader(
        db_session,
        economic_theme_id=theme.id,
    ).read("memory", "US")
    assert historical.company_stock_symbols == ("MU",)
    assert current.company_stock_symbols == ()


def test_native_membership_waits_for_legacy_mirror_before_becoming_live(db_session):
    theme, security = _global_pair(db_session)
    adapter = EconomicSocialTaxonomyAdapter(db_session)
    association = adapter.get_or_create_association(theme.id, security.id)

    pending = adapter.revise(
        association.id,
        state="accepted",
        idempotency_key="native-decision",
        actor="admin:test",
        reason="reviewed native membership",
        mirror_acknowledged=False,
    )

    assert pending.state == "pending_legacy_mirror"
    assert pending.live is False
    assert db_session.query(SocialThemeAssociation).count() == 0

    acknowledged = adapter.apply_legacy_mirror(pending.id, now=NOW)

    assert acknowledged.state == "accepted"
    assert acknowledged.live is True
    assert acknowledged.mirror_state == "acknowledged"
    assert db_session.query(SocialThemeAssociation).count() == 1
    assert db_session.query(EconomicSocialAssociationSource).count() == 1


def test_native_legacy_mirror_respects_authority_write_fence(db_session):
    theme, security = _global_pair(db_session)
    adapter = EconomicSocialTaxonomyAdapter(db_session)
    association = adapter.get_or_create_association(theme.id, security.id)
    pending = adapter.revise(
        association.id,
        state="accepted",
        idempotency_key="fenced-native-decision",
        actor="admin:test",
        reason="reviewed native membership",
        mirror_acknowledged=False,
    )
    authority = TaxonomyAuthority(
        id=1,
        mode="economic",
        processing_head_revision=0,
        authority_epoch=4,
        writes_fenced=True,
        semantic_invalidation_revision=0,
        cutover_catch_up_cursor=[],
        rollback_state="ready",
    )
    db_session.add(authority)
    db_session.flush()

    with pytest.raises(AuthorityWritesFenced, match="authority_writes_fenced"):
        adapter.apply_legacy_mirror(pending.id, now=NOW)

    assert db_session.query(SocialThemeAssociation).count() == 0


def _saved_work(db_session, *, run_status: str):
    registry = db_session.get(SocialSourceRegistry, 1)
    if registry is None:
        registry = SocialSourceRegistry(id=1, mode="live", provider="official")
        db_session.add(registry)
    item = ContentItem(
        source_type="twitter",
        external_id=f"post-{run_status}",
        url=f"https://x.com/a/status/{run_status}",
        content="Memory pricing rose.",
        published_at=NOW,
    )
    db_session.add(item)
    db_session.flush()
    work = SocialExtractionWork(
        content_item_id=item.id,
        input_hash=f"hash-{run_status}",
        prompt_version="social-v1",
        schema_version="social-v1",
        selected_model="synthetic/model",
        input_snapshot_json={"provider_post_id": item.external_id},
        result_json={"status": "accepted_candidates"},
        state="succeeded",
    )
    run = SocialSignalRun(
        id=f"run-{run_status}",
        registry_id=1,
        registry_version=1,
        mode="live",
        provider="official",
        status="running",
        source_outcomes_json={},
        application_progress_json={},
        feature_run_ids_json={},
        exposure_dates_json={},
        coverage_json={},
    )
    db_session.add_all([work, run])
    db_session.flush()
    db_session.add(
        SocialRunWork(
            run_id=run.id,
            work_id=work.id,
            input_hash=work.input_hash,
            included_at=NOW,
        )
    )
    db_session.flush()
    run.status = "staged"
    db_session.flush()
    if run_status == "published":
        run.status = "published"
        run.published_at = NOW
        db_session.flush()
    return work


def _evidence(work, *, capture_route="social", partial_recapture=False):
    return EvidenceAdmission(
        provider="x",
        canonical_item_id=str(work.content_item_id),
        capture_route=capture_route,
        original_text="Memory pricing rose.",
        preparation_version="social-prep-v1",
        captured_at=NOW,
        observed_at=NOW,
        available_at=NOW,
        evidence_channels=("narrative",),
        source_metadata={
            "archived": "archive" in capture_route,
            "partial_recapture": partial_recapture,
        },
    )


def test_only_published_succeeded_effective_work_is_live_admitted(db_session):
    published = _saved_work(db_session, run_status="published")
    staged = _saved_work(db_session, run_status="staged")
    adapter = EconomicSocialTaxonomyAdapter(db_session)

    admitted = adapter.admit_saved_work(published.id, _evidence(published))
    review_only = adapter.admit_saved_work(staged.id, _evidence(staged))

    assert admitted.precedence_state == "effective"
    assert admitted.live is True
    assert review_only.live is False
    assert review_only.admission_state == "review_only"


def test_unordered_late_archive_remains_review_only(db_session):
    work = _saved_work(db_session, run_status="published")

    result = EconomicSocialTaxonomyAdapter(db_session).admit_saved_work(
        work.id,
        _evidence(work, capture_route="social-archive"),
    )

    assert result.precedence_state == "hold_review"
    assert result.live is False
    assert result.admission_state == "review_only"


def test_partial_recapture_remains_review_only(db_session):
    work = _saved_work(db_session, run_status="published")

    result = EconomicSocialTaxonomyAdapter(db_session).admit_saved_work(
        work.id,
        _evidence(work, partial_recapture=True),
    )

    assert result.precedence_state == "hold_review"
    assert result.live is False


def test_legacy_rows_are_not_mutated_by_global_projection(db_session):
    theme, security = _global_pair(db_session)
    legacy = _legacy_association(db_session, name="Memory Legacy", state="accepted")
    before = tuple(
        db_session.execute(
            select(*SocialThemeAssociation.__table__.columns).where(
                SocialThemeAssociation.id == legacy.id
            )
        ).one()
    )

    EconomicSocialTaxonomyAdapter(db_session).project_legacy_associations(
        economic_theme_id=theme.id,
        security_id=security.id,
        legacy_association_ids=(legacy.id,),
    )
    after = tuple(
        db_session.execute(
            select(*SocialThemeAssociation.__table__.columns).where(
                SocialThemeAssociation.id == legacy.id
            )
        ).one()
    )

    assert after == before
