from __future__ import annotations

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domain.cot.models import Participant
from app.infra.db.models.cot import (
    CotImportRun,
    CotInstrument,
    CotPublicationPointer,
    CotWeeklyPosition,
)
from app.infra.db.repositories.cot_repository import SqlCotRepository
from app.use_cases.cot.refresh import CotRefreshCommand, RefreshCotUseCase
from tests.unit.test_cot_refresh import FakePriceHydrator, FakeSource


def test_initial_no_change_and_corrected_publication_are_atomic():
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
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    source = FakeSource()
    use_case = RefreshCotUseCase(
        source=source,
        repository=SqlCotRepository(session),
        price_hydrator=FakePriceHydrator(),
    )
    try:
        first = use_case.execute(CotRefreshCommand(origin="test"))
        second = use_case.execute(CotRefreshCommand(origin="test"))
        assert first.status == "published"
        assert second.status == "no_change"
        assert session.get(CotPublicationPointer, "latest_published").run_id == 1

        before = _gold_focal_history(session)
        before_delta = before[156].delta_net
        before_percentile = before[156].percentile_3y
        source.correct_gold_week(155, long_delta=50)
        third = use_case.execute(CotRefreshCommand(origin="test"))
        session.expire_all()
        after = _gold_focal_history(session)

        assert third.status == "published"
        assert third.price_unavailable_count == 31
        assert session.get(CotPublicationPointer, "latest_published").run_id == 3
        assert after[156].delta_net != before_delta
        assert after[156].percentile_3y != before_percentile
    finally:
        session.close()
        engine.dispose()


def _gold_focal_history(session):
    return tuple(
        session.scalars(
            select(CotWeeklyPosition)
            .join(CotInstrument, CotInstrument.id == CotWeeklyPosition.instrument_id)
            .where(
                CotInstrument.slug == "gold",
                CotWeeklyPosition.participant == Participant.MANAGED_MONEY.value,
            )
            .order_by(CotWeeklyPosition.report_date)
        )
    )
