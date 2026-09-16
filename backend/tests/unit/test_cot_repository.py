from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, event
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


def derived_weeks(*, net: int = 40) -> tuple[DerivedCotWeek, ...]:
    return (
        DerivedCotWeek(
            source_dataset_id="72hh-3qpy",
            source_row_id="gold-2026-09-08",
            source_fingerprint=f"fingerprint-{net}",
            instrument_slug="gold",
            report_date=date(2026, 9, 8),
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
