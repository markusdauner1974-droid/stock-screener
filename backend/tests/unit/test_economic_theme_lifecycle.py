from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.models.economic_taxonomy import EconomicThemeRevision
from app.models.economic_taxonomy_runtime import (
    TaxonomyAuthority,
    TaxonomySourceRevisionLog,
)
from app.services.economic_theme_lifecycle_service import (
    EconomicThemeLifecycleService,
    LifecycleRoot,
    LifecycleTheme,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _root(*, days=0, family=None):
    return LifecycleRoot(
        source_family_id=family or uuid4(), available_at=NOW - timedelta(days=days)
    )


def test_provisional_requires_roots_families_dates_and_breadth():
    family_a = uuid4()
    family_b = uuid4()
    eligible = LifecycleTheme(
        theme_id=uuid4(),
        state="provisional",
        roots=(
            _root(days=1, family=family_a),
            _root(days=2, family=family_a),
            _root(days=3, family=family_b),
        ),
        accepted_constituent_security_ids=frozenset({11, 12}),
    )
    no_breadth = LifecycleTheme(
        theme_id=uuid4(),
        state="provisional",
        roots=eligible.roots,
    )

    assert EconomicThemeLifecycleService.evaluate(eligible, as_of=NOW).state == (
        "established"
    )
    assert EconomicThemeLifecycleService.evaluate(no_breadth, as_of=NOW).state == (
        "provisional"
    )


def test_authenticated_breadth_assertion_can_establish_provisional_theme():
    family_a = uuid4()
    family_b = uuid4()
    theme = LifecycleTheme(
        theme_id=uuid4(),
        state="provisional",
        roots=(
            _root(days=1, family=family_a),
            _root(days=2, family=family_a),
            _root(days=3, family=family_b),
        ),
        reviewed_multi_security_breadth=True,
        breadth_assertion_actor="admin:alice",
    )

    assert EconomicThemeLifecycleService.evaluate(theme, as_of=NOW).state == (
        "established"
    )


def test_reactivated_theme_can_become_dormant_again_without_losing_timestamp():
    family_a = uuid4()
    family_b = uuid4()
    initial = LifecycleTheme(
        theme_id=uuid4(),
        state="established",
        roots=(),
    )
    dormant = EconomicThemeLifecycleService.evaluate(initial, as_of=NOW)
    reactivation_input = LifecycleTheme(
        theme_id=initial.theme_id,
        state=dormant.state,
        roots=(
            LifecycleRoot(family_a, NOW + timedelta(days=8)),
            LifecycleRoot(family_b, NOW + timedelta(days=9)),
        ),
    )
    reactivated = EconomicThemeLifecycleService.evaluate(
        reactivation_input, as_of=NOW + timedelta(days=9)
    )
    dormant_again = EconomicThemeLifecycleService.evaluate(
        LifecycleTheme(
            theme_id=initial.theme_id,
            state=reactivated.state,
            roots=(),
            reactivated_at=reactivated.reactivated_at,
        ),
        as_of=NOW + timedelta(days=100),
    )

    assert [dormant.state, reactivated.state, dormant_again.state] == [
        "dormant",
        "reactivated",
        "dormant",
    ]
    assert dormant_again.reactivated_at == reactivated.reactivated_at


def test_retirement_is_never_automatic():
    retired = LifecycleTheme(theme_id=uuid4(), state="retired", roots=())
    established = LifecycleTheme(theme_id=uuid4(), state="established", roots=())

    assert EconomicThemeLifecycleService.evaluate(retired, as_of=NOW).state == "retired"
    assert EconomicThemeLifecycleService.evaluate(established, as_of=NOW).state != (
        "retired"
    )


def test_propose_lifecycle_snapshot_advances_processing_not_serving(db_session):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:author", reason="lifecycle fixture")
    theme = repo.create_theme(
        draft.id,
        display_name="AI Memory",
        definition="Memory exposed to AI demand.",
        mechanism="AI server memory demand",
        lifecycle="provisional",
        lifecycle_policy_version="lifecycle-v1",
    )
    taxonomy = repo.seal_draft(draft.id)
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=2,
            authority_epoch=4,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            rollback_state="ready",
        )
    )
    db_session.commit()
    family_a = uuid4()
    family_b = uuid4()
    lifecycle_input = LifecycleTheme(
        theme_id=theme.id,
        state="provisional",
        roots=(
            _root(days=1, family=family_a),
            _root(days=2, family=family_a),
            _root(days=3, family=family_b),
        ),
        accepted_constituent_security_ids=frozenset({1, 2}),
    )
    principal = AdminPrincipal(
        subject="system:economic-taxonomy-refresh",
        auth_method="service_principal",
        roles=frozenset({"taxonomy:review"}),
    )

    result = EconomicThemeLifecycleService(db_session).propose_lifecycle_snapshot(
        themes=[lifecycle_input],
        as_of=NOW,
        principal=principal,
        expected_epoch=4,
    )
    db_session.commit()

    authority = db_session.get(TaxonomyAuthority, 1)
    revision = db_session.get(
        EconomicThemeRevision, (result.taxonomy_version_id, theme.id)
    )
    dirty = db_session.scalar(select(TaxonomySourceRevisionLog))
    assert result.transition_count == 1
    assert revision.lifecycle == "established"
    assert revision.lifecycle_policy_version == "economic-theme-lifecycle-v1"
    assert authority.processing_taxonomy_version_id == result.taxonomy_version_id
    assert authority.serving_generation_id is None
    assert dirty.revision_kind == "lifecycle_change"
