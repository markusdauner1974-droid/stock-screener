from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Protocol

from app.domain.cot.models import (
    COT_CALCULATION_VERSION,
    COT_REGISTRY_VERSION,
    COT_SCHEMA_VERSION,
    CotInstrumentDefinition,
    DerivedCotWeek,
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

    def as_dict(self) -> dict[str, object]:
        return {
            "retrieved_at": self.retrieved_at.isoformat(),
            "retry_count": self.retry_count,
            "dataset_row_counts": dict(self.dataset_row_counts),
            "expected_dataset_row_counts": dict(self.expected_dataset_row_counts),
        }


@dataclass(frozen=True)
class CotSourceSnapshot:
    weeks: tuple[NormalizedCotWeek, ...]
    metadata: CotSourceMetadata


@dataclass(frozen=True)
class CotPublicationSignature:
    source_fingerprints: Mapping[str, str]
    registry_version: str
    calculation_version: str
    schema_version: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.registry_version,
                self.calculation_version,
                self.schema_version,
            )
        ):
            raise ValueError("publication signature versions must be non-empty")
        object.__setattr__(
            self,
            "source_fingerprints",
            MappingProxyType(dict(self.source_fingerprints)),
        )


class CotSource(Protocol):
    def fetch(
        self,
        instruments: Sequence[CotInstrumentDefinition],
    ) -> CotSourceSnapshot: ...


class CotWriteRepository(Protocol):
    def start_run(self, request: CotRunRequest) -> int: ...

    def existing_week_keys(
        self,
        instrument_slugs: Sequence[str],
    ) -> frozenset[tuple[str, date]]: ...

    def publication_signature(self) -> CotPublicationSignature | None: ...

    def publish(
        self,
        run_id: int,
        *,
        registry: Sequence[CotInstrumentDefinition],
        weeks: Sequence[DerivedCotWeek],
        diagnostics: Mapping[str, object],
        source_metadata: Mapping[str, object],
    ) -> None: ...

    def mark_no_change(
        self,
        run_id: int,
        diagnostics: Mapping[str, object],
    ) -> None: ...

    def mark_failed(
        self,
        run_id: int,
        status: str,
        diagnostics: Mapping[str, object],
    ) -> None: ...


class CotPriceHydrationResultPort(Protocol):
    unavailable_count: int

    def as_dict(self) -> Mapping[str, object]: ...


class CotPriceHydratorPort(Protocol):
    def hydrate(
        self,
        instruments: Sequence[CotInstrumentDefinition],
    ) -> CotPriceHydrationResultPort: ...


class CotRunRecord(Protocol):
    id: int
    registry_version: str
    calculation_version: str
    schema_version: str
    source_metadata_json: Mapping[str, object] | None
    published_at: datetime | None


class CotPublicationPointerRecord(Protocol):
    report_date: date


class CotPublicationRecord(Protocol):
    run: CotRunRecord
    pointer: CotPublicationPointerRecord


class CotHistoryPositionRecord(Protocol):
    report_date: date
    participant: str
    long: int
    short: int
    spreading: int
    open_interest: int
    net: int
    delta_long: int | None
    delta_short: int | None
    delta_net: int | None
    net_pct_open_interest: float | None
    percentile_3y: float | None
    percentile_status: str


@dataclass(frozen=True)
class CotSnapshotPositionRecord:
    instrument_slug: str
    report_date: date
    participant: str
    long: int
    short: int
    open_interest: int
    net: int
    delta_long: int | None
    delta_short: int | None
    delta_net: int | None
    net_pct_open_interest: float | None
    percentile_3y: float | None
    percentile_status: str


class CotReadRepository(Protocol):
    def get_publication(self) -> CotPublicationRecord | None: ...

    def get_history(
        self,
        slug: str,
        *,
        limit: int,
    ) -> Sequence[CotHistoryPositionRecord]: ...

    def get_snapshot_history(
        self,
        *,
        weeks: int,
    ) -> Sequence[CotSnapshotPositionRecord]: ...


class CotPriceReader(Protocol):
    def closes(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
    ) -> Mapping[date, float]: ...

    def closes_many(
        self,
        requests: Mapping[str, tuple[date, date]],
    ) -> Mapping[str, Mapping[date, float]]: ...
