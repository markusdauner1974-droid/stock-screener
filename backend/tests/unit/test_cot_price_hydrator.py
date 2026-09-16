from __future__ import annotations

import pandas as pd

from app.domain.cot.registry import COT_INSTRUMENTS, instrument_by_slug
from app.services.cot_price_hydrator import CotPriceHydrator


class FakePriceCache:
    def __init__(self, responses=None, failures=()):
        self.responses = dict(responses or {})
        self.failures = set(failures)
        self.calls = []

    def get_historical_data(self, symbol, *, period, market):
        self.calls.append((symbol, period, market))
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

    result = CotPriceHydrator(cache).hydrate(COT_INSTRUMENTS)

    assert all(period == "5y" and market == "US" for _, period, market in cache.calls)
    assert len(cache.calls) == 30
    assert all(symbol is not None for symbol, _, _ in cache.calls)
    assert result.attempted_count == 30
    assert result.unavailable_count == 1


def test_hydrator_records_symbol_failure_without_raising():
    cache = FakePriceCache(failures={"GC=F"})

    result = CotPriceHydrator(cache).hydrate((instrument_by_slug("gold"),))

    assert result.unavailable_count == 1
    assert result.items[0].error_code == "RuntimeError"


def test_hydrator_accepts_short_lumber_history_as_partial():
    cache = FakePriceCache(responses={"LBR=F": frame("2025-09-01", 300)})

    result = CotPriceHydrator(cache).hydrate((instrument_by_slug("lumber"),))

    assert result.partial_count == 1
    assert result.unavailable_count == 0
