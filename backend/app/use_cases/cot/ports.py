from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Protocol

from app.domain.cot.models import (
    COT_CALCULATION_VERSION,
    COT_REGISTRY_VERSION,
    COT_SCHEMA_VERSION,
    CotInstrumentDefinition,
    NormalizedCotWeek,
)


@dataclass(frozen=True)
class CotRunRequest:
    origin: str
    expected_instrument_count: int
    requested_report_date: date | None = None
    registry_version: str = COT_REGISTRY_VERSION
    calculation_version: str = COT_CALCULATION_VERSION
    schema_version: str = COT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.origin.strip():
            raise ValueError("origin must be non-empty")
        if self.expected_instrument_count < 0:
            raise ValueError("expected instrument count must be nonnegative")


@dataclass(frozen=True)
class CotSourceMetadata:
    retrieved_at: datetime
    retry_count: int
    dataset_row_counts: Mapping[str, int]
    expected_dataset_row_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.retry_count < 0:
            raise ValueError("retry_count must be nonnegative")
        if any(count < 0 for count in self.dataset_row_counts.values()):
            raise ValueError("dataset row counts must be nonnegative")
        if any(count < 0 for count in self.expected_dataset_row_counts.values()):
            raise ValueError("expected dataset row counts must be nonnegative")
        object.__setattr__(
            self,
            "dataset_row_counts",
            MappingProxyType(dict(self.dataset_row_counts)),
        )
        object.__setattr__(
            self,
            "expected_dataset_row_counts",
            MappingProxyType(dict(self.expected_dataset_row_counts)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "retrieved_at": self.retrieved_at.isoformat(),
            "retry_count": self.retry_count,
            "dataset_row_counts": dict(self.dataset_row_counts),
            "expected_dataset_row_counts": dict(
                self.expected_dataset_row_counts
            ),
        }


@dataclass(frozen=True)
class CotSourceSnapshot:
    weeks: tuple[NormalizedCotWeek, ...]
    metadata: CotSourceMetadata


class CotSource(Protocol):
    def fetch(
        self,
        instruments: Sequence[CotInstrumentDefinition],
    ) -> CotSourceSnapshot: ...


class CotRepository(Protocol):
    def existing_week_keys(self) -> frozenset[tuple[str, object]]: ...

    def stored_fingerprints(self) -> Mapping[str, str]: ...


class CotPriceHydratorPort(Protocol):
    def hydrate(self, instruments: Sequence[CotInstrumentDefinition]) -> Any: ...


class CotReadSide(Protocol):
    def get_publication(self) -> Any: ...

    def get_instruments(self) -> Sequence[Any]: ...

    def get_history(self, slug: str, *, limit: int) -> Sequence[Any]: ...

    def get_snapshot(self) -> Sequence[Any]: ...
