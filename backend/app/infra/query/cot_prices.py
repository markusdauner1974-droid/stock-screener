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

    def closes_many(
        self,
        requests: Mapping[str, tuple[date, date]],
    ) -> Mapping[str, Mapping[date, float]]:
        if not requests:
            return {}
        symbols = tuple(requests)
        earliest = min(start for start, _end in requests.values())
        latest = max(end for _start, end in requests.values())
        rows = self._session.execute(
            select(StockPrice.symbol, StockPrice.date, StockPrice.close).where(
                StockPrice.symbol.in_(symbols),
                StockPrice.date >= earliest,
                StockPrice.date <= latest,
                StockPrice.close.is_not(None),
            )
        ).all()
        result: dict[str, dict[date, float]] = {symbol: {} for symbol in symbols}
        for symbol, price_date, close in rows:
            start, end = requests[symbol]
            if start <= price_date <= end:
                result[symbol][price_date] = float(close)
        return result


__all__ = ["SqlCotPriceReader"]
