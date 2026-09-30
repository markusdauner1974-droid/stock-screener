"""Data-only Redis cache payloads (issue #434): no pickle on the read path."""

from __future__ import annotations

import math
import pickle
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.services.cache.redis_codec import decode_dict, decode_frame, encode_dict, encode_frame

EXECUTED: list[str] = []


def _mark_executed(tag: str) -> str:
    EXECUTED.append(tag)
    return tag


class _Exploit:
    # Unpickling calls this module's function by name; pickling EXECUTED.append
    # instead would copy the list and hide the call.
    def __reduce__(self):
        return (_mark_executed, ("pwned",))


def test_exploit_payload_runs_code_when_unpickled():
    EXECUTED.clear()

    pickle.loads(pickle.dumps(_Exploit()))

    assert EXECUTED == ["pwned"]


def _ohlcv(tz: str | None) -> pd.DataFrame:
    index = pd.DatetimeIndex(
        pd.to_datetime(["2026-09-28", "2026-09-29", "2026-09-30"]), name="Date"
    )
    if tz is not None:
        index = index.tz_localize(tz)
    return pd.DataFrame(
        {
            "Open": [1.5, 2.5, 3.5],
            "High": [2.0, 3.0, 4.0],
            "Low": [1.0, 2.0, 3.0],
            "Close": [1.75, 2.75, 3.75],
            "Adj Close": [1.7, 2.7, 3.7],
            "Volume": np.array([10, 20, 30], dtype="int64"),
        },
        index=index,
    )


@pytest.mark.parametrize("tz", [None, "America/New_York", "Asia/Hong_Kong"])
def test_frame_round_trips_exactly(tz):
    frame = _ohlcv(tz)

    decoded = decode_frame(encode_frame(frame))

    pd.testing.assert_frame_equal(decoded, frame)
    assert str(decoded.index.tz) == str(frame.index.tz)


def test_frame_index_freq_round_trips():
    frame = _ohlcv("America/New_York")
    frame.index = pd.bdate_range(end="2026-09-30", periods=3, tz="America/New_York", name="Date")

    decoded = decode_frame(encode_frame(frame))

    pd.testing.assert_frame_equal(decoded, frame)  # checks freq too
    assert decoded.index.freq == frame.index.freq


def test_frame_attrs_round_trip():
    # The price cache records each frame's coverage window in attrs (#447).
    frame = _ohlcv(None)
    frame.attrs = {"coverage_days": 365}

    assert decode_frame(encode_frame(frame)).attrs == {"coverage_days": 365}


def test_decoded_frame_is_writable():
    decoded = decode_frame(encode_frame(_ohlcv(None)))

    decoded.loc[decoded.index[0], "Close"] = 9.0

    assert decoded["Close"].iloc[0] == 9.0


def test_object_numeric_column_is_stored_as_numbers():
    frame = _ohlcv(None)
    frame["Adj Close"] = pd.Series([1.7, None, 3.7], index=frame.index, dtype="object")

    decoded = decode_frame(encode_frame(frame))

    assert decoded["Adj Close"].dtype == np.float64
    assert math.isnan(decoded["Adj Close"].iloc[1])


def test_frame_encoder_rejects_what_it_cannot_round_trip():
    with pytest.raises(TypeError):
        encode_frame(pd.DataFrame({"Close": [1.0]}, index=["not-a-date"]))
    frame = _ohlcv(None)
    frame["Note"] = ["a", "b", "c"]
    with pytest.raises(TypeError):
        encode_frame(frame)


def test_dict_round_trips_dates_datetimes_and_nesting():
    payload = {
        "market_cap": 123.5,
        "shares": np.int64(42),
        "ratio": float("nan"),
        "sector": "Tech",
        "missing": None,
        "flag": True,
        "ipo_date": date(2020, 1, 2),
        "updated_at": datetime(2026, 9, 30, 20, 15, tzinfo=timezone.utc),
        "availability": {"eps": ["yahoo", "finviz"], "as_of": date(2026, 9, 30)},
    }

    decoded = decode_dict(encode_dict(payload))

    assert decoded["ipo_date"] == date(2020, 1, 2) and type(decoded["ipo_date"]) is date
    assert decoded["updated_at"] == payload["updated_at"]
    assert decoded["shares"] == 42 and type(decoded["shares"]) is int
    assert math.isnan(decoded["ratio"])
    assert decoded["availability"] == {"eps": ["yahoo", "finviz"], "as_of": date(2026, 9, 30)}
    assert {k: v for k, v in decoded.items() if k not in {"shares", "ratio"}} == {
        k: v for k, v in payload.items() if k not in {"shares", "ratio"}
    }


def test_dict_encoder_rejects_what_it_cannot_round_trip():
    with pytest.raises(TypeError):
        encode_dict({2024: 1.0})  # json would silently turn the key into "2024"
    with pytest.raises(TypeError):
        encode_dict({"when": {1, 2}})


@pytest.mark.parametrize("decode", [decode_frame, decode_dict])
def test_legacy_pickle_payload_is_a_miss_and_never_unpickled(decode):
    EXECUTED.clear()

    assert decode(pickle.dumps(_Exploit())) is None
    assert EXECUTED == []


def test_truncated_frame_payload_is_rejected():
    blob = encode_frame(_ohlcv(None))

    with pytest.raises(ValueError):
        decode_frame(blob[:-8])


# ── The cache services write the codec and never unpickle ─────────────


class _DictRedis:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value

    def pipeline(self):
        redis = self

        class _Pipeline:
            def __init__(self):
                self.calls = []

            def get(self, key):
                self.calls.append(("get", key, None))
                return self

            def setex(self, key, ttl, value):
                self.calls.append(("set", key, value))
                return self

            def execute(self, raise_on_error=True):
                results = []
                for op, key, value in self.calls:
                    if op == "set":
                        redis.values[key] = value
                        results.append(True)
                    else:
                        results.append(redis.values.get(key))
                return results

        return _Pipeline()


def _recent_ohlcv() -> pd.DataFrame:
    frame = _ohlcv(None)
    frame.index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=3, name="Date")
    return frame


def test_price_cache_writes_decodable_frames():
    from app.services.price_cache_service import PriceCacheService

    redis = _DictRedis()
    service = PriceCacheService(redis_client=redis, session_factory=lambda: None)
    frame = _recent_ohlcv()

    service._store_recent_in_redis("AAPL", frame, stamp_fetch_metadata=False)
    service.store_batch_in_cache({"MSFT": frame}, also_store_db=False)

    for key in ("price:US:AAPL:recent", "price:US:MSFT:recent"):
        pd.testing.assert_frame_equal(decode_frame(redis.values[key]), frame, check_freq=False)


def test_price_cache_bulk_read_treats_a_legacy_pickle_as_a_miss(monkeypatch):
    import app.services.bulk_data_fetcher as bulk_module
    import app.services.price_cache_service as module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    class _NoFetch:
        def fetch_prices_in_batches(self, symbols, **kwargs):
            return {symbol: {"has_error": True, "error": "stub"} for symbol in symbols}

    monkeypatch.setattr(bulk_module, "BulkDataFetcher", _NoFetch)
    EXECUTED.clear()
    redis = _DictRedis({"price:US:AAPL:recent": pickle.dumps(_Exploit())})
    monkeypatch.setattr(module, "get_bulk_redis_client", lambda: redis)
    service = module.PriceCacheService(redis_client=redis, session_factory=sessionmaker(bind=engine))

    result = service.get_many(["AAPL"], period="2y")

    assert result["AAPL"] is None
    assert EXECUTED == []


def test_fundamentals_cache_writes_decodable_dicts():
    from app.services.fundamentals_cache_service import FundamentalsCacheService

    redis = _DictRedis()
    service = FundamentalsCacheService(redis_client=redis, session_factory=lambda: None)
    payload = {"market_cap": 1.0, "ipo_date": date(2020, 1, 2)}

    service._store_in_redis("AAPL", payload)

    (value,) = redis.values.values()
    assert decode_dict(value) == payload


def test_fundamentals_reads_treat_a_legacy_pickle_as_a_miss(monkeypatch):
    from app.services.fundamentals_cache_service import FundamentalsCacheService

    EXECUTED.clear()
    redis = _DictRedis()
    service = FundamentalsCacheService(redis_client=redis, session_factory=lambda: None)
    redis.values[service._redis_data_key("AAPL")] = pickle.dumps(_Exploit())
    fetched = {"market_cap": 2.0}
    monkeypatch.setattr(service, "_get_from_database", lambda symbol: (None, None))
    monkeypatch.setattr(service, "_get_many_from_database", lambda symbols: {s: (None, None) for s in symbols})
    monkeypatch.setattr(service, "_fetch_and_cache", lambda symbol, market=None: fetched)

    assert service.get_fundamentals("AAPL") is fetched
    service.get_many(["AAPL"])
    assert EXECUTED == []


def test_benchmark_cache_round_trips_and_ignores_a_legacy_pickle():
    from app.services.benchmark_cache_service import BenchmarkCacheService

    EXECUTED.clear()
    redis = _DictRedis()
    service = BenchmarkCacheService(redis_client=redis, session_factory=lambda: None)
    frame = _recent_ohlcv()

    service.store_benchmark_in_redis("SPY", "2y", frame, market="US")
    pd.testing.assert_frame_equal(
        service.load_benchmark_from_redis("SPY", "2y", "US"), frame, check_freq=False
    )

    redis.values[service._redis_data_key("SPY", "2y", "US")] = pickle.dumps(_Exploit())
    assert service.load_benchmark_from_redis("SPY", "2y", "US") is None
    assert EXECUTED == []
