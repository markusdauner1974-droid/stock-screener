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
