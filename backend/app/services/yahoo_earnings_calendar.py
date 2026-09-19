"""Shared Yahoo earnings-calendar normalization.

Single owner for turning ``ticker.earnings_dates`` into the persisted
event-calendar evidence consumed by the scan pipeline's fail-closed
survivor gate. It preserves the distinction between:

- a successful lookup with no future earnings date (fresh observation
  stamp with ``next_earnings_date=None`` — the row stays evidence-complete),
  and
- a provider failure (no observation stamp — the row stays explicitly
  unavailable and scheduled producers retry on the next run).

Every producer that persists fundamentals (US snapshot hydration,
non-US bulk fundamentals ingestion, per-symbol snapshots) shares this
module so the observation semantics cannot drift, and the persisted
freshness window consumed by ``DataPreparationLayer._persisted_event_calendar``
is owned here as well.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# How long a persisted calendar observation stays usable by the scan
# pipeline's persisted-only event gate. Weekly producers must refresh at
# least this often; the window is intentionally wider than one week so a
# hydration run does not strand daily snapshots with stale evidence
# (age is measured against each snapshot's price as_of_date).
EVENT_CALENDAR_MAX_AGE_DAYS = 14
EVENT_CALENDAR_FUTURE_TOLERANCE_DAYS = 3


def normalize_yahoo_earnings_dates(
    earnings_dates: Any,
    *,
    symbol: str | None = None,
    limit: int = 4,
) -> tuple[list[date], bool]:
    """Normalize one ``ticker.earnings_dates`` lookup.

    Returns a sorted, de-duplicated date list and an availability flag.
    A successful empty response is ``([], True)``; provider failure is
    ``([], False)``.
    """
    try:
        # NOTE: ``DataFrame.empty`` is True whenever any axis is empty —
        # an all-index frame (no columns) reports empty even with rows.
        # Test row count explicitly so such frames are still normalized.
        if earnings_dates is None or len(earnings_dates) == 0:
            return [], True

        normalized = earnings_dates.reset_index()
        result: list[date] = []
        for row in normalized.head(limit).to_dict("records"):
            raw_value = (
                row.get("Earnings Date") or row.get("index") or row.get("Date")
            )
            if raw_value is None:
                continue
            try:
                timestamp = pd.Timestamp(raw_value)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping unparsable earnings date for %s: %r",
                    symbol,
                    raw_value,
                )
                continue
            if pd.isna(timestamp):
                continue
            result.append(timestamp.date())
        return sorted(set(result)), True
    except Exception as exc:
        logger.error("Error fetching earnings dates for %s: %s", symbol, exc)
        return [], False


def stamp_event_calendar_observation(
    upcoming_dates: list[date],
    available: bool,
    *,
    observed_at: date | None = None,
) -> dict[str, Any]:
    """Return persisted fundamentals keys for one calendar observation.

    Returns ``{}`` when the provider lookup failed so failed producers
    never stamp a marker, keeping the row explicitly unavailable for the
    fail-closed gate and eligible for retry. A successful observation
    stamps ``event_calendar_as_of_date`` (the freshness owner) and the
    first known-future ``next_earnings_date`` (or ``None`` when Yahoo
    lists no upcoming earnings).
    """
    if not available:
        return {}
    observation_date = observed_at or datetime.now(UTC).date()
    next_earnings_date = next(
        (value for value in upcoming_dates if value >= observation_date),
        None,
    )
    return {
        "event_calendar_as_of_date": observation_date,
        "next_earnings_date": next_earnings_date,
    }


def is_event_calendar_observation_fresh(
    observed_at: Any,
    *,
    reference_date: date | None = None,
) -> bool:
    """Return whether an observation timestamp satisfies the freshness gate.

    The consumer side (``_persisted_event_calendar``) and the producer
    completeness check share this rule so both sides age evidence out on
    the same schedule.
    """
    if observed_at is None:
        return False
    try:
        timestamp = pd.Timestamp(observed_at)
    except (TypeError, ValueError):
        return False
    if pd.isna(timestamp):
        return False
    reference = reference_date or datetime.now(UTC).date()
    age_days = (reference - timestamp.date()).days
    return (
        -EVENT_CALENDAR_FUTURE_TOLERANCE_DAYS
        <= age_days
        <= EVENT_CALENDAR_MAX_AGE_DAYS
    )


__all__ = [
    "EVENT_CALENDAR_FUTURE_TOLERANCE_DAYS",
    "EVENT_CALENDAR_MAX_AGE_DAYS",
    "is_event_calendar_observation_fresh",
    "normalize_yahoo_earnings_dates",
    "stamp_event_calendar_observation",
]
