from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from datetime import date

from app.domain.cot.models import (
    AlignedPrice,
    DerivedCotWeek,
    DerivedParticipantPosition,
    NormalizedCotWeek,
    Participant,
)


PERCENTILE_WINDOW = 156


def midrank_percentile(window: Sequence[int], current: int) -> float:
    if not window:
        raise ValueError("percentile window cannot be empty")
    below = sum(value < current for value in window)
    equal = sum(value == current for value in window)
    return 100.0 * (below + 0.5 * equal) / len(window)


def rolling_net_percentiles(
    values: Sequence[int | None],
    *,
    window: int = PERCENTILE_WINDOW,
) -> tuple[float | None, ...]:
    if window <= 0:
        raise ValueError("percentile window must be positive")
    usable: deque[int] = deque(maxlen=window)
    output: list[float | None] = []
    for value in values:
        if value is not None:
            usable.append(value)
        output.append(
            midrank_percentile(tuple(usable), value)
            if value is not None and len(usable) == window
            else None
        )
    return tuple(output)


def derive_position_series(
    weeks: Sequence[NormalizedCotWeek],
) -> tuple[DerivedCotWeek, ...]:
    ordered = tuple(sorted(weeks, key=lambda week: week.report_date))
    instrument_slugs = {week.instrument_slug for week in ordered}
    if len(instrument_slugs) > 1:
        raise ValueError("derive_position_series accepts one instrument at a time")

    positions_by_week = [
        {position.participant: position for position in week.positions}
        for week in ordered
    ]
    participants = tuple(
        dict.fromkeys(
            position.participant
            for week in ordered
            for position in week.positions
        )
    )
    percentiles = {
        participant: rolling_net_percentiles(
            tuple(
                (
                    position.long - position.short
                    if (position := positions.get(participant)) is not None
                    else None
                )
                for positions in positions_by_week
            )
        )
        for participant in participants
    }

    previous: dict[Participant, tuple[int, int, int]] = {}
    derived_weeks: list[DerivedCotWeek] = []
    for index, week in enumerate(ordered):
        derived_positions: list[DerivedParticipantPosition] = []
        for position in week.positions:
            net = position.long - position.short
            prior = previous.get(position.participant)
            percentile = percentiles[position.participant][index]
            derived_positions.append(
                DerivedParticipantPosition(
                    participant=position.participant,
                    long=position.long,
                    short=position.short,
                    spreading=position.spreading,
                    net=net,
                    delta_long=(position.long - prior[0]) if prior is not None else None,
                    delta_short=(position.short - prior[1]) if prior is not None else None,
                    delta_net=(net - prior[2]) if prior is not None else None,
                    net_pct_open_interest=(
                        100.0 * net / week.open_interest
                        if week.open_interest > 0
                        else None
                    ),
                    percentile_3y=percentile,
                    percentile_status=(
                        "available" if percentile is not None else "insufficient_history"
                    ),
                )
            )
            previous[position.participant] = (position.long, position.short, net)
        derived_weeks.append(
            DerivedCotWeek(
                source_dataset_id=week.source_dataset_id,
                source_row_id=week.source_row_id,
                source_fingerprint=week.source_fingerprint,
                instrument_slug=week.instrument_slug,
                report_date=week.report_date,
                open_interest=week.open_interest,
                positions=tuple(derived_positions),
            )
        )
    return tuple(derived_weeks)


def derive_all_instrument_series(
    weeks: Sequence[NormalizedCotWeek],
) -> tuple[DerivedCotWeek, ...]:
    grouped: dict[str, list[NormalizedCotWeek]] = defaultdict(list)
    for week in weeks:
        grouped[week.instrument_slug].append(week)
    derived = [
        week
        for instrument_weeks in grouped.values()
        for week in derive_position_series(instrument_weeks)
    ]
    return tuple(sorted(derived, key=lambda week: (week.report_date, week.instrument_slug)))


def align_prices_to_report_dates(
    report_dates: Sequence[date],
    closes: Mapping[date, float],
) -> tuple[AlignedPrice, ...]:
    ordered_reports = tuple(sorted(report_dates))
    ordered_closes = tuple(sorted(closes.items()))
    price_index = 0
    latest_price_date: date | None = None
    latest_close: float | None = None
    previous_aligned_close: float | None = None
    aligned: list[AlignedPrice] = []

    for report_date in ordered_reports:
        while (
            price_index < len(ordered_closes)
            and ordered_closes[price_index][0] <= report_date
        ):
            latest_price_date, latest_close = ordered_closes[price_index]
            price_index += 1
        weekly_change_pct = (
            100.0 * (latest_close - previous_aligned_close) / previous_aligned_close
            if latest_close is not None
            and previous_aligned_close is not None
            and previous_aligned_close != 0
            else None
        )
        aligned.append(
            AlignedPrice(
                report_date=report_date,
                price_date=latest_price_date,
                close=latest_close,
                weekly_change_pct=weekly_change_pct,
            )
        )
        previous_aligned_close = latest_close

    return tuple(aligned)
