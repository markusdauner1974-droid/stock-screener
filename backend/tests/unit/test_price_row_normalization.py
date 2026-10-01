from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.infra.serialization import finite_float_or_none
from app.services.price_row_normalization import (
    STOCK_PRICE_ROW_COLUMNS,
    drop_non_finite_close_rows,
    normalize_price_batch,
    normalize_price_frame,
    stock_price_frame,
    stock_price_frames_by_symbol,
    stock_price_row_from_ohlcv,
)


def _ohlcv_frame(closes: list[float], days: list[date]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": closes,
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=pd.to_datetime(days),
    )


def test_drop_non_finite_close_rows_removes_unusable_market_prices():
    payload = _ohlcv_frame(
        [101.0, float("nan"), float("inf")],
        [date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26)],
    )

    cleaned = drop_non_finite_close_rows(payload)

    assert cleaned is not None
    assert cleaned["Close"].tolist() == [101.0]
    assert cleaned.index.tolist() == [pd.Timestamp(date(2026, 6, 24))]


def test_drop_non_finite_close_rows_treats_missing_close_as_empty_price_frame():
    payload = pd.DataFrame(
        {"Open": [100.0], "Volume": [1_000_000]},
        index=pd.to_datetime([date(2026, 6, 24)]),
    )

    cleaned = drop_non_finite_close_rows(payload)

    assert cleaned is not None
    assert cleaned.empty
    assert list(cleaned.columns) == ["Open", "Volume"]


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param(
            {
                "Open": [100.0, float("nan"), 102.0, 103.0, 104.0],
                "High": [101.0, 102.0, float("inf"), 104.0, 105.0],
                "Low": [99.0, 100.0, 101.0, float("-inf"), 103.0],
                "Close": [100.5, 101.5, 102.5, 103.5, 104.5],
            },
            id="float-columns",
        ),
        pytest.param(
            {
                "Open": [100, 101, 102, 103, 104],
                "High": np.array([101, 102, 103, 104, 105], dtype="uint32"),
                "Low": np.array([99.0, np.nan, 101.0, 102.0, 103.0], dtype="float32"),
                "Close": [100, 101, 102, 103, 104],
            },
            id="integer-and-float32-columns",
        ),
        pytest.param(
            {
                "Open": [100.0, None, "102.5", "n/a", Decimal("104.25")],
                "High": [Decimal("101"), 102.0, 103.0, 104.0, float("inf")],
                "Low": [True, 100.0, 101.0, 102.0, 103.0],
                "Close": pd.array([100.5, 101.5, pd.NA, 103.5, 104.5], dtype="Float64"),
            },
            id="object-and-nullable-columns",
        ),
    ],
)
def test_drop_non_finite_close_rows_matches_the_per_cell_finite_check(columns):
    payload = pd.DataFrame(
        {**columns, "Volume": [1_000_000] * 5},
        index=pd.to_datetime([date(2026, 6, day) for day in range(22, 27)]),
    )
    expected_keep = pd.Series(True, index=payload.index)
    for column in ("Open", "High", "Low", "Close"):
        expected_keep &= payload[column].map(finite_float_or_none).notna()

    cleaned = drop_non_finite_close_rows(payload)

    assert not expected_keep.all()
    pd.testing.assert_frame_equal(cleaned, payload.loc[expected_keep])


def test_drop_non_finite_close_rows_drops_longdouble_values_that_overflow_float():
    # Finite as an x86 longdouble, infinite once converted to a Python float.
    closes = np.array(["100.5", "1e400", "102.5"], dtype=np.longdouble)
    payload = pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes},
        index=pd.to_datetime([date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26)]),
    )

    cleaned = drop_non_finite_close_rows(payload)

    assert cleaned.index.tolist() == [
        pd.Timestamp(date(2026, 6, 24)),
        pd.Timestamp(date(2026, 6, 26)),
    ]


def test_drop_non_finite_close_rows_returns_a_clean_frame_unchanged():
    payload = _ohlcv_frame([101.0, 102.0], [date(2026, 6, 24), date(2026, 6, 25)])

    assert drop_non_finite_close_rows(payload) is payload


def test_stock_price_row_from_ohlcv_skips_rows_without_finite_close():
    row = pd.Series({"Open": 100.0, "Close": float("nan"), "Volume": 1_000_000})

    assert stock_price_row_from_ohlcv(symbol="SPY", row_date=date(2026, 6, 24), row=row) is None


def test_stock_price_row_from_ohlcv_skips_rows_without_complete_finite_ohlc():
    row = pd.Series(
        {
            "Open": 100.0,
            "High": float("nan"),
            "Low": 99.0,
            "Close": 101.0,
            "Volume": 1_000_000,
        }
    )

    assert stock_price_row_from_ohlcv(symbol="SPY", row_date=date(2026, 6, 24), row=row) is None


def test_normalize_price_frame_enforces_min_rows_after_filtering():
    payload = _ohlcv_frame([101.0, float("nan")], [date(2026, 6, 24), date(2026, 6, 25)])

    assert normalize_price_frame(payload, min_rows=2) is None

    cleaned = normalize_price_frame(payload, min_rows=1)

    assert cleaned is not None
    assert cleaned["Close"].tolist() == [101.0]


def test_normalize_price_frame_removes_rows_with_incomplete_ohlc_values():
    payload = pd.DataFrame(
        {
            "Open": [100.0, float("nan")],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1_000_000, 1_000_000],
        },
        index=pd.to_datetime([date(2026, 6, 24), date(2026, 6, 25)]),
    )

    cleaned = normalize_price_frame(payload)

    assert cleaned is not None
    assert cleaned["Close"].tolist() == [101.0]
    assert cleaned.index.tolist() == [pd.Timestamp(date(2026, 6, 24))]


def test_normalize_price_batch_filters_symbols_with_insufficient_clean_rows():
    enough_rows = _ohlcv_frame([101.0, 102.0], [date(2026, 6, 24), date(2026, 6, 25)])
    insufficient_after_filter = _ohlcv_frame([103.0, float("nan")], [date(2026, 6, 24), date(2026, 6, 25)])
    no_close = pd.DataFrame(
        {"Open": [100.0, 101.0], "Volume": [1_000_000, 1_000_000]},
        index=pd.to_datetime([date(2026, 6, 24), date(2026, 6, 25)]),
    )

    cleaned = normalize_price_batch(
        {"AAPL": enough_rows, "MSFT": insufficient_after_filter, "BAD": no_close},
        min_rows=2,
    )

    assert list(cleaned) == ["AAPL"]
    assert cleaned["AAPL"]["Close"].tolist() == [101.0, 102.0]


def _price_rows():
    """Column-select rows as the bulk loader gets them: by symbol, then date."""
    from collections import namedtuple

    Row = namedtuple("Row", STOCK_PRICE_ROW_COLUMNS)
    return [
        Row("AAPL", date(2026, 6, 22), 100.0, 101.0, 99.0, 100.5, 100.5, 1_000),
        Row("AAPL", date(2026, 6, 23), 101.0, 102.0, 100.0, None, None, None),
        Row("AAPL", date(2026, 6, 24), 102.0, 103.0, 101.0, 102.5, 102.0, 3_000),
        Row("MSFT", date(2026, 6, 23), 300.0, 301.0, 299.0, float("nan"), 300.0, 5_000),
        Row("MSFT", date(2026, 6, 24), 301.0, 302.0, 300.0, 301.5, 301.5, 6_000),
    ]


@pytest.mark.parametrize("include_adj_close", [True, False])
def test_frames_by_symbol_match_the_per_symbol_builder(include_adj_close):
    rows = _price_rows()

    frames = stock_price_frames_by_symbol(rows, include_adj_close=include_adj_close)

    assert list(frames) == ["AAPL", "MSFT"]
    for symbol, frame in frames.items():
        expected = stock_price_frame(
            [row for row in rows if row.symbol == symbol],
            include_adj_close=include_adj_close,
        )
        pd.testing.assert_frame_equal(frame, expected)  # values, dtypes and index


def test_frames_by_symbol_keep_an_all_null_column_as_its_own_frame_would():
    """Review on #460: a symbol whose Adj Close and Volume are all NULL must not
    pick up its neighbours' dtype."""
    from collections import namedtuple

    Row = namedtuple("Row", STOCK_PRICE_ROW_COLUMNS)
    rows = [
        Row("BARE", date(2026, 6, 23), 10.0, 11.0, 9.0, 10.5, None, None),
        Row("BARE", date(2026, 6, 24), 10.5, 11.5, 9.5, 11.0, None, None),
        Row("FULL", date(2026, 6, 23), 20.0, 21.0, 19.0, 20.5, 20.5, 7_000),
        Row("FULL", date(2026, 6, 24), 20.5, 21.5, 19.5, 21.0, 21.0, 8_000),
    ]

    frames = stock_price_frames_by_symbol(rows, include_adj_close=True)

    for symbol in ("BARE", "FULL"):
        pd.testing.assert_frame_equal(
            frames[symbol],
            stock_price_frame(
                [row for row in rows if row.symbol == symbol], include_adj_close=True
            ),
        )


def test_frames_by_symbol_are_independent_copies():
    frames = stock_price_frames_by_symbol(_price_rows(), include_adj_close=True)

    # A slice of the shared chunk frame would keep the whole chunk alive and
    # warn when a caller adds or changes a column.
    assert not np.shares_memory(
        frames["AAPL"]["Open"].to_numpy(), frames["MSFT"]["Open"].to_numpy()
    )
    frames["AAPL"]["Close"] = 0.0
    assert frames["MSFT"]["Close"].tolist()[1] == 301.5


def test_frames_by_symbol_of_no_rows_is_empty():
    assert stock_price_frames_by_symbol([], include_adj_close=True) == {}
