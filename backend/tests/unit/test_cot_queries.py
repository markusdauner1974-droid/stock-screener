from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.domain.cot.registry import COT_INSTRUMENTS
from app.use_cases.cot.queries import CotPublicationUnavailable, CotQueryService


class FakeRepository:
    def __init__(self):
        run = SimpleNamespace(
            id=7,
            registry_version="cot-curated-v1",
            calculation_version="cot-positions-v1",
            schema_version="cot-v1",
            source_metadata_json={"retrieved_at": "2026-09-11T20:45:00+00:00"},
        )
        pointer = SimpleNamespace(run_id=7, report_date=date(2026, 9, 8))
        self.publication = SimpleNamespace(run=run, pointer=pointer)
        self.history_calls = []
        self.snapshot_history_calls = []

    def get_publication(self):
        return self.publication

    def get_instruments(self):
        return tuple(
            SimpleNamespace(
                slug=item.slug,
                display_name=item.display_name,
                category=item.category.value,
                category_order=item.category_order,
                instrument_order=item.instrument_order,
                report_family=item.report_family.value,
                focal_participant=item.focal_participant.value,
            )
            for item in COT_INSTRUMENTS
        )

    def get_history(self, slug, *, limit=None):
        self.history_calls.append((slug, limit))
        return self._history_rows(slug, limit=limit)

    @staticmethod
    def _history_rows(slug, *, limit=None):
        definition = next(item for item in COT_INSTRUMENTS if item.slug == slug)
        latest = date(2026, 9, 8)
        weeks = []
        for week_index in range(60):
            report_date = latest - timedelta(weeks=59 - week_index)
            for participant_index, participant in enumerate(definition.participants):
                net = week_index * 10 + participant_index
                weeks.append(
                    SimpleNamespace(
                        report_date=report_date,
                        participant=participant.value,
                        long=1000 + net,
                        short=1000,
                        spreading=0,
                        open_interest=10_000,
                        net=net,
                        delta_long=10 if week_index else None,
                        delta_short=0 if week_index else None,
                        delta_net=10 if week_index else None,
                        net_pct_open_interest=net / 100,
                        percentile_3y=75.0,
                        percentile_status="available",
                    )
                )
        if limit is not None:
            selected_dates = sorted({row.report_date for row in weeks})[-limit:]
            weeks = [row for row in weeks if row.report_date in selected_dates]
        return tuple(weeks)

    def get_snapshot_history(self, *, weeks):
        self.snapshot_history_calls.append(weeks)
        return tuple(
            SimpleNamespace(instrument_slug=definition.slug, **vars(row))
            for definition in COT_INSTRUMENTS
            for row in self._history_rows(definition.slug, limit=weeks)
            if row.participant == definition.focal_participant.value
        )

    def get_snapshot(self):
        return tuple(
            row
            for definition in COT_INSTRUMENTS
            for row in self.get_history(definition.slug, limit=1)
        )


class FakePriceReader:
    def __init__(self):
        self.external_calls = []
        self.requests = []
        self.batch_calls = []

    def closes(self, symbol, *, start, end):
        self.requests.append((symbol, start, end))
        return {
            start + timedelta(days=index): 100.0 + index
            for index in range((end - start).days + 1)
        }

    def closes_many(self, requests):
        self.batch_calls.append(dict(requests))
        return {
            symbol: self.closes(symbol, start=start, end=end)
            for symbol, (start, end) in requests.items()
        }


class PreRangeOnlyPriceReader(FakePriceReader):
    def closes(self, symbol, *, start, end):
        self.requests.append((symbol, start, end))
        return {
            start + timedelta(days=7): 99.0,
            start + timedelta(days=14): 100.0,
        }


def service():
    return CotQueryService(
        FakeRepository(),
        FakePriceReader(),
        now=lambda: datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


def test_history_uses_week_counts_and_cached_prices_only():
    repository = FakeRepository()
    price_reader = FakePriceReader()
    query_service = CotQueryService(
        repository,
        price_reader,
        now=lambda: datetime(2026, 9, 12, tzinfo=timezone.utc),
    )

    history = query_service.history("sp-500", "1y")

    assert len(history.weeks) == 52
    assert history.weeks[-1].report_date.isoformat() == "2026-09-08"
    assert history.weeks[-1].price_date <= history.weeks[-1].report_date
    assert history.weeks[0].price_change_pct is not None
    assert repository.history_calls == [("sp-500", 53)]
    assert price_reader.external_calls == []


def test_history_reads_pre_range_close_for_first_report_alignment():
    repository = FakeRepository()
    price_reader = PreRangeOnlyPriceReader()
    query_service = CotQueryService(repository, price_reader)

    history = query_service.history("sp-500", "1y")

    first_report = history.weeks[0].report_date
    assert price_reader.requests[0][1] == first_report - timedelta(days=14)
    assert history.weeks[0].price_date == first_report
    assert history.weeks[0].price_close == 100.0
    assert history.weeks[0].price_change_pct == 100.0 / 99.0


def test_snapshot_preserves_registry_order_and_focal_participants():
    rows = service().snapshot().rows

    assert [row.slug for row in rows[:3]] == ["sp-500", "nasdaq-100", "russell-2000"]
    assert (
        next(row for row in rows if row.slug == "sp-500").focal_participant
        == "leveraged_funds"
    )
    assert (
        next(row for row in rows if row.slug == "gold").focal_participant
        == "managed_money"
    )
    assert len(next(row for row in rows if row.slug == "gold").net_trend) == 12


def test_snapshot_uses_one_repository_batch_and_one_price_batch():
    repository = FakeRepository()
    price_reader = FakePriceReader()
    query_service = CotQueryService(repository, price_reader)

    snapshot = query_service.snapshot()

    assert len(snapshot.rows) == 31
    assert repository.history_calls == []
    assert repository.snapshot_history_calls == [52]
    assert len(price_reader.batch_calls) == 1


def test_catalog_exposes_all_official_sources_and_curated_entries():
    catalog = service().catalog()

    assert catalog.default_slug == "sp-500"
    assert len(catalog.instruments) == 31
    assert {source.dataset_id for source in catalog.sources} == {
        "72hh-3qpy",
        "gpe5-46if",
    }


def test_queries_reject_a_publication_from_an_incompatible_registry():
    repository = FakeRepository()
    repository.publication.run.registry_version = "cot-curated-old"
    query_service = CotQueryService(repository, FakePriceReader())

    with pytest.raises(CotPublicationUnavailable, match="registry"):
        query_service.catalog()
