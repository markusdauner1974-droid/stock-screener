from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260916_0045_add_cot_positioning.py"
)


def _load_migration():
    if not MIGRATION_PATH.is_file():
        pytest.fail(f"COT migration is missing: {MIGRATION_PATH}")
    spec = importlib.util.spec_from_file_location("cot_positioning_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_revision(engine, operation: str) -> None:
    module = _load_migration()
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original_op = module.op
        module.op = operations
        try:
            getattr(module, operation)()
        finally:
            module.op = original_op


def test_cot_migration_creates_constraints_and_cleanly_downgrades(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'cot.sqlite'}")

    _run_revision(engine, "upgrade")

    inspector = sa.inspect(engine)
    expected = {
        "cot_instruments",
        "cot_weekly_positions",
        "cot_import_runs",
        "cot_publication_pointers",
    }
    assert expected.issubset(inspector.get_table_names())
    unique_constraints = inspector.get_unique_constraints("cot_weekly_positions")
    assert {
        tuple(constraint["column_names"]) for constraint in unique_constraints
    } >= {("instrument_id", "report_date", "participant")}
    indexes = inspector.get_indexes("cot_weekly_positions")
    assert any(
        index["name"] == "ix_cot_weekly_instrument_date"
        and tuple(index["column_names"]) == ("instrument_id", "report_date")
        for index in indexes
    )

    _run_revision(engine, "downgrade")

    assert expected.isdisjoint(sa.inspect(engine).get_table_names())
    engine.dispose()
