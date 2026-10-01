"""Cache-only bulk reads never reach a price provider (#451)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from app.services.bulk_data_fetcher import BulkDataFetcher
from app.services.price_cache_service import PriceCacheService

EXPECTED = date(2026, 9, 29)


def _frame(bars: int, last: date) -> pd.DataFrame:
    index = pd.bdate_range(end=last, periods=bars)
    closes = [100.0 + i for i in range(bars)]
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * bars,
        },
        index=index,
    )
    frame.index.name = "Date"
    return frame


class _EmptyRedis:
    """Every read misses, every write is dropped."""

    def setex(self, *_args):
        return None

    def get(self, _key):
        return None

    def pipeline(self):
        class Pipeline:
            def __init__(self):
                self.reads = 0

            def get(self, _key):
                self.reads += 1
                return self

            def setex(self, *_args):
                return self

            def execute(self, raise_on_error=True):
                return [None] * self.reads

        return Pipeline()


@pytest.fixture
def provider_calls(monkeypatch):
    calls: list[list[str]] = []

    def record(self, symbols, *args, **kwargs):
        calls.append(list(symbols))
        return {}

    monkeypatch.setattr(BulkDataFetcher, "fetch_prices_in_batches", record)
    return calls


def _service(db_frames: dict[str, pd.DataFrame], *, with_redis: bool) -> PriceCacheService:
    """Database tier holds ``db_frames`` and applies the loader's minimum_rows rule."""
    service = PriceCacheService(
        redis_client=_EmptyRedis() if with_redis else None,
        session_factory=lambda: None,
    )

    def read_db(symbols, period, *, minimum_rows=50):
        results = {}
        for symbol in symbols:
            frame = db_frames.get(symbol)
            if frame is None or len(frame) < minimum_rows:
                results[symbol] = (None, None)
            else:
                results[symbol] = (frame, frame.index[-1].date())
        return results

    service._get_many_from_database = read_db  # type: ignore[assignment]
    service._get_expected_data_date = lambda market=None: EXPECTED  # type: ignore[assignment]
    service._active_market_by_symbol = (  # type: ignore[assignment]
        lambda symbols: {symbol: "US" for symbol in symbols}
    )
    return service


@pytest.mark.parametrize("with_redis", [True, False])
def test_cache_only_serves_a_new_listing_from_the_database(provider_calls, with_redis):
    young = _frame(10, EXPECTED)

    result = _service({"NEWCO": young}, with_redis=with_redis).get_many(
        ["NEWCO"], cache_only=True
    )

    assert provider_calls == []
    pd.testing.assert_frame_equal(result["NEWCO"], young)


@pytest.mark.parametrize("with_redis", [True, False])
def test_cache_only_serves_a_stale_frame_instead_of_fetching(provider_calls, with_redis):
    stale = _frame(300, EXPECTED - timedelta(days=7))

    result = _service({"OLDCO": stale}, with_redis=with_redis).get_many(
        ["OLDCO"], cache_only=True
    )

    assert provider_calls == []
    pd.testing.assert_frame_equal(result["OLDCO"], stale)


@pytest.mark.parametrize("with_redis", [True, False])
def test_cache_only_returns_none_when_the_database_has_nothing(provider_calls, with_redis):
    result = _service({}, with_redis=with_redis).get_many(["NODATA"], cache_only=True)

    assert provider_calls == []
    assert result["NODATA"] is None


def test_default_bulk_read_still_fetches_a_new_listing(provider_calls):
    # The populate paths (bootstrap, internal scans) keep the provider fallback.
    _service({"NEWCO": _frame(10, EXPECTED)}, with_redis=True).get_many(["NEWCO"])

    assert provider_calls == [["NEWCO"]]
