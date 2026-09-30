from __future__ import annotations

import pickle
from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.services.price_cache_service import PERIOD_DAYS, PriceCacheService


def _redis_hit_service(frame: pd.DataFrame) -> PriceCacheService:
    class FakePipeline:
        def get(self, _key):
            return self

        def execute(self, raise_on_error=True):
            return [pickle.dumps(frame), None]

    class FakeRedis:
        def pipeline(self):
            return FakePipeline()

    service = PriceCacheService(redis_client=FakeRedis(), session_factory=lambda: None)
    last_date = frame.index[-1].date()
    service._get_expected_data_date = lambda market=None: last_date  # type: ignore[assignment]

    def fail_fallback(symbols, **_kwargs):
        raise AssertionError(f"Redis hit must not fall back to the database: {symbols}")

    service._resolve_bulk_fallback = fail_fallback  # type: ignore[assignment]
    return service


def _five_year_frame(tz: str | None) -> pd.DataFrame:
    # 1250 business days ~ 1750 calendar days: inside the 5y Redis window.
    index = pd.bdate_range(end=datetime.now().date(), periods=1250, tz=tz)
    closes = [100.0 + i for i in range(len(index))]
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(index),
        },
        index=index,
    )
    frame.index.name = "Date"
    return frame


@pytest.mark.parametrize("tz", [None, "America/New_York"])
@pytest.mark.parametrize("period", ["1y", "2y"])
def test_get_many_trims_redis_hit_to_the_window_the_db_tier_returns(period, tz):
    frame = _five_year_frame(tz)
    start_date = datetime.now().date() - timedelta(days=PERIOD_DAYS[period])
    expected = frame[[bar.date() >= start_date for bar in frame.index]]

    result = _redis_hit_service(frame).get_many(["AAPL"], period=period)["AAPL"]

    assert len(expected) < len(frame)
    pd.testing.assert_frame_equal(result, expected)


def test_get_many_leaves_a_redis_frame_already_inside_the_window_alone():
    frame = _five_year_frame(None).iloc[-250:]

    result = _redis_hit_service(frame).get_many(["AAPL"], period="2y")["AAPL"]

    pd.testing.assert_frame_equal(result, frame)


class _DictRedis:
    def __init__(self):
        self.store: dict = {}

    def setex(self, key, _ttl, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def pipeline(self):
        redis = self

        class Pipeline:
            def __init__(self):
                self.commands = []

            def get(self, key):
                self.commands.append(lambda: redis.store.get(key))
                return self

            def setex(self, key, ttl, value):
                self.commands.append(lambda: redis.setex(key, ttl, value))
                return self

            def execute(self, raise_on_error=True):
                return [command() for command in self.commands]

        return Pipeline()


def _db_backed_service(db_frame: pd.DataFrame) -> tuple[PriceCacheService, list[str]]:
    """Service over an in-memory Redis whose database tier holds ``db_frame``."""
    service = PriceCacheService(redis_client=_DictRedis(), session_factory=lambda: None)
    last_date = db_frame.index[-1].date()
    db_reads: list[str] = []

    def read_db(symbols, period, **_kwargs):
        db_reads.append(period)
        frame = PriceCacheService._trim_to_period(db_frame, period)
        return {symbol: (frame, last_date) for symbol in symbols}

    service._get_expected_data_date = lambda market=None: last_date  # type: ignore[assignment]
    service._active_market_by_symbol = lambda symbols: {}  # type: ignore[assignment]
    service._get_many_from_database = read_db  # type: ignore[assignment]
    return service, db_reads


def test_five_year_request_is_not_served_a_frame_cut_for_a_two_year_request():
    db_frame = _five_year_frame(None)
    service, db_reads = _db_backed_service(db_frame)

    two_year = service.get_many(["AAPL"], period="2y")["AAPL"]
    five_year = service.get_many(["AAPL"], period="5y")["AAPL"]

    assert db_reads == ["2y", "5y"]
    assert len(two_year) < len(five_year)
    pd.testing.assert_frame_equal(five_year, db_frame)


def test_frame_cut_for_five_years_serves_later_requests_from_redis():
    db_frame = _five_year_frame(None)
    service, db_reads = _db_backed_service(db_frame)
    service.get_many(["AAPL"], period="5y")

    five_year = service.get_many(["AAPL"], period="5y")["AAPL"]
    two_year = service.get_many(["AAPL"], period="2y")["AAPL"]

    assert db_reads == ["5y"]
    pd.testing.assert_frame_equal(five_year, db_frame)
    pd.testing.assert_frame_equal(
        two_year, PriceCacheService._trim_to_period(db_frame, "2y")
    )


def test_young_stock_cut_for_five_years_is_served_from_redis():
    # All the history there is: 250 bars, read with a 5y window.
    db_frame = _five_year_frame(None).iloc[-250:]
    service, db_reads = _db_backed_service(db_frame)
    service.get_many(["AAPL"], period="5y")

    result = service.get_many(["AAPL"], period="5y")["AAPL"]

    assert db_reads == ["5y"]
    pd.testing.assert_frame_equal(result, db_frame)


def _store_provider_frame(service: PriceCacheService, writer: str, frame: pd.DataFrame, period: str) -> None:
    if writer == "single_fetch":
        service._fetch_direct_historical_data = lambda symbol, period: frame  # type: ignore[assignment]
        service._store_in_database = lambda symbol, data: None  # type: ignore[assignment]
        service._fetch_full_and_cache("AAPL", period)
    elif writer == "batch":
        service.store_batch_in_cache({"AAPL": frame}, also_store_db=False, period=period)
    else:
        service._store_batch_in_cache_for_market(
            {"AAPL": frame}, also_store_db=False, market=None, period=period
        )


@pytest.mark.parametrize("writer", ["single_fetch", "batch", "fallback_batch"])
def test_two_year_request_is_not_served_a_one_year_provider_frame(writer):
    db_frame = _five_year_frame(None)
    service, db_reads = _db_backed_service(db_frame)
    one_year = PriceCacheService._trim_to_period(db_frame, "1y")
    assert len(one_year) >= 200

    _store_provider_frame(service, writer, one_year, "1y")
    result = service.get_many(["AAPL"], period="2y")["AAPL"]

    assert db_reads == ["2y"]
    pd.testing.assert_frame_equal(result, PriceCacheService._trim_to_period(db_frame, "2y"))


@pytest.mark.parametrize("writer", ["single_fetch", "batch", "fallback_batch"])
def test_provider_frame_serves_requests_up_to_its_own_period(writer):
    db_frame = _five_year_frame(None)
    service, db_reads = _db_backed_service(db_frame)
    one_year = PriceCacheService._trim_to_period(db_frame, "1y")

    _store_provider_frame(service, writer, one_year, "1y")
    result = service.get_many(["AAPL"], period="1y")["AAPL"]

    assert db_reads == []
    pd.testing.assert_frame_equal(result, one_year)


@pytest.mark.parametrize("writer", ["single_fetch", "batch", "fallback_batch"])
def test_five_year_provider_fetch_does_not_claim_five_years(writer):
    # A provider can return less than it was asked for; only a database read
    # vouches for a window longer than the 2y default.
    db_frame = _five_year_frame(None)
    service, db_reads = _db_backed_service(db_frame)
    short = PriceCacheService._trim_to_period(db_frame, "2y")

    _store_provider_frame(service, writer, short, "5y")
    service.get_many(["AAPL"], period="5y")

    assert db_reads == ["5y"]


@pytest.mark.parametrize("writer", ["store_in_cache", "store_batch_in_cache"])
def test_restoring_a_cache_read_frame_does_not_keep_its_five_year_claim(writer):
    db_frame = _five_year_frame(None)
    service, db_reads = _db_backed_service(db_frame)
    service.get_many(["AAPL"], period="5y")
    one_year = service.get_many(["AAPL"], period="1y")["AAPL"]

    if writer == "store_in_cache":
        service.store_in_cache("AAPL", one_year, also_store_db=False)
    else:
        service.store_batch_in_cache({"AAPL": one_year}, also_store_db=False)
    service.get_many(["AAPL"], period="5y")

    assert db_reads == ["5y", "5y"]
