from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import app.services.yahoo_quote_price_repair as repair_module
from app.services.yahoo_quote_price_repair import repair_from_yahoo_quotes

TOKYO = ZoneInfo("Asia/Tokyo")
SESSION = date(2026, 9, 29)


def _yahoo(rows):
    frame = pd.DataFrame(
        rows,
        columns=["Date", "Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends"],
    )
    return frame.set_index(pd.DatetimeIndex(frame.pop("Date")))


def _ok(frame):
    return {"price_data": frame, "has_error": False}


def _quote(symbol, *, close, day=SESSION, state="PREPRE"):
    # 15:30 JST: the TSE close.
    ts = datetime(day.year, day.month, day.day, 15, 30, tzinfo=TOKYO).timestamp()
    return {
        "symbol": symbol,
        "regularMarketOpen": close * 0.99,
        "regularMarketDayHigh": close * 1.01,
        "regularMarketDayLow": close * 0.98,
        "regularMarketPrice": close,
        "regularMarketVolume": 1000,
        "regularMarketTime": int(ts),
        "marketState": state,
    }


def _repair(results, quotes, **kwargs):
    return repair_from_yahoo_quotes(
        results,
        expected_session=SESSION,
        market_tz=TOKYO,
        fetch_quotes=lambda symbols: [q for q in quotes if q["symbol"] in symbols],
        **kwargs,
    )


def test_appends_missing_session_with_anchor_adj_ratio_and_only_quotes_stale():
    requested = []
    results = {
        "7203.T": _ok(_yahoo([("2026-09-28", 2990, 3000, 2980, 2986.5, 1493.25, 9, 0.0)])),
        "6758.T": _ok(_yahoo([("2026-09-29", 1, 1, 1, 1, 1, 1, 0.0)])),
    }

    stats = repair_from_yahoo_quotes(
        results,
        expected_session=SESSION,
        market_tz=TOKYO,
        fetch_quotes=lambda symbols: requested.extend(symbols) or [_quote("7203.T", close=3010.0)],
    )

    frame = results["7203.T"]["price_data"]
    assert requested == ["7203.T"]
    assert stats == {"stale": 1, "repaired": 1, "failed": 0, "skipped": 0}
    assert frame.loc["2026-09-29", "Close"] == 3010.0
    assert frame.loc["2026-09-29", "Adj Close"] == pytest.approx(1505.0)
    assert frame.loc["2026-09-29", "Dividends"] == 0.0
    assert results["7203.T"]["repaired_by"] == "yahoo_quote"


def test_fills_interior_hole_before_next_intraday_bar():
    results = {
        "1306.T": _ok(
            _yahoo(
                [
                    ("2026-09-28", 3.0, 3.1, 2.9, 3.0, 3.0, 1, 0.0),
                    ("2026-09-30", 3.2, 3.3, 3.1, 3.2, 3.2, 1, 0.0),
                ]
            )
        )
    }

    _repair(results, [_quote("1306.T", close=3.1)])

    assert [ts.date().isoformat() for ts in results["1306.T"]["price_data"].index] == [
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
    ]


@pytest.mark.parametrize(
    "quote",
    [
        # Run after the next session opened: the quote describes 09-30.
        _quote("7203.T", close=3010.0, day=date(2026, 9, 30), state="REGULAR"),
        # Calendar says closed but Yahoo still reports a live session.
        _quote("7203.T", close=3010.0, state="REGULAR"),
        # Close above the high: never persist an impossible bar.
        _quote("7203.T", close=3010.0) | {"regularMarketDayHigh": 0, "regularMarketDayLow": 0},
    ],
)
def test_skips_quotes_that_do_not_describe_the_completed_session(quote):
    results = {"7203.T": _ok(_yahoo([("2026-09-28", 1, 1, 1, 1, 1, 1, 0.0)]))}

    stats = _repair(results, [quote])

    assert stats["failed"] == 1
    assert "repaired_by" not in results["7203.T"]


def test_index_quote_with_zero_volume_is_repaired():
    results = {"^N225": _ok(_yahoo([("2026-09-28", 1, 1, 1, 1, 1, 0, 0.0)]))}
    quote = _quote("^N225", close=65481.27) | {"regularMarketVolume": 0}

    stats = _repair(results, [quote])

    assert stats["repaired"] == 1
    assert results["^N225"]["price_data"].loc["2026-09-29", "Volume"] == 0


def test_request_breaker_skips_remaining_batches(monkeypatch):
    monkeypatch.setattr(repair_module, "YAHOO_QUOTE_BATCH_SIZE", 1)
    calls = []

    def failing(symbols):
        calls.append(symbols)
        raise RuntimeError("blocked")

    stale = _yahoo([("2026-09-28", 1, 1, 1, 1, 1, 1, 0.0)])
    results = {f"{code}.T": _ok(stale) for code in range(1000, 1006)}

    stats = repair_from_yahoo_quotes(
        results, expected_session=SESSION, market_tz=TOKYO, fetch_quotes=failing
    )

    assert len(calls) == repair_module.YAHOO_QUOTE_MAX_CONSECUTIVE_FAILURES
    assert stats == {"stale": 6, "repaired": 0, "failed": 3, "skipped": 3}


def test_empty_quote_responses_trip_the_request_breaker(monkeypatch):
    monkeypatch.setattr(repair_module, "YAHOO_QUOTE_BATCH_SIZE", 1)
    calls = []
    stale = _yahoo([("2026-09-28", 1, 1, 1, 1, 1, 1, 0.0)])
    results = {f"{code}.T": _ok(stale) for code in range(1000, 1006)}

    stats = repair_from_yahoo_quotes(
        results,
        expected_session=SESSION,
        market_tz=TOKYO,
        fetch_quotes=lambda symbols: calls.append(symbols) or [],
    )

    assert len(calls) == repair_module.YAHOO_QUOTE_MAX_CONSECUTIVE_FAILURES
    assert stats["skipped"] == 3
