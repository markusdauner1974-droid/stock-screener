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
from app.domain.cot.registry import dataset_for_family, participants_for

MINIMUM_INITIAL_HISTORY_WEEKS = 156
_TFF_REPORTED_TOTAL_TOLERANCE = 3
_TFF_NONREPORTABLE_TOLERANCE = 1


@dataclass(frozen=True)
class CotValidationResult:
    valid: bool
    reason_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
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
            "warning_codes": list(self.warning_codes),
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
    expected_dataset_row_counts: Mapping[str, int],
) -> CotValidationResult:
    snapshot = tuple(weeks)
    definitions = tuple(instruments)
    definitions_by_slug = {definition.slug: definition for definition in definitions}
    persisted_keys = set(existing_keys)
    reasons: list[str] = []
    warnings: list[str] = []

    def reject(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    def reconcile(
        actual: int,
        expected: int,
        *,
        tolerance: int,
        code: str,
    ) -> None:
        if actual == expected:
            return
        tolerated = abs(actual - expected) <= tolerance
        target = warnings if tolerated else reasons
        result = f"{code}_{'tolerated' if tolerated else 'failed'}"
        if result not in target:
            target.append(result)

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
            != dataset_for_family(definition.report_family).dataset_id.value
        ):
            reject("source_dataset_mismatch")

        expected_participants = participants_for(definition.report_family)
        actual_participants = tuple(position.participant for position in week.positions)
        if len(actual_participants) != len(set(actual_participants)) or set(
            actual_participants
        ) != set(expected_participants):
            reject("participant_structure_mismatch")
            continue

        reportable_positions = tuple(
            position
            for position in week.positions
            if position.participant is not Participant.NONREPORTABLES
        )
        computed_reported_long = sum(
            position.long + position.spreading for position in reportable_positions
        )
        computed_reported_short = sum(
            position.short + position.spreading for position in reportable_positions
        )
        is_tff = definition.report_family is ReportFamily.TFF_FUTURES_ONLY
        reconcile(
            computed_reported_long,
            week.reported_long_total,
            tolerance=_TFF_REPORTED_TOTAL_TOLERANCE if is_tff else 0,
            code="reported_long_reconciliation",
        )
        reconcile(
            computed_reported_short,
            week.reported_short_total,
            tolerance=_TFF_REPORTED_TOTAL_TOLERANCE if is_tff else 0,
            code="reported_short_reconciliation",
        )

        nonreportable = next(
            position
            for position in week.positions
            if position.participant is Participant.NONREPORTABLES
        )
        expected_nonreportable_long = week.open_interest - week.reported_long_total
        expected_nonreportable_short = week.open_interest - week.reported_short_total
        if expected_nonreportable_long < 0:
            reject("nonreportable_long_reconciliation_failed")
        else:
            reconcile(
                nonreportable.long,
                expected_nonreportable_long,
                tolerance=_TFF_NONREPORTABLE_TOLERANCE if is_tff else 0,
                code="nonreportable_long_reconciliation",
            )
        if expected_nonreportable_short < 0:
            reject("nonreportable_short_reconciliation_failed")
        else:
            reconcile(
                nonreportable.short,
                expected_nonreportable_short,
                tolerance=_TFF_NONREPORTABLE_TOLERANCE if is_tff else 0,
                code="nonreportable_short_reconciliation",
            )

    if not persisted_keys.issubset(observed_keys):
        reject("source_history_truncated")

    expected_dataset_ids = {
        dataset_for_family(definition.report_family).dataset_id.value
        for definition in definitions
    }
    if set(expected_dataset_row_counts) != expected_dataset_ids:
        reject("source_coverage_baseline_mismatch")
    observed_dataset_row_counts: dict[str, int] = defaultdict(int)
    for week in snapshot:
        observed_dataset_row_counts[week.source_dataset_id] += 1
    if any(
        observed_dataset_row_counts[dataset_id] != expected_count
        for dataset_id, expected_count in expected_dataset_row_counts.items()
    ):
        reject("source_row_count_mismatch")

    persisted_slugs = {slug for slug, _report_date in persisted_keys}
    if any(
        definition.slug not in persisted_slugs
        and len(weeks_by_slug.get(definition.slug, ()))
        < MINIMUM_INITIAL_HISTORY_WEEKS
        for definition in definitions
    ):
        reject("insufficient_initial_history")

    latest_report_dates: dict[str, date] = {}
    definitions_by_family: dict[ReportFamily, list[CotInstrumentDefinition]] = (
        defaultdict(list)
    )
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
        if (
            len(latest_by_slug) != len(family_definitions)
            or len(common_latest_dates) != 1
        ):
            reject("incomplete_latest_family_coverage")
            continue
        latest_report_dates[family.value] = next(iter(common_latest_dates))

    if (
        len(latest_report_dates) == len(definitions_by_family)
        and len(set(latest_report_dates.values())) > 1
    ):
        reject("mixed_latest_report_dates")

    return CotValidationResult(
        valid=not reasons,
        reason_codes=tuple(reasons),
        warning_codes=tuple(warnings),
        instrument_count=len(weeks_by_slug),
        week_count=len(snapshot),
        latest_report_dates=latest_report_dates,
    )
