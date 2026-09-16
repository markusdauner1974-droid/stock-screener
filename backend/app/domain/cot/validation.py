from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Any

from app.domain.cot.models import (
    CotInstrumentDefinition,
    NormalizedCotWeek,
    Participant,
    ReportFamily,
)
from app.domain.cot.registry import participants_for


EXPECTED_DATASET_BY_FAMILY = {
    ReportFamily.DISAGGREGATED_FUTURES_ONLY: "72hh-3qpy",
    ReportFamily.TFF_FUTURES_ONLY: "gpe5-46if",
}


@dataclass(frozen=True)
class CotValidationResult:
    valid: bool
    reason_codes: tuple[str, ...]
    instrument_count: int
    week_count: int
    latest_report_dates: Mapping[str, date]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "latest_report_dates",
            MappingProxyType(dict(self.latest_report_dates)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason_codes": list(self.reason_codes),
            "instrument_count": self.instrument_count,
            "week_count": self.week_count,
            "latest_report_dates": {
                family: value.isoformat()
                for family, value in self.latest_report_dates.items()
            },
        }


def validate_cot_snapshot(
    weeks: Sequence[NormalizedCotWeek],
    instruments: Sequence[CotInstrumentDefinition],
    existing_keys: Iterable[tuple[str, date]],
) -> CotValidationResult:
    snapshot = tuple(weeks)
    definitions = tuple(instruments)
    definitions_by_slug = {definition.slug: definition for definition in definitions}
    reasons: list[str] = []

    def reject(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    if len(definitions_by_slug) != len(definitions):
        reject("duplicate_registry_instrument")

    observed_keys: set[tuple[str, date]] = set()
    observed_source_rows: set[tuple[str, str]] = set()
    weeks_by_slug: dict[str, list[NormalizedCotWeek]] = defaultdict(list)
    for week in snapshot:
        key = (week.instrument_slug, week.report_date)
        if key in observed_keys:
            reject("duplicate_instrument_report_date")
        observed_keys.add(key)

        source_key = (week.source_dataset_id, week.source_row_id)
        if source_key in observed_source_rows:
            reject("duplicate_source_row_id")
        observed_source_rows.add(source_key)

        definition = definitions_by_slug.get(week.instrument_slug)
        if definition is None:
            reject("unknown_instrument")
            continue
        weeks_by_slug[week.instrument_slug].append(week)
        if (
            week.source_dataset_id
            != EXPECTED_DATASET_BY_FAMILY[definition.report_family]
        ):
            reject("source_dataset_mismatch")

        expected_participants = participants_for(definition.report_family)
        actual_participants = tuple(
            position.participant for position in week.positions
        )
        if (
            len(actual_participants) != len(set(actual_participants))
            or set(actual_participants) != set(expected_participants)
        ):
            reject("participant_structure_mismatch")
            continue

        reportable_positions = tuple(
            position
            for position in week.positions
            if position.participant is not Participant.NONREPORTABLES
        )
        computed_reported_long = sum(
            position.long + position.spreading
            for position in reportable_positions
        )
        computed_reported_short = sum(
            position.short + position.spreading
            for position in reportable_positions
        )
        if computed_reported_long != week.reported_long_total:
            reject("reported_long_reconciliation_failed")
        if computed_reported_short != week.reported_short_total:
            reject("reported_short_reconciliation_failed")

        nonreportable = next(
            position
            for position in week.positions
            if position.participant is Participant.NONREPORTABLES
        )
        expected_nonreportable_long = week.open_interest - week.reported_long_total
        expected_nonreportable_short = week.open_interest - week.reported_short_total
        if (
            expected_nonreportable_long < 0
            or nonreportable.long != expected_nonreportable_long
        ):
            reject("nonreportable_long_reconciliation_failed")
        if (
            expected_nonreportable_short < 0
            or nonreportable.short != expected_nonreportable_short
        ):
            reject("nonreportable_short_reconciliation_failed")

    if not set(existing_keys).issubset(observed_keys):
        reject("source_history_truncated")

    latest_report_dates: dict[str, date] = {}
    definitions_by_family: dict[
        ReportFamily, list[CotInstrumentDefinition]
    ] = defaultdict(list)
    for definition in definitions:
        definitions_by_family[definition.report_family].append(definition)

    for family, family_definitions in definitions_by_family.items():
        latest_by_slug: dict[str, date] = {}
        for definition in family_definitions:
            instrument_weeks = weeks_by_slug.get(definition.slug, ())
            if not instrument_weeks:
                reject("missing_instrument_history")
                continue
            latest_by_slug[definition.slug] = max(
                week.report_date for week in instrument_weeks
            )
        common_latest_dates = set(latest_by_slug.values())
        if len(latest_by_slug) != len(family_definitions) or len(common_latest_dates) != 1:
            reject("incomplete_latest_family_coverage")
            continue
        latest_report_dates[family.value] = next(iter(common_latest_dates))

    return CotValidationResult(
        valid=not reasons,
        reason_codes=tuple(reasons),
        instrument_count=len(weeks_by_slug),
        week_count=len(snapshot),
        latest_report_dates=latest_report_dates,
    )
