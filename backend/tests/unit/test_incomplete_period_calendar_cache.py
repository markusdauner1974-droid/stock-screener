"""``has_incomplete_last_period`` memoizes the weekly exchange schedule.

Every symbol in a scan asks about the same week, and building the schedule is
the dominant cost of the check (~5ms). These tests pin both halves of the
change: the schedule is built once per (exchange, week), and the cached answer
is the one the uncached lookup gives on every day of two years, holiday weeks
included.
"""

from __future__ import annotations

import pandas as pd
import pytest

import app.analysis.patterns.technicals as technicals
from app.analysis.patterns.technicals import has_incomplete_last_period


@pytest.fixture(autouse=True)
def _fresh_cache():
    technicals._last_scheduled_session.cache_clear()
    yield
    technicals._last_scheduled_session.cache_clear()


def _uncached_answer(last_ts: pd.Timestamp, exchange: str) -> bool:
    """The pre-cache logic: build the week's schedule on every call."""
    period = last_ts.to_period("W-FRI")
    schedule = technicals._get_exchange_calendar(exchange).schedule(
        start_date=period.start_time.normalize().date().isoformat(),
        end_date=period.end_time.normalize().date().isoformat(),
    )
    if schedule.empty:
        return last_ts.normalize() < period.end_time.normalize()
    expected = pd.DatetimeIndex(schedule.index).tz_localize(None).max().normalize()
    return last_ts.normalize() < expected


def _index_ending(day: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.bdate_range(end=day, periods=30)


def test_schedule_is_built_once_per_exchange_and_week(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []
    real_calendar = technicals._get_exchange_calendar

    class _CountingCalendar:
        def __init__(self, exchange: str) -> None:
            self._exchange = exchange
            self._calendar = real_calendar(exchange)

        def schedule(self, *, start_date: str, end_date: str):
            calls.append((self._exchange, start_date, end_date))
            return self._calendar.schedule(start_date=start_date, end_date=end_date)

    monkeypatch.setattr(technicals, "_get_exchange_calendar", _CountingCalendar)

    # Many "symbols" whose latest bar falls in the same week, on different days.
    for day in ("2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"):
        for _ in range(50):
            has_incomplete_last_period(_index_ending(pd.Timestamp(day)), rule="W-FRI")

    assert calls == [("NYSE", "2026-09-19", "2026-09-25")]

    # A different week or a different exchange is a separate entry.
    has_incomplete_last_period(_index_ending(pd.Timestamp("2026-09-30")), rule="W-FRI")
    has_incomplete_last_period(
        _index_ending(pd.Timestamp("2026-09-24")), rule="W-FRI", exchange="NASDAQ"
    )
    assert len(calls) == 3


@pytest.mark.parametrize("exchange", ["NYSE", "NASDAQ"])
def test_cached_answers_match_uncached_lookup_every_day(exchange: str) -> None:
    for day in pd.date_range("2024-01-01", "2025-12-31", freq="D"):
        index = pd.DatetimeIndex([day - pd.Timedelta(days=7), day])
        expected = _uncached_answer(day, exchange)
        # Twice: the first call fills the cache, the second reads it.
        assert has_incomplete_last_period(index, rule="W-FRI", exchange=exchange) is expected
        assert has_incomplete_last_period(index, rule="W-FRI", exchange=exchange) is expected


def test_holiday_shortened_week_is_complete_on_thursday() -> None:
    # Good Friday 2025-04-18: NYSE closed, so Thursday is the last session.
    thursday = pd.Timestamp("2025-04-17")
    assert has_incomplete_last_period(_index_ending(thursday), rule="W-FRI") is False
    wednesday = pd.Timestamp("2025-04-16")
    assert has_incomplete_last_period(_index_ending(wednesday), rule="W-FRI") is True
