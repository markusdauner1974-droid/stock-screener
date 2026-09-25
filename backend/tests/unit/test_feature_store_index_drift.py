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
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

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

    # Record recovery and creation in ONE ordered sequence. Asserting that
    # recovery merely *ran* would still pass if it moved after the creates --
    # which is exactly the case where ``IF NOT EXISTS`` skips the rebuild.
    events: list[str] = []
    real_rebuild = migration._rebuild_invalid_indexes
    real_execute = migration.op.execute
    migration._rebuild_invalid_indexes = lambda: events.append("rebuild")

    def _record(statement, *args, **kwargs):
        if str(statement).startswith("CREATE INDEX"):
            events.append("create")
        return real_execute(statement, *args, **kwargs)

    migration.op.execute = _record
    migration._create_indexes()
    migration._rebuild_invalid_indexes = real_rebuild
    migration.op.execute = real_execute

    assert events == ["rebuild", "create", "create"], events

    statements = [
        line
        for line in output.getvalue().splitlines()
        if line.startswith("CREATE INDEX")
    ]
    assert len(statements) == len(migration._FIELDS)
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


def test_daily_snapshot_migration_extends_the_single_head():
    """The migration must hang off the current head of the whole tree.

    A branch that adds a revision while ``main`` also adds one ends up with two
    heads unless the new revision is rewritten onto the new head — and a
    multi-head tree makes ``alembic upgrade head`` fail, which surfaces as an
    unhealthy backend container rather than a migration error.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_root = Path(__file__).parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    script = ScriptDirectory.from_config(config)

    migration = _load_migration(_DAILY_SNAPSHOT_MIGRATION)
    heads = script.get_heads()

    assert len(heads) == 1, (
        f"the migration tree has {len(heads)} heads ({sorted(heads)}); "
        f"alembic upgrade head cannot resolve this"
    )
    # The revision must be reachable from that head, not orphaned beside it.
    reachable = {
        rev.revision for rev in script.walk_revisions(base="base", head="heads")
    }
    assert migration.revision in reachable, (
        f"{migration.revision} is not on the path to the single head {heads[0]}"
    )


def test_daily_snapshot_migration_recovers_invalid_indexes():
    """CONCURRENTLY is not atomic: an interrupted build leaves an invalid index
    under the target name, which ``IF NOT EXISTS`` would then treat as done."""
    migration = _load_migration(_DAILY_SNAPSHOT_MIGRATION)
    assert migration._rebuild_invalid_indexes is not None

    # Offline (--sql) has no catalog; the emitted script must stay CREATEs only.
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration.op = Operations(context)
    migration._rebuild_invalid_indexes()
    assert output.getvalue().strip() == ""

    # A catalog reporting an invalid index must trigger a DROP of that index's
    # schema-qualified name — resolving by bare name could drop an unrelated
    # same-named index that lives in another schema.
    class _FakeBind:
        def __init__(self, invalid):
            self._invalid = invalid
            self.queries: list[str] = []

        def execute(self, clause, _params=None):
            outer = self
            self.queries.append(str(clause))

            class _R:
                def scalar(self):
                    return outer._invalid

            return _R()

    class _Ctx:
        as_sql = False

        def __init__(self, bind):
            self._bind = bind

        def autocommit_block(self):
            import contextlib

            return contextlib.nullcontext()

        def get_bind(self):
            return self._bind

    emitted: list[str] = []

    class _Op:
        def get_context(self):
            return ctx

        def get_bind(self):
            return ctx.get_bind()

        def execute(self, sql, *a, **k):
            emitted.append(sql)

    bind = _FakeBind("public.ix_sfd_run_avg_dollar_volume")
    ctx = _Ctx(bind)
    migration.op = _Op()
    migration._rebuild_invalid_indexes()

    assert emitted == [
        "DROP INDEX CONCURRENTLY IF EXISTS public.ix_sfd_run_avg_dollar_volume",
        "DROP INDEX CONCURRENTLY IF EXISTS public.ix_sfd_run_avg_dollar_volume",
    ], emitted

    # The lookup must resolve the index through the target table, not by bare
    # name: to_regclass(name) can pick up an unrelated same-named index from
    # another schema and drop that one instead.
    assert bind.queries, "no lookup query was executed"
    for query in bind.queries:
        assert "pg_index" in query and "indrelid" in query, query
        assert "to_regclass('stock_feature_daily')" in query, query
        assert "indexrelid = to_regclass(:index_name)" not in query, query

    # A valid catalog (no invalid index) must emit nothing.
    emitted.clear()
    ctx = _Ctx(_FakeBind(None))
    migration.op = _Op()
    migration._rebuild_invalid_indexes()
    assert emitted == []


def test_default_scan_filter_field_is_indexed():
    """The Daily Snapshot constrains minVolume for every market, so the field
    that filter maps to must be indexed -- that miss is what made the snapshot
    exceed the client timeout."""
    from app.domain.scanning.default_filters import resolve_default_scan_filters
    from app.infra.query.feature_store_query import _FIELD_BINDINGS
    from app.services.daily_snapshot_service import VOLUME_FILTER_FIELD

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
        # Read the field the service actually constrains, not a hard-coded
        # name: if the service switches to an unindexed field the snapshot
        # starts full-scanning again, and this must fail rather than pass.
        binding = _FIELD_BINDINGS[VOLUME_FILTER_FIELD]
        assert binding.json_path in indexed_paths, (
            f"minVolume ({minimum_volume}) filters {binding.json_path} but no "
            f"migration indexes it; the snapshot will full-scan the run"
        )


def test_daily_snapshot_service_filters_the_volume_field(monkeypatch):
    """The service must constrain ``VOLUME_FILTER_FIELD``, and that field must
    be indexed — otherwise the snapshot is back to a full JSON scan.

    ``_query_scan_rows`` is the single place the snapshot turns filters into a
    query, so capture there: it takes the ``FilterSpec`` the service built.
    """
    import app.services.daily_snapshot_service as svc

    captured: list = []

    def _fake_query_scan_rows(*, filters, **_kw):
        captured.append(filters)
        return [], 0

    monkeypatch.setattr(svc, "_query_scan_rows", _fake_query_scan_rows)
    monkeypatch.setattr(svc, "resolve_default_scan_filters", lambda _m: {"minVolume": 5})
    # Top groups resolve through the process runtime, which unit tests do not
    # start; the filters under test are built before that point either way.
    monkeypatch.setattr(svc, "_build_top_groups", lambda *_a, **_k: ([], None))

    class _Query:
        def filter(self, *_a):
            return self

        def order_by(self, *_a):
            return self

        def first(self):
            return None

        def all(self):
            return []

    class _Db:
        def query(self, *_a):
            return _Query()

        def get(self, *_a):
            return None

    scan = SimpleNamespace(
        scan_id="s-1",
        completed_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        feature_run=None,
        # The correction-survivor path reads these after both queries ran, so
        # they must exist for the snapshot to complete instead of raising.
        feature_run_id=None,
        metadata_json=None,
    )

    svc.build_daily_snapshot_payload(
        _Db(),
        market="US",
        market_display_name="United States",
        scan=scan,
        uow=object(),
        scan_results_use_case=object(),
    )

    filtered_by_call = []
    for spec in captured:
        fields = {
            f.field
            for group in (
                getattr(spec, "range_filters", []),
                getattr(spec, "categorical_filters", []),
                getattr(spec, "boolean_filters", []),
            )
            for f in group
        }
        if fields:
            filtered_by_call.append((fields, spec))

    assert len(filtered_by_call) >= 2, (
        f"expected the candidate and leader queries; got {len(filtered_by_call)}"
    )

    # Both the candidate and the leader query must constrain the volume field.
    # A union over every call would still pass if only one of them did, which is
    # the regression this guards: the other query goes back to a full JSON scan.
    for fields, spec in filtered_by_call:
        assert svc.VOLUME_FILTER_FIELD in fields, (
            f"a snapshot query skipped {svc.VOLUME_FILTER_FIELD}; "
            f"it constrained {sorted(fields)}"
        )
        minimums = {
            f.field: f.min_value
            for f in getattr(spec, "range_filters", [])
            if f.field == svc.VOLUME_FILTER_FIELD
        }
        assert minimums.get(svc.VOLUME_FILTER_FIELD) == 5, (
            f"{svc.VOLUME_FILTER_FIELD} was not bounded by the market minimum: "
            f"{minimums}"
        )
