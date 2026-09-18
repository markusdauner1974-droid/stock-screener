from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain.cot.models import (
    COT_CALCULATION_VERSION,
    COT_REGISTRY_VERSION,
    COT_SCHEMA_VERSION,
    NormalizedCotWeek,
    Participant,
    RawParticipantPosition,
)
from app.domain.cot.registry import COT_INSTRUMENTS
from app.use_cases.cot.ports import (
    CotPublicationSignature,
    CotSourceMetadata,
    CotSourceSnapshot,
)
from app.use_cases.cot.refresh import CotRefreshCommand, RefreshCotUseCase


def make_week(definition, report_date: date, sequence: int) -> NormalizedCotWeek:
    reportables = tuple(
        participant
        for participant in definition.participants
        if participant is not Participant.NONREPORTABLES
    )
    positions = []
    reported_long = 0
    reported_short = 0
    for participant in reportables:
        long_value = (
            200 + sequence if participant is definition.focal_participant else 100
        )
        short_value = 100
        positions.append(
            RawParticipantPosition(participant, long_value, short_value, 0)
        )
        reported_long += long_value
        reported_short += short_value
    open_interest = 2000
    positions.append(
        RawParticipantPosition(
            Participant.NONREPORTABLES,
            open_interest - reported_long,
            open_interest - reported_short,
            0,
        )
    )
    dataset_id = (
        "gpe5-46if"
        if definition.report_family.value == "tff_futures_only"
        else "72hh-3qpy"
    )
    return NormalizedCotWeek(
        source_dataset_id=dataset_id,
        source_row_id=f"{definition.slug}-{report_date.isoformat()}",
        source_fingerprint=f"{definition.slug}-{report_date.isoformat()}-{sequence}",
        instrument_slug=definition.slug,
        report_date=report_date,
        open_interest=open_interest,
        reported_long_total=reported_long,
        reported_short_total=reported_short,
        positions=tuple(positions),
    )


class FakeSource:
    def __init__(self) -> None:
        latest = date(2026, 9, 8)
        start = latest - timedelta(weeks=156)
        self.weeks = tuple(
            make_week(definition, start + timedelta(weeks=index), index)
            for definition in COT_INSTRUMENTS
            for index in range(157)
        )
        self.expected_counts = self._counts(self.weeks)

    @staticmethod
    def _counts(weeks):
        counts = {}
        for week in weeks:
            counts[week.source_dataset_id] = counts.get(week.source_dataset_id, 0) + 1
        return counts

    def fetch(self, _instruments):
        return CotSourceSnapshot(
            weeks=self.weeks,
            metadata=CotSourceMetadata(
                retrieved_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
                retry_count=0,
                dataset_row_counts=self._counts(self.weeks),
                expected_dataset_row_counts=self.expected_counts,
            ),
        )

    def correct_gold_week(self, index: int, long_delta: int) -> None:
        gold_weeks = [week for week in self.weeks if week.instrument_slug == "gold"]
        target = gold_weeks[index]
        corrected_positions = tuple(
            replace(position, long=position.long + long_delta)
            if position.participant is Participant.MANAGED_MONEY
            else replace(position, long=position.long - long_delta)
            if position.participant is Participant.NONREPORTABLES
            else position
            for position in target.positions
        )
        corrected = replace(
            target,
            source_fingerprint=f"{target.source_fingerprint}-corrected",
            reported_long_total=target.reported_long_total + long_delta,
            positions=corrected_positions,
        )
        self.weeks = tuple(corrected if week is target else week for week in self.weeks)


class FakeRepository:
    def __init__(self) -> None:
        self.next_run_id = 1
        self.published_run_id = None
        self.fingerprints = {}
        self.weeks = ()
        self.statuses = {}
        self.signature = None
        self.existing_key_slugs = ()
        self.publish_result = True

    @contextmanager
    def serialized_refresh(self):
        yield

    def start_run(self, _request):
        run_id = self.next_run_id
        self.next_run_id += 1
        self.statuses[run_id] = "staged"
        return run_id

    def existing_week_keys(self, instrument_slugs):
        self.existing_key_slugs = tuple(instrument_slugs)
        return frozenset(
            (week.instrument_slug, week.report_date)
            for week in self.weeks
            if week.instrument_slug in self.existing_key_slugs
        )

    def stored_fingerprints(self):
        return dict(self.fingerprints)

    def publication_signature(self):
        return self.signature

    def publish(self, run_id, *, registry, weeks, diagnostics, source_metadata):
        assert len(registry) == 31
        if not self.publish_result:
            self.statuses[run_id] = "superseded"
            return False
        self.weeks = tuple(weeks)
        self.fingerprints = {
            week.source_row_id: week.source_fingerprint for week in weeks
        }
        self.signature = CotPublicationSignature(
            source_fingerprints=self.fingerprints,
            registry_version=COT_REGISTRY_VERSION,
            calculation_version=COT_CALCULATION_VERSION,
            schema_version=COT_SCHEMA_VERSION,
        )
        self.published_run_id = run_id
        self.statuses[run_id] = "published"
        return True

    def mark_no_change(self, run_id, _diagnostics):
        self.statuses[run_id] = "no_change"

    def mark_failed(self, run_id, status, _diagnostics):
        self.statuses[run_id] = status

    def gold_position_at(self, index: int):
        weeks = sorted(
            (week for week in self.weeks if week.instrument_slug == "gold"),
            key=lambda week: week.report_date,
        )
        return next(
            position
            for position in weeks[index].positions
            if position.participant is Participant.MANAGED_MONEY
        )


@dataclass(frozen=True)
class FakePriceResult:
    unavailable_count: int = 31

    def as_dict(self):
        return {"unavailable_count": self.unavailable_count}


class FakePriceHydrator:
    def __init__(self):
        self.calls = 0
        self.report_dates = []

    def hydrate(self, _instruments, *, report_date):
        self.calls += 1
        self.report_dates.append(report_date)
        return FakePriceResult()


def make_use_case():
    source = FakeSource()
    repository = FakeRepository()
    return (
        RefreshCotUseCase(
            source=source,
            repository=repository,
            price_hydrator=FakePriceHydrator(),
        ),
        source,
        repository,
    )


def test_refresh_publishes_complete_valid_source_even_when_prices_fail():
    use_case, _source, repository = make_use_case()

    result = use_case.execute(CotRefreshCommand(origin="test", force=False))

    assert result.status == "published"
    assert result.instrument_count == 31
    assert result.price_unavailable_count == 31
    assert repository.published_run_id == result.run_id
    assert repository.existing_key_slugs == tuple(
        item.slug for item in COT_INSTRUMENTS
    )


def test_refresh_serializes_the_complete_fetch_to_publish_operation():
    class LockingRepository(FakeRepository):
        def __init__(self):
            super().__init__()
            self.lock_depth = 0

        @contextmanager
        def serialized_refresh(self):
            self.lock_depth += 1
            try:
                yield
            finally:
                self.lock_depth -= 1

        def publish(self, *args, **kwargs):
            assert self.lock_depth == 1
            return super().publish(*args, **kwargs)

    repository = LockingRepository()

    class LockAssertingSource(FakeSource):
        def fetch(self, instruments):
            assert repository.lock_depth == 1
            return super().fetch(instruments)

    use_case = RefreshCotUseCase(
        source=LockAssertingSource(),
        repository=repository,
        price_hydrator=FakePriceHydrator(),
    )

    result = use_case.execute(CotRefreshCommand(origin="test"))

    assert result.status == "published"
    assert repository.lock_depth == 0


def test_refresh_rejects_a_truncated_first_backfill():
    use_case, source, repository = make_use_case()
    source.weeks = tuple(
        week
        for week in source.weeks
        if week.instrument_slug != "gold" or week.report_date == date(2026, 9, 8)
    )

    result = use_case.execute(CotRefreshCommand(origin="test", force=False))

    assert result.status == "failed_quality"
    assert "insufficient_initial_history" in result.reason_codes
    assert "source_row_count_mismatch" in result.reason_codes
    assert repository.published_run_id is None


def test_refresh_no_change_does_not_move_pointer():
    source = FakeSource()
    repository = FakeRepository()
    price_hydrator = FakePriceHydrator()
    use_case = RefreshCotUseCase(
        source=source,
        repository=repository,
        price_hydrator=price_hydrator,
    )
    first = use_case.execute(CotRefreshCommand(origin="test", force=False))

    second = use_case.execute(CotRefreshCommand(origin="test", force=False))

    assert second.status == "no_change"
    assert second.price_unavailable_count == 31
    assert price_hydrator.calls == 2
    assert price_hydrator.report_dates == [date(2026, 9, 8)] * 2
    assert repository.published_run_id == first.run_id


def test_refresh_reports_a_superseded_publication_as_a_successful_noop():
    use_case, _source, repository = make_use_case()
    repository.publish_result = False

    result = use_case.execute(CotRefreshCommand(origin="test", force=True))

    assert result.status == "superseded"
    assert repository.statuses[result.run_id] == "superseded"


def test_refresh_republishes_when_calculation_version_changes():
    use_case, _source, repository = make_use_case()
    first = use_case.execute(CotRefreshCommand(origin="test", force=False))
    repository.signature = replace(
        repository.signature,
        calculation_version="cot-positions-old",
    )

    second = use_case.execute(CotRefreshCommand(origin="test", force=False))

    assert first.status == "published"
    assert second.status == "published"
    assert repository.published_run_id == second.run_id


def test_historical_correction_rebuilds_later_deltas_and_percentiles():
    use_case, source, repository = make_use_case()
    use_case.execute(CotRefreshCommand(origin="test", force=False))
    prior_delta = repository.gold_position_at(156).delta_net
    prior_percentile = repository.gold_position_at(156).percentile_3y
    source.correct_gold_week(155, long_delta=50)

    second = use_case.execute(CotRefreshCommand(origin="test", force=False))

    assert second.status == "published"
    assert repository.gold_position_at(156).delta_net != prior_delta
    assert repository.gold_position_at(156).percentile_3y != prior_percentile


def test_refresh_records_calculation_failures_by_phase(monkeypatch):
    use_case, _source, repository = make_use_case()
    monkeypatch.setattr(
        "app.use_cases.cot.refresh.derive_all_instrument_series",
        lambda _weeks: (_ for _ in ()).throw(RuntimeError("calculation failed")),
    )

    with pytest.raises(RuntimeError, match="calculation failed"):
        use_case.execute(CotRefreshCommand(origin="test"))

    assert repository.statuses[1] == "failed_calculation"


def test_refresh_records_price_hydration_failures_by_phase():
    source = FakeSource()
    repository = FakeRepository()

    class FailingPriceHydrator:
        def hydrate(self, _instruments, *, report_date):
            raise RuntimeError("price hydration failed")

    use_case = RefreshCotUseCase(
        source=source,
        repository=repository,
        price_hydrator=FailingPriceHydrator(),
    )

    with pytest.raises(RuntimeError, match="price hydration failed"):
        use_case.execute(CotRefreshCommand(origin="test"))

    assert repository.statuses[1] == "failed_price_hydration"


def test_refresh_records_publication_failures_by_phase():
    source = FakeSource()

    class FailingPublishRepository(FakeRepository):
        def publish(self, *args, **kwargs):
            raise RuntimeError("publish failed")

    repository = FailingPublishRepository()
    use_case = RefreshCotUseCase(
        source=source,
        repository=repository,
        price_hydrator=FakePriceHydrator(),
    )

    with pytest.raises(RuntimeError, match="publish failed"):
        use_case.execute(CotRefreshCommand(origin="test"))

    assert repository.statuses[1] == "failed_publish"
