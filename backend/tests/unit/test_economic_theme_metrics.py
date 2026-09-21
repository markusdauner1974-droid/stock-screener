from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.models.economic_taxonomy_runtime import (
    GenerationInputManifest,
    InterpretationSet,
    ThemeMetric,
)
from app.services.economic_theme_metrics_service import (
    EconomicThemeMetricsService,
    MetricObservation,
    MetricSignal,
    ThemeMetricInput,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _theme(*, lifecycle="established", observations=(), signals=()):
    return ThemeMetricInput(
        theme_id=uuid4(),
        lifecycle=lifecycle,
        observations=tuple(observations),
        signals=tuple(signals),
        eligible_channels=frozenset({"technical", "fundamental", "narrative"}),
        pinned_eligibility_revision_ids=("eligibility:1",),
    )


def _root(channel, *, days=0, family=None, direction=None):
    return MetricObservation(
        source_family_id=family or uuid4(),
        evidence_channel=channel,
        available_at=NOW - timedelta(days=days),
        direction=direction,
    )


def test_eligibility_without_support_is_unavailable():
    result = EconomicThemeMetricsService.calculate(_theme(), as_of=NOW)

    assert result.technical_attention.availability == "unavailable"
    assert result.fundamental_attention.availability == "unavailable"
    assert result.narrative_attention.availability == "unavailable"


def test_fundamental_attention_is_unsigned():
    family = uuid4()
    positive = EconomicThemeMetricsService.calculate(
        _theme(observations=[_root("fundamental", family=family, direction="positive")]),
        as_of=NOW,
    )
    negative = EconomicThemeMetricsService.calculate(
        _theme(observations=[_root("fundamental", family=family, direction="negative")]),
        as_of=NOW,
    )

    assert positive.fundamental_attention.raw == negative.fundamental_attention.raw
    assert positive.fundamental_attention.raw == pytest.approx(1.0)


def test_technical_root_and_duplicate_signals_contribute_once_per_family_day():
    family = uuid4()
    theme = _theme(
        observations=[
            MetricObservation(
                source_family_id=family,
                evidence_channel="technical",
                available_at=NOW - timedelta(hours=3),
            )
        ],
        signals=[
            MetricSignal(
                source_family_id=family,
                signal_kind="breakout",
                available_at=NOW - timedelta(hours=1),
            ),
            MetricSignal(
                source_family_id=family,
                signal_kind="vcp",
                available_at=NOW - timedelta(hours=2),
            ),
        ],
    )

    result = EconomicThemeMetricsService.calculate(theme, as_of=NOW)

    expected = 2 ** (-(1 / 24) / 5)
    assert result.technical_attention.raw == pytest.approx(expected)
    assert result.technical_attention.components["daily_contribution_count"] == 1


def test_closed_windows_include_lower_boundary_and_exclude_future():
    family_a = uuid4()
    family_b = uuid4()
    theme = _theme(
        observations=[
            _root("narrative", days=14, family=family_a),
            MetricObservation(
                source_family_id=family_b,
                evidence_channel="narrative",
                available_at=NOW + timedelta(seconds=1),
            ),
        ]
    )

    result = EconomicThemeMetricsService.calculate(theme, as_of=NOW)

    assert result.narrative_attention.raw == pytest.approx(2 ** (-14 / 3))


def test_derived_observations_and_unaccepted_signals_do_not_score():
    family = uuid4()
    result = EconomicThemeMetricsService.calculate(
        _theme(
            observations=[
                MetricObservation(
                    source_family_id=family,
                    evidence_channel="fundamental",
                    available_at=NOW,
                    observation_kind="derived_parent",
                    direct_root=False,
                )
            ],
            signals=[
                MetricSignal(
                    source_family_id=family,
                    signal_kind="breakout",
                    available_at=NOW,
                    accepted=False,
                )
            ],
        ),
        as_of=NOW,
    )

    assert result.fundamental_attention.availability == "unavailable"
    assert result.technical_attention.availability == "unavailable"


def test_emerging_requires_two_families_and_two_dates_in_last_seven_days():
    family_a = uuid4()
    family_b = uuid4()
    available = EconomicThemeMetricsService.calculate(
        _theme(
            lifecycle="provisional",
            observations=[
                _root("narrative", days=1, family=family_a),
                _root("fundamental", days=2, family=family_b),
                _root("narrative", days=10, family=uuid4()),
            ],
        ),
        as_of=NOW,
    )
    one_date = EconomicThemeMetricsService.calculate(
        _theme(
            lifecycle="reactivated",
            observations=[
                _root("narrative", days=1, family=family_a),
                _root("fundamental", days=1, family=family_b),
            ],
        ),
        as_of=NOW,
    )

    assert available.emerging.availability == "available"
    assert available.emerging.raw == pytest.approx(2 - (1 / 3))
    assert one_date.emerging.availability == "unavailable"


def test_rank_uses_average_ties_and_singleton_percentile_100():
    metrics = EconomicThemeMetricsService
    singleton = metrics.rank([metrics.available_value(4.0)])
    tied = metrics.rank(
        [
            metrics.available_value(1.0),
            metrics.available_value(1.0),
            metrics.available_value(3.0),
        ]
    )

    assert singleton[0].percentile == 100
    assert [value.percentile for value in tied] == [25, 25, 100]


def test_broad_confirmation_requires_two_channels_and_two_direct_families():
    technical_only = EconomicThemeMetricsService.calculate_and_rank(
        [_theme(observations=[_root("technical")])], as_of=NOW
    )[0]
    family_a = uuid4()
    family_b = uuid4()
    broad = EconomicThemeMetricsService.calculate_and_rank(
        [
            _theme(
                observations=[
                    _root("technical", family=family_a),
                    _root("fundamental", family=family_b),
                ]
            )
        ],
        as_of=NOW,
    )[0]

    assert technical_only.broad_confirmation.availability == "unavailable"
    assert broad.broad_confirmation.raw == pytest.approx(100.0)


def test_calculate_metrics_persists_sealed_formula_and_eligibility_provenance(
    db_session,
):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:author", reason="metrics fixture")
    theme = repo.create_theme(
        draft.id,
        display_name="AI Memory",
        definition="Memory exposed to AI demand.",
        mechanism="AI server memory demand",
        lifecycle="provisional",
        lifecycle_policy_version="lifecycle-v1",
    )
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
    manifest.seal(semantic_hash="manifest", artifact_integrity_hash="artifact")
    interpretation = InterpretationSet(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        created_by="test:publisher",
    )
    db_session.add(interpretation)
    db_session.flush()
    interpretation.seal(
        semantic_hash="interpretation", artifact_integrity_hash="artifact"
    )
    db_session.commit()

    result = EconomicThemeMetricsService(db_session).calculate_metrics(
        taxonomy_version_id=taxonomy.id,
        interpretation_set_id=interpretation.id,
        generation_input_manifest_id=manifest.id,
        as_of=NOW,
        actor="test:publisher",
        themes=[
            ThemeMetricInput(
                theme_id=theme.id,
                lifecycle="provisional",
                observations=(
                    _root("technical", family=uuid4()),
                    _root("fundamental", family=uuid4()),
                ),
                pinned_eligibility_revision_ids=("eligibility:7",),
            )
        ],
    )
    db_session.commit()

    rows = db_session.scalars(
        select(ThemeMetric).where(ThemeMetric.metrics_revision_id == result.id)
    ).all()
    assert result.status == "sealed"
    assert result.formula_version == "economic-theme-metrics-v1"
    assert len(rows) == 5
    assert all(
        row.components["pinned_eligibility_revision_ids"] == ["eligibility:7"]
        for row in rows
    )
