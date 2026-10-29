"""Feature-store rows whose indexed numeric detail is not a number (#624).

PostgreSQL evaluates each ``CAST(<details> ->> 'key' AS FLOAT)`` expression
index on every row it writes, so a value the cast rejects fails the INSERT,
and with it the whole 500-row upsert batch and the snapshot publish.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.database import engine
from app.domain.feature_store.models import FeatureRowWrite
from app.infra.db.models.feature_store import FeatureRun, StockFeatureDaily
from app.infra.db.portability import json_number
from app.infra.db.repositories.feature_store_repo import SqlFeatureStoreRepository

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql", reason="needs PostgreSQL expression indexes"
)

AS_OF = date(2026, 2, 17)
MIGRATIONS = Path(__file__).parents[2] / "alembic" / "versions"
# Values each float cast rejects: text, empty, out of range, JSON true, object.
BAD_VALUES = {
    "rs_rating": "n/a",
    "stage": "",
    "resilience_score": "1e400",
    "ibd_group_rank": True,
    "avg_dollar_volume": {"usd": 1},
}


def _load(name: str):
    path = next(MIGRATIONS.glob(f"{name}_*.py"))
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def float_cast_indexes(db_session):
    """The 0021/0028/0057 details_json and 0064 table_details_json indexes."""
    connection = db_session.connection()
    op = Operations(MigrationContext.configure(connection))
    details_indexes = [
        (migration, field)
        for migration, fields in (
            (_load("20260617_0021"), None),
            (_load("20260925_0057"), None),
            (_load("20260821_0028"), ["resilience_score"]),
        )
        for field in fields or migration._FIELDS
    ]
    for migration, field in details_indexes:
        # 0057 builds CONCURRENTLY, which cannot run inside the test transaction.
        connection.exec_driver_sql(
            f"CREATE INDEX {migration._index_name(field)} "
            f"ON stock_feature_daily (run_id, ({migration._index_expr(field)}))"
        )
    table_details = _load("20261011_0064")
    table_details.op = op
    table_details._create_indexes()
    yield
    db_session.rollback()  # PostgreSQL DDL is transactional: drops the indexes too


def _run(db_session) -> FeatureRun:
    run = FeatureRun(as_of_date=AS_OF, run_type="daily_snapshot", status="running")
    db_session.add(run)
    db_session.flush()
    return run


def _rs_rating_above_zero(db_session, run_id: int) -> list[str]:
    return list(
        db_session.scalars(
            select(StockFeatureDaily.symbol)
            .where(StockFeatureDaily.run_id == run_id)
            .where(json_number(StockFeatureDaily.details_json, ("rs_rating",)) > 0)
            .order_by(json_number(StockFeatureDaily.details_json, ("rs_rating",)))
        )
    )


def test_upsert_publishes_a_row_whose_indexed_numeric_detail_is_not_a_number(
    db_session, float_cast_indexes
):
    run = _run(db_session)
    rows = [
        FeatureRowWrite("BAD", AS_OF, 50.0, 3, 1, dict(BAD_VALUES)),
        FeatureRowWrite("GOOD", AS_OF, 60.0, 4, 2, {"rs_rating": 90, "stage": "2"}),
    ]

    assert SqlFeatureStoreRepository(db_session).upsert_snapshot_rows(run.id, rows) == 2

    bad = db_session.get(StockFeatureDaily, (run.id, "BAD"))
    db_session.refresh(bad)
    assert {key: bad.details_json[key] for key in BAD_VALUES} == dict.fromkeys(BAD_VALUES)
    good = db_session.get(StockFeatureDaily, (run.id, "GOOD"))
    db_session.refresh(good)
    assert good.details_json["stage"] == "2"  # a numeric string still casts
    assert _rs_rating_above_zero(db_session, run.id) == ["GOOD"]


def test_orm_write_of_a_non_numeric_indexed_detail_stores_it_as_missing(
    db_session, float_cast_indexes
):
    run = _run(db_session)
    row = StockFeatureDaily(
        run_id=run.id, symbol="BAD", as_of_date=AS_OF, details_json=dict(BAD_VALUES)
    )
    db_session.add(row)
    db_session.flush()

    row.details_json = {**row.details_json, "rs_rating": "pending"}
    db_session.flush()

    db_session.refresh(row)
    assert {key: row.details_json[key] for key in BAD_VALUES} == dict.fromkeys(BAD_VALUES)
    assert _rs_rating_above_zero(db_session, run.id) == []
