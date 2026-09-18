from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone

from app.domain.cot.calculations import align_prices_to_report_dates
from app.domain.cot.models import (
    COT_CALCULATION_VERSION,
    COT_REGISTRY_VERSION,
    COT_SCHEMA_VERSION,
    PriceCoverageState,
    is_cot_publication_stale,
)
from app.domain.cot.registry import (
    CATEGORY_ORDER,
    COT_DATASETS,
    COT_INSTRUMENTS,
    PARTICIPANT_LABELS,
    dataset_for_family,
    instrument_by_slug,
)
from app.use_cases.cot.ports import (
    CotHistoryPositionRecord,
    CotPriceReader,
    CotReadRepository,
    CotSnapshotPositionRecord,
)
from app.use_cases.cot.read_models import (
    CotCatalogInstrumentView,
    CotCatalogView,
    CotHistoryView,
    CotHistoryWeekView,
    CotPositionView,
    CotPublicationView,
    CotSnapshotRowView,
    CotSnapshotView,
    CotSourceView,
)

RANGE_WEEKS = {"1y": 52, "3y": 156, "5y": 260}


class CotPublicationUnavailable(LookupError):
    pass


class CotInstrumentUnavailable(LookupError):
    pass


class CotQueryService:
    def __init__(
        self,
        repository: CotReadRepository,
        price_reader: CotPriceReader,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._price_reader = price_reader
        self._now = now or (lambda: datetime.now(timezone.utc))

    def publication(self) -> CotPublicationView:
        publication = self._repository.get_publication()
        if publication is None:
            raise CotPublicationUnavailable("no published COT run")
        if publication.run.registry_version != COT_REGISTRY_VERSION:
            raise CotPublicationUnavailable(
                "published COT registry is incompatible with the deployed registry"
            )
        if publication.run.schema_version != COT_SCHEMA_VERSION:
            raise CotPublicationUnavailable(
                "published COT schema is incompatible with the deployed schema"
            )
        if publication.run.calculation_version != COT_CALCULATION_VERSION:
            raise CotPublicationUnavailable(
                "published COT calculation is incompatible with the deployed calculation"
            )
        metadata = dict(publication.run.source_metadata_json or {})
        retrieved = metadata.get("retrieved_at")
        retrieved_at = (
            datetime.fromisoformat(retrieved)
            if isinstance(retrieved, str)
            else publication.run.published_at or datetime.now(timezone.utc)
        )
        return CotPublicationView(
            schema_version=publication.run.schema_version,
            calculation_version=publication.run.calculation_version,
            registry_version=publication.run.registry_version,
            publication_id=publication.run.id,
            report_date=publication.pointer.report_date,
            retrieved_at=retrieved_at,
            stale=is_cot_publication_stale(
                publication.pointer.report_date,
                at=self._now(),
            ),
        )

    def catalog(
        self,
        *,
        publication: CotPublicationView | None = None,
    ) -> CotCatalogView:
        publication = publication or self.publication()
        return CotCatalogView(
            publication=publication,
            default_slug="sp-500",
            categories=tuple(category.value for category in CATEGORY_ORDER),
            sources=tuple(
                CotSourceView(
                    dataset_id=dataset.dataset_id.value,
                    label=dataset.label,
                    url=dataset.url,
                )
                for dataset in COT_DATASETS
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
                    participants=tuple(
                        participant.value for participant in item.participants
                    ),
                    price_symbol=item.price.yahoo_symbol,
                    price_mapping_kind=item.price.kind.value,
                    tradingview_url=item.price.tradingview_url,
                )
                for item in COT_INSTRUMENTS
            ),
        )

    def history(
        self,
        slug: str,
        range_name: str,
        *,
        publication: CotPublicationView | None = None,
    ) -> CotHistoryView:
        if range_name not in RANGE_WEEKS:
            raise ValueError(f"unknown COT range: {range_name}")
        try:
            definition = instrument_by_slug(slug)
        except KeyError as exc:
            raise CotInstrumentUnavailable(slug) from exc
        fixed_publication = publication is not None
        publication = publication or self.publication()
        requested_weeks = RANGE_WEEKS[range_name]
        for attempt in range(2):
            rows = self._repository.get_history(slug, limit=requested_weeks + 1)
            current_publication = self.publication()
            if current_publication.publication_id == publication.publication_id:
                break
            if fixed_publication or attempt == 1:
                raise CotPublicationUnavailable("COT publication changed during read")
            publication = current_publication
        if not rows:
            raise CotInstrumentUnavailable(slug)
        grouped: dict[date, list[CotHistoryPositionRecord]] = defaultdict(list)
        for row in rows:
            grouped[row.report_date].append(row)
        alignment_dates = tuple(sorted(grouped))
        report_dates = alignment_dates[-requested_weeks:]
        closes: Mapping[date, float] = {}
        if definition.price.yahoo_symbol is not None:
            closes = self._price_reader.closes(
                definition.price.yahoo_symbol,
                start=alignment_dates[0] - timedelta(days=7),
                end=alignment_dates[-1],
            )
        aligned = align_prices_to_report_dates(alignment_dates, closes)
        aligned_by_date = {item.report_date: item for item in aligned}
        aligned_count = sum(
            aligned_by_date[item].close is not None for item in report_dates
        )
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
                            next(
                                p
                                for p in definition.participants
                                if p.value == row.participant
                            )
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
                            next(
                                p
                                for p in definition.participants
                                if p.value == value.participant
                            )
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
            source_dataset_id=dataset_for_family(
                definition.report_family
            ).dataset_id.value,
            focal_participant=definition.focal_participant.value,
            price_symbol=definition.price.yahoo_symbol,
            price_mapping_kind=definition.price.kind.value,
            price_coverage_state=coverage.value,
            price_history_start=next(
                (week.price_date for week in weeks if week.price_date is not None),
                None,
            ),
            tradingview_url=definition.price.tradingview_url,
            weeks=weeks,
        )

    def snapshot(
        self,
        *,
        publication: CotPublicationView | None = None,
    ) -> CotSnapshotView:
        fixed_publication = publication is not None
        publication = publication or self.publication()
        for attempt in range(2):
            records = self._repository.get_snapshot_history(weeks=RANGE_WEEKS["1y"])
            current_publication = self.publication()
            if current_publication.publication_id == publication.publication_id:
                break
            if fixed_publication or attempt == 1:
                raise CotPublicationUnavailable("COT publication changed during read")
            publication = current_publication
        history_by_slug: dict[str, list[CotSnapshotPositionRecord]] = defaultdict(list)
        for record in records:
            history_by_slug[record.instrument_slug].append(record)

        price_requests: dict[str, tuple[date, date]] = {}
        for definition in COT_INSTRUMENTS:
            history = history_by_slug.get(definition.slug, [])
            if not history:
                raise CotInstrumentUnavailable(definition.slug)
            history.sort(key=lambda item: item.report_date)
            symbol = definition.price.yahoo_symbol
            if symbol is not None:
                requested = (
                    history[0].report_date - timedelta(days=7),
                    history[-1].report_date,
                )
                existing = price_requests.get(symbol)
                price_requests[symbol] = (
                    (
                        min(existing[0], requested[0]),
                        max(existing[1], requested[1]),
                    )
                    if existing
                    else requested
                )
        closes_by_symbol = self._price_reader.closes_many(price_requests)

        rows: list[CotSnapshotRowView] = []
        for definition in COT_INSTRUMENTS:
            history = history_by_slug[definition.slug]
            report_dates = tuple(item.report_date for item in history)
            closes = (
                closes_by_symbol.get(definition.price.yahoo_symbol, {})
                if definition.price.yahoo_symbol is not None
                else {}
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
            current = history[-1]
            current_price = aligned_by_date[current.report_date]
            rows.append(
                CotSnapshotRowView(
                    slug=definition.slug,
                    display_name=definition.display_name,
                    category=definition.category.value,
                    instrument_order=definition.instrument_order,
                    focal_participant=current.participant,
                    focal_label=PARTICIPANT_LABELS[definition.focal_participant],
                    report_date=current.report_date,
                    long=current.long,
                    short=current.short,
                    net=current.net,
                    delta_long=current.delta_long,
                    delta_short=current.delta_short,
                    delta_net=current.delta_net,
                    net_pct_open_interest=current.net_pct_open_interest,
                    percentile_3y=current.percentile_3y,
                    percentile_status=current.percentile_status,
                    net_trend=tuple(item.net for item in history[-12:]),
                    price_change_pct=current_price.weekly_change_pct,
                    price_mapping_kind=definition.price.kind.value,
                    price_coverage_state=coverage.value,
                )
            )
        return CotSnapshotView(publication=publication, rows=tuple(rows))
