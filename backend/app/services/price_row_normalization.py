"""Shared normalization for persisted OHLCV price rows."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from app.infra.serialization import finite_float_or_none

OHLC_COLUMNS = ("Open", "High", "Low", "Close")


def finite_ohlc_values(
    open_: Any,
    high: Any,
    low: Any,
    close: Any,
) -> tuple[float, float, float, float] | None:
    open_price = finite_float_or_none(open_)
    high_price = finite_float_or_none(high)
    low_price = finite_float_or_none(low)
    close_price = finite_float_or_none(close)
    if (
        open_price is None
        or high_price is None
        or low_price is None
        or close_price is None
    ):
        return None
    return open_price, high_price, low_price, close_price


def drop_non_finite_close_rows(data: pd.DataFrame | None) -> pd.DataFrame | None:
    """Remove rows whose OHLC values cannot be safely treated as market prices."""
    if data is None or data.empty:
        return data
    if any(column not in data.columns for column in OHLC_COLUMNS):
        return data.iloc[0:0].copy()
    keep_mask = np.ones(len(data), dtype=bool)
    for column in OHLC_COLUMNS:
        keep_mask &= _finite_mask(data[column])
    if keep_mask.all():
        return data
    return data.loc[keep_mask].copy()


def _finite_mask(values: pd.Series) -> np.ndarray:
    """Per-cell ``finite_float_or_none(...) is not None``, vectorized for numpy numbers."""
    dtype = getattr(values, "dtype", None)
    # Wider floats (x86 longdouble) can be finite yet overflow Python float, so they
    # stay on the per-cell path with object and nullable-extension columns.
    if isinstance(dtype, np.dtype) and (
        dtype.kind in "iu" or (dtype.kind == "f" and dtype.itemsize <= 8)
    ):
        return np.isfinite(values.to_numpy())
    return values.map(finite_float_or_none).notna().to_numpy()


def normalize_price_frame(
    data: pd.DataFrame | None,
    *,
    min_rows: int = 1,
) -> pd.DataFrame | None:
    """Return a finite-close OHLCV frame that satisfies the row-count contract."""
    cleaned = drop_non_finite_close_rows(data)
    if cleaned is None or cleaned.empty:
        return None
    if len(cleaned) < min_rows:
        return None
    return cleaned


def normalize_price_batch(
    batch_data: Mapping[str, pd.DataFrame | None],
    *,
    min_rows: int = 1,
) -> dict[str, pd.DataFrame]:
    """Normalize a symbol->price-frame batch and drop unusable symbols."""
    normalized: dict[str, pd.DataFrame] = {}
    for symbol, data in batch_data.items():
        cleaned = normalize_price_frame(data, min_rows=min_rows)
        if cleaned is not None:
            normalized[symbol] = cleaned
    return normalized


def _volume_or_zero(value: Any) -> int:
    number = finite_float_or_none(value)
    if number is None:
        return 0
    return int(number)


def stock_price_row_from_ohlcv(
    *,
    symbol: str,
    row_date: date,
    row: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Build a StockPrice mapping, skipping rows without complete finite OHLC."""
    ohlc = finite_ohlc_values(
        row.get("Open"),
        row.get("High"),
        row.get("Low"),
        row.get("Close"),
    )
    if ohlc is None:
        return None
    open_, high, low, close = ohlc
    adj_close = finite_float_or_none(row.get("Adj Close"))
    return {
        "symbol": symbol,
        "date": row_date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": _volume_or_zero(row.get("Volume")),
        "adj_close": adj_close if adj_close is not None else close,
    }


def stock_price_frame(rows: Iterable[Any], *, include_adj_close: bool) -> pd.DataFrame:
    """Turn StockPrice rows (oldest first) into an OHLCV frame indexed by ``Date``.

    The inverse of ``stock_price_row_from_ohlcv``. Callers keep their own row
    thresholds and finite-close normalization.
    """
    rows = list(rows)
    data = {
        "Date": [row.date for row in rows],
        "Open": [row.open for row in rows],
        "High": [row.high for row in rows],
        "Low": [row.low for row in rows],
        "Close": [row.close for row in rows],
    }
    if include_adj_close:
        data["Adj Close"] = [row.adj_close for row in rows]
    data["Volume"] = [row.volume for row in rows]
    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")


# Column order of the StockPrice select that ``stock_price_frames_by_symbol`` reads.
STOCK_PRICE_ROW_COLUMNS = (
    "symbol", "date", "open", "high", "low", "close", "adj_close", "volume",
)
_FRAME_COLUMN_NAMES = {
    "date": "Date", "open": "Open", "high": "High", "low": "Low",
    "close": "Close", "adj_close": "Adj Close", "volume": "Volume",
}


def stock_price_frames_by_symbol(
    rows: Iterable[Any], *, include_adj_close: bool
) -> dict[str, pd.DataFrame]:
    """``stock_price_frame`` for many symbols at once, from one row list.

    ``rows`` are tuples in ``STOCK_PRICE_ROW_COLUMNS`` order, sorted by symbol
    and then date (oldest first). One frame is built for all of them and cut
    at the symbol boundaries, which is several times faster than a Python
    list per column per symbol (#418). Each symbol gets its own copy.
    """
    frame = pd.DataFrame.from_records(list(rows), columns=STOCK_PRICE_ROW_COLUMNS)
    if frame.empty:
        return {}
    frame["date"] = pd.to_datetime(frame["date"])
    symbols = frame.pop("symbol").to_numpy()
    if not include_adj_close:
        frame = frame.drop(columns="adj_close")
    frame = frame.rename(columns=_FRAME_COLUMN_NAMES).set_index("Date")
    # Sorted by symbol, so every symbol is one contiguous run of rows.
    starts = np.flatnonzero(np.r_[True, symbols[1:] != symbols[:-1]])
    ends = np.r_[starts[1:], len(symbols)]
    # A symbol's frame must not depend on the other symbols in the chunk, so
    # NULLs are counted per symbol and column (one vectorized pass):
    # - a column that is all NULL for a symbol becomes object None, as in
    #   ``stock_price_frame``, not float NaN borrowed from the shared column;
    # - one NULL volume elsewhere makes the shared column float, so a symbol
    #   without gaps gets integer volume back.
    present = np.add.reduceat(frame.notna().to_numpy(), starts, axis=0)
    volume_column = frame.columns.get_loc("Volume")
    volume_widened = frame["Volume"].dtype.kind == "f"
    frames = {}
    for present_counts, start, end in zip(present, starts, ends):
        part = frame.iloc[start:end].copy()
        for column in np.flatnonzero(present_counts == 0):
            part[frame.columns[column]] = pd.Series(
                [None] * (end - start), index=part.index, dtype=object
            )
        if volume_widened and present_counts[volume_column] == end - start:
            part["Volume"] = part["Volume"].astype("int64")
        frames[symbols[start]] = part
    return frames
