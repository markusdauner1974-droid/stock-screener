"""SQL-backed price reads for published COT queries."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from sqlalchemy import select

from app.models.stock import StockPrice


class SqlCotPriceReader:
    def __init__(self, session) -> None:
        self._session = session

    def closes(self, symbol: str, *, start: date, end: date) -> Mapping[date, float]:
        rows = self._session.execute(
            select(StockPrice.date, StockPrice.close).where(
                StockPrice.symbol == symbol,
                StockPrice.date >= start,
                StockPrice.date <= end,
                StockPrice.close.is_not(None),
            )
        ).all()
        return {price_date: float(close) for price_date, close in rows}


__all__ = ["SqlCotPriceReader"]
