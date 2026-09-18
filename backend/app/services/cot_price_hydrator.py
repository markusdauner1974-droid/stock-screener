from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.domain.cot.calculations import MAX_PRICE_AGE
from app.domain.cot.models import CotInstrumentDefinition, PriceCoverageState

_COMPLETE_COVERAGE_DAYS = 5 * 365 - 7


@dataclass(frozen=True)
class CotPriceHydrationItem:
    slug: str
    yahoo_symbol: str | None
    coverage_state: PriceCoverageState
    row_count: int
    history_start: date | None
    history_end: date | None
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "yahoo_symbol": self.yahoo_symbol,
            "coverage_state": self.coverage_state.value,
            "row_count": self.row_count,
            "history_start": self.history_start.isoformat() if self.history_start else None,
            "history_end": self.history_end.isoformat() if self.history_end else None,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class CotPriceHydrationResult:
    items: tuple[CotPriceHydrationItem, ...]

    @property
    def attempted_count(self) -> int:
        return sum(item.yahoo_symbol is not None for item in self.items)

    @property
    def available_count(self) -> int:
        return sum(
            item.coverage_state is PriceCoverageState.COMPLETE for item in self.items
        )

    @property
    def partial_count(self) -> int:
        return sum(
            item.coverage_state is PriceCoverageState.PARTIAL for item in self.items
        )

    @property
    def unavailable_count(self) -> int:
        return sum(
            item.coverage_state is PriceCoverageState.UNAVAILABLE
            for item in self.items
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted_count": self.attempted_count,
            "available_count": self.available_count,
            "partial_count": self.partial_count,
            "unavailable_count": self.unavailable_count,
            "items": [item.as_dict() for item in self.items],
        }


class CotPriceHydrator:
    def __init__(self, price_cache: Any) -> None:
        self._price_cache = price_cache

    def hydrate(
        self,
        instruments: Sequence[CotInstrumentDefinition],
        *,
        report_date: date,
    ) -> CotPriceHydrationResult:
        items: list[CotPriceHydrationItem] = []
        for definition in instruments:
            symbol = definition.price.yahoo_symbol
            if symbol is None:
                items.append(
                    CotPriceHydrationItem(
                        slug=definition.slug,
                        yahoo_symbol=None,
                        coverage_state=PriceCoverageState.UNAVAILABLE,
                        row_count=0,
                        history_start=None,
                        history_end=None,
                        error_code="no_machine_readable_mapping",
                    )
                )
                continue
            try:
                frame = self._price_cache.get_historical_data(
                    symbol,
                    period="5y",
                    market="US",
                )
                if frame is None or frame.empty:
                    items.append(
                        CotPriceHydrationItem(
                            slug=definition.slug,
                            yahoo_symbol=symbol,
                            coverage_state=PriceCoverageState.UNAVAILABLE,
                            row_count=0,
                            history_start=None,
                            history_end=None,
                            error_code="empty_price_history",
                        )
                    )
                    continue
                history_start = frame.index.min().date()
                history_end = frame.index.max().date()
                if (
                    (history_end - history_start).days < _COMPLETE_COVERAGE_DAYS
                    or history_end < report_date - MAX_PRICE_AGE
                ):
                    refreshed_frame = self._price_cache.get_historical_data(
                        symbol,
                        period="5y",
                        market="US",
                        force_refresh=True,
                    )
                    if refreshed_frame is not None and not refreshed_frame.empty:
                        frame = refreshed_frame
                        history_start = frame.index.min().date()
                        history_end = frame.index.max().date()
                history_is_fresh = history_end >= report_date - MAX_PRICE_AGE
                coverage = (
                    PriceCoverageState.COMPLETE
                    if (
                        (history_end - history_start).days
                        >= _COMPLETE_COVERAGE_DAYS
                        and history_is_fresh
                    )
                    else PriceCoverageState.PARTIAL
                )
                items.append(
                    CotPriceHydrationItem(
                        slug=definition.slug,
                        yahoo_symbol=symbol,
                        coverage_state=coverage,
                        row_count=len(frame.index),
                        history_start=history_start,
                        history_end=history_end,
                        error_code=(
                            None if history_is_fresh else "stale_price_history"
                        ),
                    )
                )
            except Exception as exc:
                items.append(
                    CotPriceHydrationItem(
                        slug=definition.slug,
                        yahoo_symbol=symbol,
                        coverage_state=PriceCoverageState.UNAVAILABLE,
                        row_count=0,
                        history_start=None,
                        history_end=None,
                        error_code=type(exc).__name__,
                    )
                )
        return CotPriceHydrationResult(items=tuple(items))
