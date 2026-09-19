"""Contract tests for the shared Yahoo earnings-calendar normalizer.

Guards the success-empty vs provider-failure distinction and the shared
freshness window consumed by the fail-closed survivor gate.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.services.yahoo_earnings_calendar import (
    EVENT_CALENDAR_FUTURE_TOLERANCE_DAYS,
    EVENT_CALENDAR_MAX_AGE_DAYS,
    is_event_calendar_observation_fresh,
    normalize_yahoo_earnings_dates,
    stamp_event_calendar_observation,
)


def _frame(values):
    return pd.DataFrame({"Earnings Date": values, "EPS Estimate": [1.0] * len(values)}).set_index(
        "Earnings Date"
    )


class TestNormalizeYahooEarningsDates:
    def test_successful_lookup_with_rows_returns_normalized_dates(self):
        first = datetime(2026, 9, 25, 20, 0)
        second = datetime(2026, 12, 18, 20, 0)
        frame = _frame([second, first])

        dates, available = normalize_yahoo_earnings_dates(frame, symbol="AAPL")

        assert dates == [date(2026, 9, 25), date(2026, 12, 18)]
        assert available is True

    def test_successful_empty_response_is_available_not_failure(self):
        dates, available = normalize_yahoo_earnings_dates(pd.DataFrame())

        assert dates == []
        assert available is True

    def test_none_frame_is_available_not_failure(self):
        dates, available = normalize_yahoo_earnings_dates(None)

        assert dates == []
        assert available is True

    def test_provider_failure_is_reported_as_unavailable(self):
        class ExplodingFrame:
            @property
            def empty(self):
                raise RuntimeError("provider outage")

        dates, available = normalize_yahoo_earnings_dates(ExplodingFrame(), symbol="AAPL")

        assert dates == []
        assert available is False

    def test_unparsable_rows_are_skipped_not_failures(self):
        frame = _frame(["not-a-date", datetime(2026, 10, 2, 16, 0)])

        dates, available = normalize_yahoo_earnings_dates(frame, symbol="AAPL")

        assert dates == [date(2026, 10, 2)]
        assert available is True

    def test_limit_caps_normalized_rows(self):
        values = [datetime(2026, 10, 1 + offset) for offset in range(6)]
        dates, _available = normalize_yahoo_earnings_dates(_frame(values), limit=3)

        assert len(dates) == 3


class TestStampEventCalendarObservation:
    def test_success_stamps_observation_and_next_date(self):
        stamped = stamp_event_calendar_observation(
            [date(2026, 9, 25), date(2026, 12, 18)],
            True,
            observed_at=date(2026, 9, 20),
        )

        assert stamped == {
            "event_calendar_as_of_date": date(2026, 9, 20),
            "next_earnings_date": date(2026, 9, 25),
        }

    def test_success_with_no_future_date_stamps_observation_with_null_date(self):
        stamped = stamp_event_calendar_observation(
            [date(2026, 1, 5)],
            True,
            observed_at=date(2026, 9, 20),
        )

        assert stamped["event_calendar_as_of_date"] == date(2026, 9, 20)
        assert stamped["next_earnings_date"] is None

    def test_failure_stamps_nothing(self):
        assert stamp_event_calendar_observation([], False) == {}

    def test_failure_with_dates_still_stamps_nothing(self):
        assert stamp_event_calendar_observation([date(2026, 9, 25)], False) == {}

    def test_default_observation_is_today_utc(self):
        before = datetime.now(UTC).date()
        stamped = stamp_event_calendar_observation([], True)
        after = datetime.now(UTC).date()

        assert stamped["event_calendar_as_of_date"] in {before, after}
        assert stamped["next_earnings_date"] is None


class TestObservationFreshness:
    def test_shared_window_is_wider_than_weekly_cadence(self):
        assert EVENT_CALENDAR_MAX_AGE_DAYS > 7
        assert EVENT_CALENDAR_FUTURE_TOLERANCE_DAYS >= 0

    def test_same_day_observation_is_fresh(self):
        today = date(2026, 9, 20)

        assert is_event_calendar_observation_fresh(today, reference_date=today) is True

    def test_observation_within_max_age_is_fresh(self):
        today = date(2026, 9, 20)

        assert (
            is_event_calendar_observation_fresh(
                today - timedelta(days=EVENT_CALENDAR_MAX_AGE_DAYS),
                reference_date=today,
            )
            is True
        )

    def test_observation_one_day_past_max_age_is_stale(self):
        today = date(2026, 9, 20)

        assert (
            is_event_calendar_observation_fresh(
                today - timedelta(days=EVENT_CALENDAR_MAX_AGE_DAYS + 1),
                reference_date=today,
            )
            is False
        )

    def test_observation_beyond_future_tolerance_is_not_fresh(self):
        today = date(2026, 9, 20)

        assert (
            is_event_calendar_observation_fresh(
                today + timedelta(days=EVENT_CALENDAR_FUTURE_TOLERANCE_DAYS + 1),
                reference_date=today,
            )
            is False
        )

    def test_future_observation_within_tolerance_is_fresh(self):
        today = date(2026, 9, 20)

        assert (
            is_event_calendar_observation_fresh(
                today + timedelta(days=EVENT_CALENDAR_FUTURE_TOLERANCE_DAYS),
                reference_date=today,
            )
            is True
        )

    @pytest.mark.parametrize(
        "raw",
        [None, "", "not-a-date", float("nan")],
        ids=["none", "empty", "garbage", "nan"],
    )
    def test_unusable_observation_is_stale(self, raw):
        assert is_event_calendar_observation_fresh(raw) is False

    def test_accepts_iso_string_observation(self):
        today = date(2026, 9, 20)

        assert (
            is_event_calendar_observation_fresh("2026-09-18", reference_date=today)
            is True
        )
