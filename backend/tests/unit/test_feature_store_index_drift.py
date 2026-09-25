"""Drift guard for the feature-store preset-filter expression indexes.

Migration ``20260617_0021`` creates Postgres expression indexes whose SQL must
stay byte-identical (minus the table qualifier) to what the query builder
compiles for the same field — otherwise the planner silently declines the
index and the filter falls back to a full scan with no error. This test pins
that linkage so a change to ``json_number`` / ``_JSON_FIELD_MAP`` can't rot the
indexes unnoticed.

It also enforces that every indexed field is a *flat* top-level details_json
key, since the migration's ``_index_expr`` only emits the single-segment
``details_json ->> 'field'`` form (a nested path needs a different expression).
"""

from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_mock_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.domain.common.query import BooleanFilter
from app.domain.scanning.filter_expression_model import FilterExpression
from app.infra.db.models.feature_store import StockFeatureDaily
from app.infra.db.portability import json_number
from app.infra.query.feature_store_query import (
    _FIELD_BINDINGS,
    compile_filter_expression,
)

_MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260617_0021_add_feature_store_preset_filter_indexes.py"
)
_DAILY_SNAPSHOT_MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260925_0046_add_avg_dollar_volume_filter_indexes.py"
)
_CORRECTION_SURVIVORS_MIGRATION = (
    Path(__file__).parents[2]
    / "alembic"
    / "versions"
    / "20260821_0028_seed_correction_survivors_preset.py"
)


def _load_migration(path: Path = _MIGRATION):
    assert path.exists(), f"migration is missing: {path.name}"
    spec = importlib.util.spec_from_file_location(f"_wsb_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _builder_expr(field: str) -> str:
    """The flat extraction the query builder compiles for *field* on Postgres,
    minus the table qualifier (the index DDL is unqualified).

    Compiled WITHOUT ``literal_binds`` on purpose: this is the runtime form, so
    if the JSON key ever regresses to a bind parameter (``->> $1``) the string
    won't match the literal-key index expression and this test fails — that bind
    param is precisely what makes a generic plan skip the index.
    """
    compiled = str(
        json_number(StockFeatureDaily.details_json, (field,)).compile(
            dialect=postgresql.dialect(),
        )
    )
    return compiled.replace("stock_feature_daily.", "")


def test_indexed_fields_are_flat_top_level_keys():
    """A nested path would make the flat index expression index the wrong key."""
    migration = _load_migration()
    for field in migration._FIELDS:
        binding = _FIELD_BINDINGS.get(field)
        path = binding.json_path if binding is not None else None
        assert path is not None, f"{field} is not a JSON details field"
        assert len(path) == 1, (
            f"{field} maps to nested path {path}; the migration's flat "
            f"_index_expr would index the wrong key"
        )


def test_index_expr_matches_query_builder():
    """The index expression must match what the filter predicate compiles to."""
    migration = _load_migration()
    for field in migration._FIELDS:
        assert migration._index_expr(field) == _builder_expr(field), (
            f"index expression for {field} drifted from json_number(); the "
            f"Postgres planner will stop using ix_sfd_run_{field}"
        )


def test_resilience_index_expr_matches_numeric_query_builder():
    migration = _load_migration(_CORRECTION_SURVIVORS_MIGRATION)

    assert migration._index_expr("resilience_score") == _builder_expr(
        "resilience_score"
    )


def test_survivor_index_expr_matches_compiled_boolean_predicate():
    migration = _load_migration(_CORRECTION_SURVIVORS_MIGRATION)
    engine = create_mock_engine("postgresql://", lambda *_args, **_kwargs: None)
    query = Session(bind=engine).query(StockFeatureDaily)
    predicate = compile_filter_expression(
        query,
        FilterExpression(
            required_conditions=(BooleanFilter("correction_survivor", True),)
        ),
    )
    compiled = str(predicate.compile(dialect=postgresql.dialect())).replace(
        "stock_feature_daily.", ""
    )

    assert _FIELD_BINDINGS["correction_survivor"].json_path == (
        "correction_survivor",
    )
    assert migration._index_expr("correction_survivor") in compiled


def test_correction_survivor_migration_emits_exact_postgres_indexes():
    migration = _load_migration(_CORRECTION_SURVIVORS_MIGRATION)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)

    migration._create_indexes()

    statements = [
        line
        for line in output.getvalue().splitlines()
        if line.startswith("CREATE INDEX")
    ]
    assert statements == [
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sfd_run_correction_survivor "
        "ON stock_feature_daily (run_id, "
        "(lower(details_json ->> 'correction_survivor')));",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sfd_run_resilience_score "
        "ON stock_feature_daily (run_id, "
        "(CAST(details_json ->> 'resilience_score' AS FLOAT)));",
    ]


def test_correction_survivor_migration_emits_exact_concurrent_drops():
    migration = _load_migration(_CORRECTION_SURVIVORS_MIGRATION)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)

    migration._drop_indexes()

    statements = [
        line
        for line in output.getvalue().splitlines()
        if line.startswith("DROP INDEX")
    ]
    assert statements == [
        "DROP INDEX CONCURRENTLY IF EXISTS ix_sfd_run_correction_survivor;",
        "DROP INDEX CONCURRENTLY IF EXISTS ix_sfd_run_resilience_score;",
    ]


def test_correction_survivor_index_ddl_runs_inside_autocommit_block():
    migration = _load_migration(_CORRECTION_SURVIVORS_MIGRATION)
    events: list[object] = []

    class _AutocommitBlock:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, *_args):
            events.append("exit")

    class _Context:
        @staticmethod
        def autocommit_block():
            return _AutocommitBlock()

    class _Operations:
        @staticmethod
        def get_context():
            return _Context()

        @staticmethod
        def execute(statement):
            events.append(statement)

    migration.op = _Operations()

    migration._create_indexes()

    assert events[0] == "enter"
    assert events[-1] == "exit"
    assert all("CONCURRENTLY" in statement for statement in events[1:-1])


# ── Daily Snapshot read-path indexes (20260925_0046) ──────────────────────


def test_daily_snapshot_fields_resolve_under_their_indexed_name():
    """The field name in ``_FIELDS`` must be resolvable by that same name.

    ``test_indexed_fields_are_flat_top_level_keys`` looks each indexed field up
    in ``_FIELD_BINDINGS``. ``avg_dollar_volume`` used to resolve only as
    ``volume``, so indexing it under its own key would have failed that lookup.
    Pin both names to the same JSON path.
    """
    from app.infra.query.feature_store_query import _FIELD_BINDINGS

    migration = _load_migration(_DAILY_SNAPSHOT_MIGRATION)
    for field in migration._FIELDS:
        assert field in _FIELD_BINDINGS, (
            f"{field} is indexed by {_DAILY_SNAPSHOT_MIGRATION.stem} but has no "
            f"binding under that name; the drift guard cannot resolve it"
        )

    assert _FIELD_BINDINGS["avg_dollar_volume"].json_path == ("avg_dollar_volume",)
    assert _FIELD_BINDINGS["volume"].json_path == ("avg_dollar_volume",)


def test_daily_snapshot_index_expr_matches_query_builder():
    """Index expression must match the compiled filter predicate, or the
    planner declines the index and falls back to a full JSON scan."""
    migration = _load_migration(_DAILY_SNAPSHOT_MIGRATION)
    for field in migration._FIELDS:
        assert migration._index_expr(field) == _builder_expr(field), (
            f"index expression for {field} drifted from json_number(); the "
            f"Postgres planner will stop using ix_sfd_run_{field}"
        )


def test_daily_snapshot_migration_emits_exact_concurrent_indexes():
    migration = _load_migration(_DAILY_SNAPSHOT_MIGRATION)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)

    migration._create_indexes()

    statements = [
        line
        for line in output.getvalue().splitlines()
        if line.startswith("CREATE INDEX")
    ]
    assert statements == [
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_sfd_run_avg_dollar_volume ON stock_feature_daily (run_id, "
        "(CAST(details_json ->> 'avg_dollar_volume' AS FLOAT)));",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_sfd_run_ibd_group_rank ON stock_feature_daily (run_id, "
        "(CAST(details_json ->> 'ibd_group_rank' AS FLOAT)));",
    ]


def test_daily_snapshot_migration_emits_exact_concurrent_drops():
    migration = _load_migration(_DAILY_SNAPSHOT_MIGRATION)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)

    migration._drop_indexes()

    statements = [
        line
        for line in output.getvalue().splitlines()
        if line.startswith("DROP INDEX")
    ]
    assert statements == [
        "DROP INDEX CONCURRENTLY IF EXISTS ix_sfd_run_avg_dollar_volume;",
        "DROP INDEX CONCURRENTLY IF EXISTS ix_sfd_run_ibd_group_rank;",
    ]


def test_default_scan_filter_field_is_indexed():
    """The Daily Snapshot constrains minVolume for every market, so the field
    that filter maps to must be indexed -- that miss is what made the snapshot
    exceed the client timeout."""
    from app.domain.scanning.default_filters import resolve_default_scan_filters
    from app.infra.query.feature_store_query import _FIELD_BINDINGS

    # 20260821_0028 predates the `_FIELDS` convention and keeps its two fields
    # inline in `_create_indexes`, so read them the same way the migration does.
    migration_fields = (
        _load_migration(_MIGRATION)._FIELDS,
        _load_migration(_DAILY_SNAPSHOT_MIGRATION)._FIELDS,
        ("correction_survivor", "resilience_score"),
    )
    indexed_paths = set()
    for fields in migration_fields:
        for field in fields:
            binding = _FIELD_BINDINGS.get(field)
            if binding is not None:
                indexed_paths.add(binding.json_path)

    for market in ("US", "DE"):
        minimum_volume = resolve_default_scan_filters(market).get("minVolume")
        assert minimum_volume is not None, f"{market} has no default minVolume"
        binding = _FIELD_BINDINGS["volume"]
        assert binding.json_path in indexed_paths, (
            f"minVolume ({minimum_volume}) filters {binding.json_path} but no "
            f"migration indexes it; the snapshot will full-scan the run"
        )
