from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from app.domain.cot.models import NormalizedCotWeek, Participant, RawParticipantPosition
from app.domain.cot.registry import instrument_by_slug
from app.domain.cot.validation import validate_cot_snapshot


def expected_counts(*weeks: NormalizedCotWeek) -> dict[str, int]:
    counts: dict[str, int] = {}
    for week in weeks:
        counts[week.source_dataset_id] = counts.get(week.source_dataset_id, 0) + 1
    return counts


def make_valid_week(
    report_date: date,
    *,
    slug: str = "gold",
) -> NormalizedCotWeek:
    definition = instrument_by_slug(slug)
    reportables = tuple(
        participant
        for participant in definition.participants
        if participant is not Participant.NONREPORTABLES
    )
    reportable_positions = tuple(
        RawParticipantPosition(participant, 100, 100, 0)
        for participant in reportables
    )
    reported_total = 100 * len(reportables)
    positions = reportable_positions + (
        RawParticipantPosition(
            Participant.NONREPORTABLES,
            1000 - reported_total,
            1000 - reported_total,
            0,
        ),
    )
    return NormalizedCotWeek(
        source_dataset_id=(
            "gpe5-46if"
            if definition.report_family.value == "tff_futures_only"
            else "72hh-3qpy"
        ),
        source_row_id=f"{slug}-{report_date.isoformat()}",
        source_fingerprint=f"fingerprint-{slug}-{report_date.isoformat()}",
        instrument_slug=slug,
        report_date=report_date,
        open_interest=1000,
        reported_long_total=reported_total,
        reported_short_total=reported_total,
        positions=positions,
    )


def definition_for(week: NormalizedCotWeek):
    return instrument_by_slug(week.instrument_slug)


def replace_position(
    week: NormalizedCotWeek,
    participant: Participant,
    *,
    long_delta: int,
) -> NormalizedCotWeek:
    return replace(
        week,
        positions=tuple(
            replace(position, long=position.long + long_delta)
            if position.participant is participant
            else position
            for position in week.positions
        ),
    )


def test_validation_accepts_a_complete_reconciled_snapshot():
    latest = date(2026, 9, 8)
    weeks = tuple(
        make_valid_week(latest - timedelta(weeks=index))
        for index in range(156)
    )

    result = validate_cot_snapshot(
        weeks,
        (definition_for(weeks[0]),),
        (),
        expected_counts(*weeks),
    )

    assert result.valid is True
    assert result.reason_codes == ()
    assert result.week_count == 156


def test_validation_rejects_duplicate_instrument_week():
    week = make_valid_week(date(2026, 9, 8))
    duplicated = (week, week)

    result = validate_cot_snapshot(
        duplicated,
        (definition_for(week),),
        (),
        expected_counts(*duplicated),
    )

    assert result.valid is False
    assert "duplicate_instrument_report_date" in result.reason_codes


def test_validation_rejects_reportable_reconciliation_failure():
    valid_week = make_valid_week(date(2026, 9, 8))
    broken = replace_position(valid_week, Participant.MANAGED_MONEY, long_delta=1)

    result = validate_cot_snapshot(
        (broken,),
        (definition_for(broken),),
        (),
        expected_counts(broken),
    )

    assert result.valid is False
    assert "reported_long_reconciliation_failed" in result.reason_codes


def test_validation_rejects_source_history_truncation():
    snapshot = (
        make_valid_week(date(2026, 9, 1)),
        make_valid_week(date(2026, 9, 8)),
    )
    existing = frozenset(
        (row.instrument_slug, row.report_date) for row in snapshot
    )

    result = validate_cot_snapshot(
        snapshot[1:],
        (definition_for(snapshot[0]),),
        existing,
        expected_counts(snapshot[1]),
    )

    assert result.valid is False
    assert "source_history_truncated" in result.reason_codes


def test_validation_requires_every_family_instrument_at_the_common_latest_date():
    gold = make_valid_week(date(2026, 9, 8), slug="gold")
    silver = make_valid_week(date(2026, 9, 1), slug="silver")

    result = validate_cot_snapshot(
        (gold, silver),
        (instrument_by_slug("gold"), instrument_by_slug("silver")),
        (),
        expected_counts(gold, silver),
    )

    assert result.valid is False
    assert "incomplete_latest_family_coverage" in result.reason_codes


def test_validation_requires_a_common_latest_date_across_report_families():
    gold = make_valid_week(date(2026, 9, 8), slug="gold")
    sp_500 = make_valid_week(date(2026, 9, 1), slug="sp-500")

    result = validate_cot_snapshot(
        (gold, sp_500),
        (instrument_by_slug("gold"), instrument_by_slug("sp-500")),
        (("gold", gold.report_date), ("sp-500", sp_500.report_date)),
        expected_counts(gold, sp_500),
    )

    assert result.valid is False
    assert "mixed_latest_report_dates" in result.reason_codes


def test_validation_rejects_truncated_initial_history():
    week = make_valid_week(date(2026, 9, 8))

    result = validate_cot_snapshot(
        (week,),
        (definition_for(week),),
        (),
        expected_counts(week),
    )

    assert result.valid is False
    assert "insufficient_initial_history" in result.reason_codes


def test_validation_requires_initial_history_for_each_new_registry_instrument():
    latest = date(2026, 9, 8)
    gold_weeks = tuple(
        make_valid_week(latest - timedelta(weeks=index), slug="gold")
        for index in range(156)
    )
    silver_week = make_valid_week(latest, slug="silver")
    weeks = gold_weeks + (silver_week,)
    existing_gold_keys = tuple(
        (week.instrument_slug, week.report_date) for week in gold_weeks
    )

    result = validate_cot_snapshot(
        weeks,
        (instrument_by_slug("gold"), instrument_by_slug("silver")),
        existing_gold_keys,
        expected_counts(*weeks),
    )

    assert result.valid is False
    assert "insufficient_initial_history" in result.reason_codes


def test_validation_rejects_wrong_official_dataset_identity():
    week = replace(
        make_valid_week(date(2026, 9, 8)),
        source_dataset_id="gpe5-46if",
    )

    result = validate_cot_snapshot(
        (week,),
        (definition_for(week),),
        (),
        expected_counts(week),
    )

    assert result.valid is False
    assert "source_dataset_mismatch" in result.reason_codes


def test_validation_rejects_three_year_history_below_authoritative_row_count():
    latest = date(2026, 9, 8)
    weeks = tuple(
        make_valid_week(latest - timedelta(weeks=index))
        for index in range(156)
    )

    result = validate_cot_snapshot(
        weeks,
        (definition_for(weeks[0]),),
        (),
        {"72hh-3qpy": 900},
    )

    assert result.valid is False
    assert "source_row_count_mismatch" in result.reason_codes
