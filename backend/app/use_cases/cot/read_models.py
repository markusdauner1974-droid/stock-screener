from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class CotPublicationView:
    schema_version: str
    calculation_version: str
    registry_version: str
    publication_id: int
    report_date: date
    retrieved_at: datetime
    stale: bool


@dataclass(frozen=True)
class CotSourceView:
    dataset_id: str
    label: str
    url: str


@dataclass(frozen=True)
class CotCatalogInstrumentView:
    slug: str
    display_name: str
    category: str
    category_order: int
    instrument_order: int
    report_family: str
    focal_participant: str
    participants: tuple[str, ...]
    price_symbol: str | None
    price_mapping_kind: str
    tradingview_url: str | None


@dataclass(frozen=True)
class CotCatalogView:
    publication: CotPublicationView
    default_slug: str
    categories: tuple[str, ...]
    sources: tuple[CotSourceView, ...]
    instruments: tuple[CotCatalogInstrumentView, ...]


@dataclass(frozen=True)
class CotPositionView:
    participant: str
    label: str
    long: int
    short: int
    spreading: int
    net: int
    delta_long: int | None
    delta_short: int | None
    delta_net: int | None
    net_pct_open_interest: float | None
    percentile_3y: float | None
    percentile_status: str


@dataclass(frozen=True)
class CotHistoryWeekView:
    report_date: date
    open_interest: int
    price_date: date | None
    price_close: float | None
    price_change_pct: float | None
    positions: tuple[CotPositionView, ...]


@dataclass(frozen=True)
class CotHistoryView:
    publication: CotPublicationView
    range: str
    slug: str
    display_name: str
    category: str
    report_family: str
    source_dataset_id: str
    focal_participant: str
    price_symbol: str | None
    price_mapping_kind: str
    price_coverage_state: str
    price_history_start: date | None
    tradingview_url: str | None
    weeks: tuple[CotHistoryWeekView, ...]


@dataclass(frozen=True)
class CotSnapshotRowView:
    slug: str
    display_name: str
    category: str
    instrument_order: int
    focal_participant: str
    focal_label: str
    report_date: date
    long: int
    short: int
    net: int
    delta_long: int | None
    delta_short: int | None
    delta_net: int | None
    net_pct_open_interest: float | None
    percentile_3y: float | None
    percentile_status: str
    net_trend: tuple[int, ...]
    price_change_pct: float | None
    price_mapping_kind: str
    price_coverage_state: str


@dataclass(frozen=True)
class CotSnapshotView:
    publication: CotPublicationView
    rows: tuple[CotSnapshotRowView, ...]
