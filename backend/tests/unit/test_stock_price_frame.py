from datetime import date
from types import SimpleNamespace

import pandas as pd

from app.services.price_row_normalization import stock_price_frame


def _row(day, close):
    return SimpleNamespace(
        date=day, open=close - 1, high=close + 1, low=close - 2, close=close,
        adj_close=close - 0.5, volume=100,
    )


def test_stock_price_frame_indexes_rows_by_date():
    rows = [_row(date(2026, 9, 29), 10.0), _row(date(2026, 9, 30), 11.0)]

    frame = stock_price_frame(rows, include_adj_close=True)

    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    assert isinstance(frame.index, pd.DatetimeIndex) and frame.index.name == "Date"
    assert list(frame.index) == [pd.Timestamp("2026-09-29"), pd.Timestamp("2026-09-30")]
    assert frame["Close"].tolist() == [10.0, 11.0]
    assert frame["Adj Close"].tolist() == [9.5, 10.5]


def test_stock_price_frame_can_omit_adj_close():
    frame = stock_price_frame([_row(date(2026, 9, 30), 11.0)], include_adj_close=False)

    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
