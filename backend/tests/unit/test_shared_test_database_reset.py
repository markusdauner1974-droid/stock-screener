"""The shared test database fixture must rebuild after any DDL, even one command."""

from sqlalchemy import inspect

from app.database import Base, engine
from tests.conftest import _reset_test_database


def test_single_ddl_command_after_tracker_install_forces_schema_rebuild():
    if engine.dialect.name == "postgresql":
        # Reinstall the tracker so the epoch sequence is brand new, as on a fresh database.
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA IF EXISTS pytest_meta CASCADE")
        _reset_test_database()

    table = Base.metadata.sorted_tables[-1]  # nothing references the last table
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP TABLE "{table.name}"')

    _reset_test_database()

    assert inspect(engine).has_table(table.name)
