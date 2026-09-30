"""Shared transactional persistence for normalized stock price rows."""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from app.models.stock import StockPrice
from app.services.price_row_normalization import finite_ohlc_values
from app.services.price_value_policy import is_usable_adjusted_close


def persist_stock_price_mappings(
    db: Session,
    price_rows_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    chunk_size: int = 100,
) -> dict[str, int]:
    """Persist StockPrice mapping rows using the canonical latest-row update policy."""
    normalized_rows: dict[str, list[dict[str, Any]]] = {}
    symbol_dates: dict[str, set[date]] = {}
    latest_dates: dict[str, date] = {}

    for symbol, rows in price_rows_by_symbol.items():
        symbol_rows: list[dict[str, Any]] = []
        for row in rows:
            row_date = row.get("date")
            if isinstance(row_date, date):
                normalized = dict(row)
                symbol_rows.append(normalized)
                symbol_dates.setdefault(symbol, set()).add(row_date)
                latest = latest_dates.get(symbol)
                latest_dates[symbol] = row_date if latest is None or row_date > latest else latest
        if symbol_rows:
            normalized_rows[symbol] = symbol_rows

    if not normalized_rows:
        return {"inserted": 0, "updated": 0}

    symbols = list(normalized_rows)
    all_dates = [row_date for dates in symbol_dates.values() for row_date in dates]
    min_date = min(all_dates)
    max_date = max(all_dates)
    existing_pairs: dict[
        tuple[str, date],
        tuple[int, object, object, object, object, object, object],
    ] = {}
    for chunk_start in range(0, len(symbols), chunk_size):
        chunk_symbols = symbols[chunk_start:chunk_start + chunk_size]
        rows = (
            db.query(
                StockPrice.id,
                StockPrice.symbol,
                StockPrice.date,
                StockPrice.adj_close,
                StockPrice.open,
                StockPrice.high,
                StockPrice.low,
                StockPrice.close,
                StockPrice.volume,
            )
            .filter(
                StockPrice.symbol.in_(chunk_symbols),
                StockPrice.date >= min_date,
                StockPrice.date <= max_date,
            )
            .all()
        )
        for (
            record_id,
            record_symbol,
            record_date,
            adj_close,
            open_,
            high,
            low,
            close,
            volume,
        ) in rows:
            target_dates = symbol_dates.get(record_symbol)
            if target_dates and record_date in target_dates:
                existing_pairs[(record_symbol, record_date)] = (
                    record_id,
                    adj_close,
                    open_,
                    high,
                    low,
                    close,
                    volume,
                )

    rows_to_insert: list[dict[str, Any]] = []
    rows_to_update: list[dict[str, Any]] = []
    for symbol, price_rows in normalized_rows.items():
        for price_row in price_rows:
            row_date = price_row["date"]
            existing = existing_pairs.get((symbol, row_date))
            if existing is None:
                rows_to_insert.append(price_row)
                continue

            existing_id, existing_adj_close, open_, high, low, close, volume = existing
            if (
                row_date == latest_dates.get(symbol)
                or not is_usable_adjusted_close(existing_adj_close)
                or finite_ohlc_values(open_, high, low, close) is None
            ):
                price_row["id"] = existing_id
                rows_to_update.append(price_row)
            elif _heals_same_basis_bar(price_row, open_, high, low, close, volume):
                rows_to_update.append(
                    {"id": existing_id, **{key: price_row[key] for key in _HEALED_FIELDS}}
                )

    for chunk_start in range(0, len(rows_to_insert), chunk_size):
        db.bulk_insert_mappings(
            StockPrice,
            rows_to_insert[chunk_start:chunk_start + chunk_size],
        )
    for chunk_start in range(0, len(rows_to_update), chunk_size):
        db.bulk_update_mappings(
            StockPrice,
            rows_to_update[chunk_start:chunk_start + chunk_size],
        )
    db.flush()
    return {"inserted": len(rows_to_insert), "updated": len(rows_to_update)}


_HEALED_FIELDS = ("open", "high", "low", "close", "volume")


def _heals_same_basis_bar(
    price_row: Mapping[str, Any],
    open_: object,
    high: object,
    low: object,
    close: object,
    volume: object,
) -> bool:
    """Whether a refetched older bar should replace a stored bar on the same price basis.

    Heals bars filled from a quote when Yahoo's daily history lacked the session
    (see ``yahoo_quote_price_repair``): the close matches, but open/high/low and
    volume differ slightly. A changed close means back-adjusted history (split),
    which is left to the full-history replacement path so rows never splice.
    ``adj_close`` is kept for the same reason.
    """
    try:
        if not math.isclose(float(price_row["close"]), float(close), rel_tol=1e-4):
            return False
        return int(price_row["volume"] or 0) != int(volume or 0) or not all(
            math.isclose(float(price_row[key]), float(stored), rel_tol=1e-6)
            for key, stored in (("open", open_), ("high", high), ("low", low))
        )
    except (KeyError, TypeError, ValueError):
        return False
