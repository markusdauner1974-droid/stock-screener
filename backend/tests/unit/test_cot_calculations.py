from datetime import date

import pytest

from app.domain.cot.calculations import (
    align_prices_to_report_dates,
    derive_all_instrument_series,
    derive_position_series,
    rolling_net_percentiles,
)
from app.domain.cot.models import NormalizedCotWeek, Participant, RawParticipantPosition


def make_week(
    report_date: str,
    *,
    long: int,
    short: int,
    open_interest: int,
    slug: str = "gold",
) -> NormalizedCotWeek:
    return NormalizedCotWeek(
        source_dataset_id="fixture",
        source_row_id=f"{slug}-{report_date}",
        source_fingerprint=f"fingerprint-{slug}-{report_date}",
        instrument_slug=slug,
        report_date=date.fromisoformat(report_date),
        open_interest=open_interest,
        reported_long_total=long,
        reported_short_total=short,
        positions=(
            RawParticipantPosition(
                participant=Participant.MANAGED_MONEY,
                long=long,
                short=short,
                spreading=0,
            ),
        ),
    )


def test_midrank_percentile_requires_exactly_156_values():
    values = tuple(range(155)) + (100,)

    result = rolling_net_percentiles(values)

    assert result[154] is None
    assert result[155] == pytest.approx(100 * (100 + 0.5 * 2) / 156)


def test_derivation_uses_long_minus_short_and_previous_report_week():
    weeks = (
        make_week("2026-09-01", long=120, short=80, open_interest=1000),
        make_week("2026-09-08", long=150, short=90, open_interest=1200),
    )

    current = derive_position_series(weeks)[1].positions[0]

    assert current.net == 60
    assert current.delta_long == 30
    assert current.delta_short == 10
    assert current.delta_net == 20
    assert current.net_pct_open_interest == pytest.approx(5.0)


def test_all_instrument_derivation_groups_before_calculating_deltas():
    weeks = (
        make_week("2026-09-08", long=150, short=90, open_interest=1200),
        make_week(
            "2026-09-08",
            long=80,
            short=60,
            open_interest=500,
            slug="silver",
        ),
        make_week("2026-09-01", long=120, short=80, open_interest=1000),
    )

    derived = derive_all_instrument_series(weeks)

    assert [(week.instrument_slug, week.report_date) for week in derived] == [
        ("gold", date(2026, 9, 1)),
        ("gold", date(2026, 9, 8)),
        ("silver", date(2026, 9, 8)),
    ]
    assert derived[-1].positions[0].delta_net is None


def test_price_alignment_uses_latest_close_on_or_before_tuesday():
    aligned = align_prices_to_report_dates(
        (date(2026, 9, 1), date(2026, 9, 8)),
        {date(2026, 8, 31): 100.0, date(2026, 9, 8): 105.0},
    )

    assert aligned[0].price_date == date(2026, 8, 31)
    assert aligned[1].weekly_change_pct == pytest.approx(5.0)


def test_price_alignment_preserves_missing_values_instead_of_inventing_zero():
    aligned = align_prices_to_report_dates((date(2026, 9, 1),), {})

    assert aligned[0].price_date is None
    assert aligned[0].close is None
    assert aligned[0].weekly_change_pct is None
