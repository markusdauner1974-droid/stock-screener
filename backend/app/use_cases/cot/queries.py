from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.cot.calculations import align_prices_to_report_dates
from app.domain.cot.models import PriceCoverageState
from app.domain.cot.registry import (
    CATEGORY_ORDER,
    COT_INSTRUMENTS,
    PARTICIPANT_LABELS,
    instrument_by_slug,
)
RANGE_WEEKS = {"1y": 52, "3y": 156, "5y": 260}
_NEW_YORK = ZoneInfo("America/New_York")


class CotPublicationUnavailable(LookupError):
    pass


class CotInstrumentUnavailable(LookupError):
    pass


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


class CotQueryService:
    def __init__(
        self,
        repository: Any,
        price_reader: Any,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._price_reader = price_reader
        self._now = now or (lambda: datetime.now(timezone.utc))

    @property
    def external_calls(self) -> list:
        return list(getattr(self._price_reader, "external_calls", []))

    def publication(self) -> CotPublicationView:
        publication = self._repository.get_publication()
        if publication is None:
            raise CotPublicationUnavailable("no published COT run")
        metadata = dict(publication.run.source_metadata_json or {})
        retrieved = metadata.get("retrieved_at")
        retrieved_at = (
            datetime.fromisoformat(retrieved)
            if isinstance(retrieved, str)
            else publication.run.published_at
            or datetime.now(timezone.utc)
        )
        age_days = (
            self._now().astimezone(_NEW_YORK).date()
            - publication.pointer.report_date
        ).days
        return CotPublicationView(
            schema_version=publication.run.schema_version,
            calculation_version=publication.run.calculation_version,
            registry_version=publication.run.registry_version,
            publication_id=publication.run.id,
            report_date=publication.pointer.report_date,
            retrieved_at=retrieved_at,
            stale=age_days > 10,
        )

    def catalog(self) -> CotCatalogView:
        publication = self.publication()
        return CotCatalogView(
            publication=publication,
            default_slug="sp-500",
            categories=tuple(category.value for category in CATEGORY_ORDER),
            sources=(
                CotSourceView(
                    dataset_id="72hh-3qpy",
                    label="CFTC Disaggregated Futures Only",
                    url="https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
                ),
                CotSourceView(
                    dataset_id="gpe5-46if",
                    label="CFTC Traders in Financial Futures - Futures Only",
                    url="https://publicreporting.cftc.gov/resource/gpe5-46if.json",
                ),
            ),
            instruments=tuple(
                CotCatalogInstrumentView(
                    slug=item.slug,
                    display_name=item.display_name,
                    category=item.category.value,
                    category_order=item.category_order,
                    instrument_order=item.instrument_order,
                    report_family=item.report_family.value,
                    focal_participant=item.focal_participant.value,
                    participants=tuple(participant.value for participant in item.participants),
                    price_symbol=item.price.yahoo_symbol,
                    price_mapping_kind=item.price.kind.value,
                    tradingview_url=item.price.tradingview_url,
                )
                for item in COT_INSTRUMENTS
            ),
        )

    def history(self, slug: str, range_name: str) -> CotHistoryView:
        if range_name not in RANGE_WEEKS:
            raise ValueError(f"unknown COT range: {range_name}")
        try:
            definition = instrument_by_slug(slug)
        except KeyError as exc:
            raise CotInstrumentUnavailable(slug) from exc
        publication = self.publication()
        rows = self._repository.get_history(slug, limit=RANGE_WEEKS[range_name])
        if not rows:
            raise CotInstrumentUnavailable(slug)
        grouped: dict[date, list[Any]] = defaultdict(list)
        for row in rows:
            grouped[row.report_date].append(row)
        report_dates = tuple(sorted(grouped))
        closes: Mapping[date, float] = {}
        if definition.price.yahoo_symbol is not None:
            closes = self._price_reader.closes(
                definition.price.yahoo_symbol,
                start=report_dates[0],
                end=report_dates[-1],
            )
        aligned = align_prices_to_report_dates(report_dates, closes)
        aligned_by_date = {item.report_date: item for item in aligned}
        aligned_count = sum(item.close is not None for item in aligned)
        coverage = (
            PriceCoverageState.UNAVAILABLE
            if aligned_count == 0
            else PriceCoverageState.COMPLETE
            if aligned_count == len(report_dates)
            else PriceCoverageState.PARTIAL
        )
        weeks = tuple(
            CotHistoryWeekView(
                report_date=report_date,
                open_interest=int(grouped[report_date][0].open_interest),
                price_date=aligned_by_date[report_date].price_date,
                price_close=aligned_by_date[report_date].close,
                price_change_pct=aligned_by_date[report_date].weekly_change_pct,
                positions=tuple(
                    CotPositionView(
                        participant=row.participant,
                        label=PARTICIPANT_LABELS[
                            next(p for p in definition.participants if p.value == row.participant)
                        ],
                        long=int(row.long),
                        short=int(row.short),
                        spreading=int(row.spreading),
                        net=int(row.net),
                        delta_long=row.delta_long,
                        delta_short=row.delta_short,
                        delta_net=row.delta_net,
                        net_pct_open_interest=row.net_pct_open_interest,
                        percentile_3y=row.percentile_3y,
                        percentile_status=row.percentile_status,
                    )
                    for row in sorted(
                        grouped[report_date],
                        key=lambda value: definition.participants.index(
                            next(p for p in definition.participants if p.value == value.participant)
                        ),
                    )
                ),
            )
            for report_date in report_dates
        )
        return CotHistoryView(
            publication=publication,
            range=range_name,
            slug=definition.slug,
            display_name=definition.display_name,
            category=definition.category.value,
            report_family=definition.report_family.value,
            source_dataset_id=(
                "gpe5-46if"
                if definition.report_family.value == "tff_futures_only"
                else "72hh-3qpy"
            ),
            focal_participant=definition.focal_participant.value,
            price_symbol=definition.price.yahoo_symbol,
            price_mapping_kind=definition.price.kind.value,
            price_coverage_state=coverage.value,
            price_history_start=min(closes) if closes else None,
            tradingview_url=definition.price.tradingview_url,
            weeks=weeks,
        )

    def snapshot(self) -> CotSnapshotView:
        publication = self.publication()
        rows: list[CotSnapshotRowView] = []
        for definition in COT_INSTRUMENTS:
            history = self.history(definition.slug, "1y")
            current = history.weeks[-1]
            focal = next(
                position
                for position in current.positions
                if position.participant == definition.focal_participant.value
            )
            trend = tuple(
                position.net
                for week in history.weeks[-12:]
                for position in week.positions
                if position.participant == definition.focal_participant.value
            )
            rows.append(
                CotSnapshotRowView(
                    slug=definition.slug,
                    display_name=definition.display_name,
                    category=definition.category.value,
                    instrument_order=definition.instrument_order,
                    focal_participant=focal.participant,
                    focal_label=focal.label,
                    report_date=current.report_date,
                    long=focal.long,
                    short=focal.short,
                    net=focal.net,
                    delta_long=focal.delta_long,
                    delta_short=focal.delta_short,
                    delta_net=focal.delta_net,
                    net_pct_open_interest=focal.net_pct_open_interest,
                    percentile_3y=focal.percentile_3y,
                    percentile_status=focal.percentile_status,
                    net_trend=trend,
                    price_change_pct=current.price_change_pct,
                    price_mapping_kind=history.price_mapping_kind,
                    price_coverage_state=history.price_coverage_state,
                )
            )
        return CotSnapshotView(publication=publication, rows=tuple(rows))
