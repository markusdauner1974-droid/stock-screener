"""Regression tests for event-calendar evidence in bulk fundamentals ingestion.

The non-US weekly-reference producer fetches fundamentals through
``BulkDataFetcher._extract_fundamentals``. These tests guard that the
shared Yahoo calendar normalizer's observation lands in the persisted
payload (success-empty stays available, provider failure stays retryable)
so ``prepare_data_bulk``'s persisted-only event gate can pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from app.services.bulk_data_fetcher import BulkDataFetcher


def _ticker_with_calendar(earnings_dates) -> SimpleNamespace:
    return SimpleNamespace(
        fast_info=SimpleNamespace(
            market_cap=None, shares=None, last_price=None,
        ),
        earnings_dates=earnings_dates,
    )


class TestExtractFundamentalsCalendarEvidence:
    def test_future_earnings_rows_produce_observation_and_next_date(self):
        future = datetime.now(UTC) + pd.Timedelta(days=9)
        ticker = _ticker_with_calendar(
            pd.DataFrame({"Earnings Date": [future], "EPS Estimate": [1.25]}).set_index(
                "Earnings Date"
            )
        )

        result = BulkDataFetcher()._extract_fundamentals(ticker, {})

        assert result["next_earnings_date"] == future.date()
        assert result["event_calendar_as_of_date"] == datetime.now(UTC).date()

    def test_successful_empty_calendar_stays_observed_without_next_date(self):
        """Success with no upcoming earnings keeps availability via the stamp."""
        ticker = _ticker_with_calendar(pd.DataFrame())

        result = BulkDataFetcher()._extract_fundamentals(ticker, {})

        assert "event_calendar_as_of_date" in result
        assert result["event_calendar_as_of_date"] == datetime.now(UTC).date()
        # A null next date is dropped by the None-filter, which the persisted
        # gate treats identically to an explicit None: still available.
        assert "next_earnings_date" not in result

    def test_provider_failure_stamps_no_calendar_marker(self):
        class FailingCalendarTicker(SimpleNamespace):
            @property
            def earnings_dates(self):
                raise RuntimeError("calendar unavailable")

        result = BulkDataFetcher()._extract_fundamentals(
            FailingCalendarTicker(), {}
        )

        assert "event_calendar_as_of_date" not in result
        assert "next_earnings_date" not in result

    def test_none_ticker_still_extracts_without_calendar(self):
        result = BulkDataFetcher()._extract_fundamentals(None, {"marketCap": 42})

        assert result["market_cap"] == 42
        assert "event_calendar_as_of_date" not in result

    def test_extract_earnings_calendar_is_usable_in_isolation(self):
        future = datetime.now(UTC) + pd.Timedelta(days=11)
        ticker = _ticker_with_calendar(
            pd.DataFrame({"Earnings Date": [future]}).set_index("Earnings Date")
        )

        stamped = BulkDataFetcher()._extract_earnings_calendar(ticker, symbol="AAPL")

        assert stamped["next_earnings_date"] == future.date()
