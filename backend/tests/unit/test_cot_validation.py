from __future__ import annotations

from dataclasses import replace
from datetime import date

from app.domain.cot.models import NormalizedCotWeek, Participant, RawParticipantPosition
from app.domain.cot.registry import instrument_by_slug
from app.domain.cot.validation import validate_cot_snapshot


def make_valid_week(
    report_date: date,
    *,
    slug: str = "gold",
) -> NormalizedCotWeek:
    positions = (
        RawParticipantPosition(Participant.PRODUCER_MERCHANT, 100, 200, 0),
        RawParticipantPosition(Participant.SWAP_DEALER, 100, 100, 50),
        RawParticipantPosition(Participant.MANAGED_MONEY, 200, 100, 50),
        RawParticipantPosition(Participant.OTHER_REPORTABLES, 100, 100, 50),
        RawParticipantPosition(Participant.NONREPORTABLES, 350, 350, 0),
    )
    return NormalizedCotWeek(
        source_dataset_id="72hh-3qpy",
        source_row_id=f"{slug}-{report_date.isoformat()}",
        source_fingerprint=f"fingerprint-{slug}-{report_date.isoformat()}",
        instrument_slug=slug,
        report_date=report_date,
        open_interest=1000,
        reported_long_total=650,
        reported_short_total=650,
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
    week = make_valid_week(date(2026, 9, 8))

    result = validate_cot_snapshot((week,), (definition_for(week),), ())

    assert result.valid is True
    assert result.reason_codes == ()
    assert result.week_count == 1


def test_validation_rejects_duplicate_instrument_week():
    week = make_valid_week(date(2026, 9, 8))
    duplicated = (week, week)

    result = validate_cot_snapshot(duplicated, (definition_for(week),), ())

    assert result.valid is False
    assert "duplicate_instrument_report_date" in result.reason_codes


def test_validation_rejects_reportable_reconciliation_failure():
    valid_week = make_valid_week(date(2026, 9, 8))
    broken = replace_position(valid_week, Participant.MANAGED_MONEY, long_delta=1)

    result = validate_cot_snapshot((broken,), (definition_for(broken),), ())

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

    result = validate_cot_snapshot(snapshot[1:], (definition_for(snapshot[0]),), existing)

    assert result.valid is False
    assert "source_history_truncated" in result.reason_codes


def test_validation_requires_every_family_instrument_at_the_common_latest_date():
    gold = make_valid_week(date(2026, 9, 8), slug="gold")
    silver = make_valid_week(date(2026, 9, 1), slug="silver")

    result = validate_cot_snapshot(
        (gold, silver),
        (instrument_by_slug("gold"), instrument_by_slug("silver")),
        (),
    )

    assert result.valid is False
    assert "incomplete_latest_family_coverage" in result.reason_codes


def test_validation_rejects_wrong_official_dataset_identity():
    week = replace(
        make_valid_week(date(2026, 9, 8)),
        source_dataset_id="gpe5-46if",
    )

    result = validate_cot_snapshot((week,), (definition_for(week),), ())

    assert result.valid is False
    assert "source_dataset_mismatch" in result.reason_codes
