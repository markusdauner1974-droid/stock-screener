from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domain.cot.models import (
    DerivedCotWeek,
    DerivedParticipantPosition,
    Participant,
)
from app.domain.cot.registry import COT_INSTRUMENTS
from app.infra.db.models.cot import (
    CotImportRun,
    CotInstrument,
    CotPublicationPointer,
    CotWeeklyPosition,
)
from app.infra.db.repositories.cot_repository import SqlCotRepository
from app.use_cases.cot.ports import CotRunRequest


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[
            CotInstrument.__table__,
            CotImportRun.__table__,
            CotWeeklyPosition.__table__,
            CotPublicationPointer.__table__,
        ],
    )
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def repository(session):
    return SqlCotRepository(session)


def run_request() -> CotRunRequest:
    return CotRunRequest(origin="test", expected_instrument_count=31)


def derived_weeks(
    *,
    net: int = 40,
    report_date: date = date(2026, 9, 8),
) -> tuple[DerivedCotWeek, ...]:
    return (
        DerivedCotWeek(
            source_dataset_id="72hh-3qpy",
            source_row_id=f"gold-{report_date.isoformat()}",
            source_fingerprint=f"fingerprint-{net}",
            instrument_slug="gold",
            report_date=report_date,
            open_interest=1000,
            positions=(
                DerivedParticipantPosition(
                    participant=Participant.MANAGED_MONEY,
                    long=100 + net,
                    short=100,
                    spreading=0,
                    net=net,
                    delta_long=5,
                    delta_short=0,
                    delta_net=5,
                    net_pct_open_interest=net / 10,
                    percentile_3y=75.0,
                    percentile_status="available",
                ),
            ),
        ),
    )


def test_publish_upserts_history_and_advances_pointer_in_one_commit(
    repository, session
):
    run_id = repository.start_run(run_request())

    repository.publish(run_id, registry=COT_INSTRUMENTS, weeks=derived_weeks())

    pointer = session.get(CotPublicationPointer, "latest_published")
    assert pointer.run_id == run_id
    assert repository.get_publication().run.status == "published"
    assert session.query(CotWeeklyPosition).one().net == 40
    signature = repository.publication_signature()
    assert signature.registry_version == run_request().registry_version
    assert signature.calculation_version == run_request().calculation_version
    assert signature.schema_version == run_request().schema_version
    assert dict(signature.source_fingerprints) == {"gold-2026-09-08": "fingerprint-40"}
    snapshot_rows = repository.get_snapshot_history(weeks=52)
    assert [
        (row.instrument_slug, row.participant, row.net) for row in snapshot_rows
    ] == [("gold", Participant.MANAGED_MONEY.value, 40)]


def test_failed_publish_keeps_previous_pointer(repository, session):
    first_run_id = repository.start_run(run_request())
    repository.publish(
        first_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(),
    )
    second_run_id = repository.start_run(run_request())
    duplicated = derived_weeks() + derived_weeks()

    with pytest.raises(IntegrityError):
        repository.publish(
            second_run_id,
            registry=COT_INSTRUMENTS,
            weeks=duplicated,
        )
    session.rollback()

    assert session.get(CotPublicationPointer, "latest_published").run_id == first_run_id
    assert session.get(CotImportRun, second_run_id).status == "staged"


def test_later_publication_updates_canonical_row_and_pointer(repository, session):
    first_run_id = repository.start_run(run_request())
    repository.publish(
        first_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(),
    )
    second_run_id = repository.start_run(run_request())

    repository.publish(
        second_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(net=55),
    )

    assert session.query(CotWeeklyPosition).count() == 1
    assert session.query(CotWeeklyPosition).one().net == 55
    assert (
        session.get(CotPublicationPointer, "latest_published").run_id == second_run_id
    )


def test_older_run_cannot_overwrite_a_newer_publication(repository, session):
    older_run_id = repository.start_run(run_request())
    newer_run_id = repository.start_run(run_request())
    assert repository.publish(
        newer_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(net=55),
    ) is True

    published = repository.publish(
        older_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(net=40),
    )

    assert published is False
    assert session.get(CotPublicationPointer, "latest_published").run_id == newer_run_id
    assert session.query(CotWeeklyPosition).one().net == 55
    assert session.get(CotImportRun, older_run_id).status == "superseded"


def test_newer_run_cannot_roll_publication_back_to_an_older_report_date(
    repository, session
):
    current_run_id = repository.start_run(run_request())
    repository.publish(
        current_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(net=55),
    )
    backfill_run_id = repository.start_run(run_request())

    published = repository.publish(
        backfill_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(net=40, report_date=date(2026, 9, 1)),
    )

    assert published is False
    assert session.get(CotPublicationPointer, "latest_published").run_id == current_run_id
    assert session.query(CotWeeklyPosition).one().net == 55
    assert session.get(CotImportRun, backfill_run_id).status == "superseded"


def test_history_repopulates_cached_positions_after_an_external_publish(
    repository, session
):
    run_id = repository.start_run(run_request())
    repository.publish(run_id, registry=COT_INSTRUMENTS, weeks=derived_weeks())
    cached = repository.get_history("gold")[0]
    session.commit()
    with session.get_bind().begin() as connection:
        connection.execute(
            update(CotWeeklyPosition).values(long=155, net=55)
        )

    refreshed = repository.get_history("gold")[0]

    assert refreshed is cached
    assert refreshed.long == 155
    assert refreshed.net == 55


def test_registry_slug_rename_reuses_the_existing_cftc_instrument(repository, session):
    gold = next(item for item in COT_INSTRUMENTS if item.slug == "gold")
    first_run_id = repository.start_run(run_request())
    repository.publish(
        first_run_id,
        registry=(gold,),
        weeks=derived_weeks(),
    )
    original_id = session.query(CotInstrument).one().id
    renamed_gold = replace(gold, slug="gold-futures")
    renamed_week = replace(derived_weeks(net=55)[0], instrument_slug="gold-futures")
    second_run_id = repository.start_run(run_request())

    repository.publish(
        second_run_id,
        registry=(renamed_gold,),
        weeks=(renamed_week,),
    )

    instrument = session.query(CotInstrument).one()
    assert instrument.id == original_id
    assert instrument.slug == "gold-futures"
    assert instrument.cftc_code == gold.cftc_code
    assert session.query(CotWeeklyPosition).one().net == 55


def test_no_change_run_does_not_move_publication_pointer(repository, session):
    published_run_id = repository.start_run(run_request())
    repository.publish(
        published_run_id,
        registry=COT_INSTRUMENTS,
        weeks=derived_weeks(),
    )
    no_change_run_id = repository.start_run(run_request())

    repository.mark_no_change(no_change_run_id, {"valid": True})

    assert session.get(CotImportRun, no_change_run_id).status == "no_change"
    assert (
        session.get(CotPublicationPointer, "latest_published").run_id
        == published_run_id
    )


def test_existing_week_keys_are_scoped_to_the_incoming_registry(repository):
    run_id = repository.start_run(run_request())
    repository.publish(run_id, registry=COT_INSTRUMENTS, weeks=derived_weeks())

    assert repository.existing_week_keys(("sp-500",)) == frozenset()
    assert repository.existing_week_keys(("gold",)) == frozenset(
        {("gold", date(2026, 9, 8))}
    )


def test_mark_failed_recovers_a_session_left_in_pending_rollback(repository, session):
    run_id = repository.start_run(run_request())
    session.add(
        CotImportRun(
            id=run_id,
            origin="duplicate",
            status="staged",
            expected_instrument_count=31,
            observed_instrument_count=0,
            registry_version="cot-curated-v1",
            calculation_version="cot-positions-v1",
            schema_version="cot-v1",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()

    repository.mark_failed(run_id, "failed_publish", {"exception_type": "test"})

    assert session.get(CotImportRun, run_id).status == "failed_publish"
