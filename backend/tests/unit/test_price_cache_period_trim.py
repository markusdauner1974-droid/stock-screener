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


def test_get_many_returns_full_redis_frame_for_five_year_requests():
    frame = _five_year_frame(None)

    result = _redis_hit_service(frame).get_many(["AAPL"], period="5y")["AAPL"]

    pd.testing.assert_frame_equal(result, frame)


def test_get_many_leaves_a_redis_frame_already_inside_the_window_alone():
    frame = _five_year_frame(None).iloc[-250:]

    result = _redis_hit_service(frame).get_many(["AAPL"], period="2y")["AAPL"]

    pd.testing.assert_frame_equal(result, frame)
