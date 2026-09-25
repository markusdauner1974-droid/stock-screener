from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260922_0055_economic_taxonomy_benchmarks.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("economic_benchmarks_0055", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_migration_adds_and_removes_durable_result_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'benchmark.sqlite'}")
    migration = _load_migration()
    try:
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

        schema = inspect(engine)
        assert migration.down_revision == "20260921_0054"
        assert "economic_taxonomy_benchmark_results" in schema.get_table_names()
        assert any(
            constraint["name"] == "uq_economic_taxonomy_benchmark_result"
            for constraint in schema.get_unique_constraints(
                "economic_taxonomy_benchmark_results"
            )
        )

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
        assert "economic_taxonomy_benchmark_results" not in inspect(
            engine
        ).get_table_names()
    finally:
        engine.dispose()
