from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum


COT_SCHEMA_VERSION = "cot-v1"
COT_CALCULATION_VERSION = "cot-positions-v1"
COT_REGISTRY_VERSION = "cot-curated-v1"
STATIC_COT_SCHEMA_VERSION = "static-cot-v1"


class ReportFamily(str, Enum):
    DISAGGREGATED_FUTURES_ONLY = "disaggregated_futures_only"
    TFF_FUTURES_ONLY = "tff_futures_only"


class Participant(str, Enum):
    PRODUCER_MERCHANT = "producer_merchant"
    SWAP_DEALER = "swap_dealer"
    MANAGED_MONEY = "managed_money"
    DEALER_INTERMEDIARY = "dealer_intermediary"
    ASSET_MANAGER = "asset_manager"
    LEVERAGED_FUNDS = "leveraged_funds"
    OTHER_REPORTABLES = "other_reportables"
    NONREPORTABLES = "nonreportables"


class Category(str, Enum):
    EQUITY_VOLATILITY = "equity_volatility"
    RATES = "rates"
    ENERGY = "energy"
    CURRENCIES = "currencies"
    DIGITAL_ASSETS = "digital_assets"
    METALS = "metals"
    GRAINS_OILSEEDS = "grains_oilseeds"
    SOFTS = "softs"
    LUMBER = "lumber"


class PriceMappingKind(str, Enum):
    EXACT_FUTURE = "exact_future"
    ETF_PROXY = "etf_proxy"
    INDEX_PROXY = "index_proxy"
    UNAVAILABLE = "unavailable"


class PriceCoverageState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PriceMapping:
    yahoo_symbol: str | None
    kind: PriceMappingKind
    tradingview_url: str | None = None

    def __post_init__(self) -> None:
        if self.yahoo_symbol is not None and not self.yahoo_symbol.strip():
            raise ValueError("yahoo_symbol must be non-empty when provided")
        if self.kind is PriceMappingKind.UNAVAILABLE and self.yahoo_symbol is not None:
            raise ValueError("unavailable price mappings cannot define a Yahoo symbol")
        if self.kind is not PriceMappingKind.UNAVAILABLE and self.yahoo_symbol is None:
            raise ValueError("available price mappings require a Yahoo symbol")


@dataclass(frozen=True)
class RawParticipantPosition:
    participant: Participant
    long: int
    short: int
    spreading: int

    def __post_init__(self) -> None:
        _require_nonnegative_counts(
            long=self.long,
            short=self.short,
            spreading=self.spreading,
        )


@dataclass(frozen=True)
class NormalizedCotWeek:
    source_dataset_id: str
    source_row_id: str
    source_fingerprint: str
    instrument_slug: str
    report_date: date
    open_interest: int
    reported_long_total: int
    reported_short_total: int
    positions: tuple[RawParticipantPosition, ...]

    def __post_init__(self) -> None:
        _require_nonempty(
            source_dataset_id=self.source_dataset_id,
            source_row_id=self.source_row_id,
            source_fingerprint=self.source_fingerprint,
            instrument_slug=self.instrument_slug,
        )
        _require_nonnegative_counts(
            open_interest=self.open_interest,
            reported_long_total=self.reported_long_total,
            reported_short_total=self.reported_short_total,
        )


@dataclass(frozen=True)
class CotInstrumentDefinition:
    slug: str
    display_name: str
    cftc_code: str
    category: Category
    category_order: int
    instrument_order: int
    report_family: ReportFamily
    focal_participant: Participant
    participants: tuple[Participant, ...]
    price: PriceMapping

    def __post_init__(self) -> None:
        _require_nonempty(
            slug=self.slug,
            display_name=self.display_name,
            cftc_code=self.cftc_code,
        )
        _require_nonnegative_counts(
            category_order=self.category_order,
            instrument_order=self.instrument_order,
        )
        if self.focal_participant not in self.participants:
            raise ValueError("focal participant must be available for the report family")


@dataclass(frozen=True)
class DerivedParticipantPosition:
    participant: Participant
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

    def __post_init__(self) -> None:
        _require_nonnegative_counts(
            long=self.long,
            short=self.short,
            spreading=self.spreading,
        )
        _require_finite_optional(
            net_pct_open_interest=self.net_pct_open_interest,
            percentile_3y=self.percentile_3y,
        )
        if self.percentile_status not in {"available", "insufficient_history"}:
            raise ValueError("invalid percentile status")
        if (self.percentile_3y is None) != (
            self.percentile_status == "insufficient_history"
        ):
            raise ValueError("percentile value and status must agree")


@dataclass(frozen=True)
class DerivedCotWeek:
    source_dataset_id: str
    source_row_id: str
    source_fingerprint: str
    instrument_slug: str
    report_date: date
    open_interest: int
    positions: tuple[DerivedParticipantPosition, ...]

    def __post_init__(self) -> None:
        _require_nonempty(
            source_dataset_id=self.source_dataset_id,
            source_row_id=self.source_row_id,
            source_fingerprint=self.source_fingerprint,
            instrument_slug=self.instrument_slug,
        )
        _require_nonnegative_counts(open_interest=self.open_interest)


@dataclass(frozen=True)
class AlignedPrice:
    report_date: date
    price_date: date | None
    close: float | None
    weekly_change_pct: float | None

    def __post_init__(self) -> None:
        _require_finite_optional(
            close=self.close,
            weekly_change_pct=self.weekly_change_pct,
        )
        if self.price_date is None and self.close is not None:
            raise ValueError("price date is required when a close is available")
        if self.price_date is not None and self.close is None:
            raise ValueError("close is required when a price date is available")
        if self.price_date is not None and self.price_date > self.report_date:
            raise ValueError("aligned price cannot be later than the report date")


def _require_nonempty(**values: str) -> None:
    for field_name, value in values.items():
        if not value or not value.strip():
            raise ValueError(f"{field_name} must be non-empty")


def _require_nonnegative_counts(**values: int) -> None:
    for field_name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} must be a nonnegative integer")


def _require_finite_optional(**values: float | None) -> None:
    for field_name, value in values.items():
        if value is not None and not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite when provided")
