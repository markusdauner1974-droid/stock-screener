"""Upgrade legacy theme state with and without the optional freshness marker."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize("has_source_marker", [True, False])
def test_upgrade_preserves_memberships_and_work_when_marker_is_absent(
    has_source_marker,
):
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20260912_0044_theme_state_authorities.py"
    )
    spec = importlib.util.spec_from_file_location("theme_state_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE theme_development_observations (id INTEGER PRIMARY KEY, theme_ids JSON NOT NULL, facts JSON NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE theme_development_themes (observation_id INTEGER, theme_id INTEGER, PRIMARY KEY (observation_id, theme_id))"
        )
        marker = (
            ", source_marker INTEGER NOT NULL DEFAULT 0" if has_source_marker else ""
        )
        connection.exec_driver_sql(
            f"CREATE TABLE theme_development_work (id INTEGER PRIMARY KEY, status TEXT NOT NULL{marker})"
        )
        connection.exec_driver_sql(
            'INSERT INTO theme_development_observations VALUES (1, \'[2, 3, 3]\', \'{"theme_ids": [2, 3], "summary": "keep"}\')'
        )
        connection.exec_driver_sql(
            "INSERT INTO theme_development_themes VALUES (1, 2), (1, 4)"
        )
        connection.exec_driver_sql(
            "INSERT INTO theme_development_work (id, status) VALUES (7, 'pending')"
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        columns = {
            c["name"]
            for c in sa.inspect(connection).get_columns("theme_development_work")
        }
        assert "source_marker" not in columns
        assert "checked_at" in columns
        assert connection.exec_driver_sql(
            "SELECT status, checked_at IS NOT NULL FROM theme_development_work WHERE id = 7"
        ).one() == ("pending", 1)
        assert connection.exec_driver_sql(
            "SELECT theme_id FROM theme_development_themes ORDER BY theme_id"
        ).scalars().all() == [2, 3, 4]
        assert "theme_ids" not in {
            c["name"]
            for c in sa.inspect(connection).get_columns(
                "theme_development_observations"
            )
        }
        facts = connection.execute(
            sa.select(sa.column("facts", sa.JSON)).select_from(
                sa.table("theme_development_observations")
            )
        ).scalar_one()
        assert facts == {"summary": "keep"}
    engine.dispose()
