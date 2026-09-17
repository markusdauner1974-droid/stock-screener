from __future__ import annotations

from datetime import date

import pandas as pd
from app.domain.cot.registry import COT_INSTRUMENTS, instrument_by_slug
from app.services.cot_price_hydrator import CotPriceHydrator


class FakePriceCache:
    def __init__(self, responses=None, failures=()):
        self.responses = dict(responses or {})
        self.failures = set(failures)
        self.calls = []

    def get_historical_data(
        self, symbol, *, period, market, force_refresh=False
    ):
        self.calls.append((symbol, period, market, force_refresh))
        if symbol in self.failures:
            raise RuntimeError("provider unavailable")
        return self.responses.get(symbol)


def frame(start: str, periods: int, frequency: str = "D") -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq=frequency)
    return pd.DataFrame({"Close": range(periods)}, index=index)


def test_hydrator_requests_five_years_and_never_requests_canola():
    cache = FakePriceCache(
        responses={definition.price.yahoo_symbol: frame("2021-09-01", 1827)
                   for definition in COT_INSTRUMENTS
                   if definition.price.yahoo_symbol is not None}
    )

    result = CotPriceHydrator(cache).hydrate(
        COT_INSTRUMENTS,
        report_date=date(2026, 9, 1),
    )

    assert all(
        period == "5y" and market == "US" and not force_refresh
        for _, period, market, force_refresh in cache.calls
    )
    assert len(cache.calls) == 30
    assert all(symbol is not None for symbol, _, _, _ in cache.calls)
    assert result.attempted_count == 30
    assert result.unavailable_count == 1


def test_hydrator_records_symbol_failure_without_raising():
    cache = FakePriceCache(failures={"GC=F"})

    result = CotPriceHydrator(cache).hydrate(
        (instrument_by_slug("gold"),),
        report_date=date(2026, 9, 1),
    )

    assert result.unavailable_count == 1
    assert result.items[0].error_code == "RuntimeError"


def test_hydrator_accepts_short_lumber_history_as_partial():
    cache = FakePriceCache(responses={"LBR=F": frame("2025-09-01", 300)})

    result = CotPriceHydrator(cache).hydrate(
        (instrument_by_slug("lumber"),),
        report_date=date(2026, 9, 1),
    )

    assert result.partial_count == 1
    assert result.unavailable_count == 0
    assert cache.calls == [
        ("LBR=F", "5y", "US", False),
        ("LBR=F", "5y", "US", True),
    ]


def test_hydrator_force_refills_a_fresh_but_short_cache():
    partial = frame("2025-09-01", 300)
    complete = frame("2021-09-01", 1827)

    class ExpandingPriceCache:
        def __init__(self):
            self.calls = []

        def get_historical_data(
            self, symbol, *, period, market, force_refresh=False
        ):
            self.calls.append((symbol, period, market, force_refresh))
            return complete if force_refresh else partial

    cache = ExpandingPriceCache()

    result = CotPriceHydrator(cache).hydrate(
        (instrument_by_slug("gold"),),
        report_date=date(2026, 9, 1),
    )

    assert result.available_count == 1
    assert result.partial_count == 0
    assert cache.calls == [
        ("GC=F", "5y", "US", False),
        ("GC=F", "5y", "US", True),
    ]


def test_hydrator_does_not_report_complete_when_latest_price_is_stale():
    stale = frame("2020-09-01", 1827)
    cache = FakePriceCache(responses={"GC=F": stale})

    result = CotPriceHydrator(cache).hydrate(
        (instrument_by_slug("gold"),),
        report_date=date(2026, 9, 8),
    )

    assert result.available_count == 0
    assert result.partial_count == 1
    assert result.items[0].error_code == "stale_price_history"
    assert cache.calls == [
        ("GC=F", "5y", "US", False),
        ("GC=F", "5y", "US", True),
    ]
