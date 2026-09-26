"""Index the Daily Snapshot's opportunity-summary counts.

``opportunity_summary_repo._aggregate`` reads two ``details_json`` keys once per
row of a run and pivots them into per-state counts. ``20260925_0057`` covered
the snapshot's *filter* predicates; this one covers the projection.

The first fix attempt — an expression index on the two keys — does not work, and
the measurement matters more than the shape:

* ``stock_feature_daily`` carries 10,079 rows for a run, each with a ~64 kB
  ``details_json``. Aggregating by ``GROUP BY`` measured 19,357 ms.
* With an expression index on ``(run_id, survivor, action_state)`` the planner
  *did* pick it up — as a ``Bitmap Index Scan`` — and the time stayed 19,768 ms.
  Neither ``Index Scan`` nor ``Bitmap Heap Scan`` is an ``Index Only Scan``, so
  every tuple still goes back to the heap, and the heap re-parses the whole
  stored document per row.

PostgreSQL only chooses an index-only scan when all *table* expressions the
query needs are available from the index. For ``f(x)`` it sees that ``x`` (here:
``details_json``) is needed, does not find it, and concludes an index-only scan
is impossible — documented in "Index-Only Scans and Covering Indexes". An
expression index therefore helps a filter (``WHERE``, served as an index
condition) but not a projection (``GROUP BY`` key, read per row). That is why
``20260925_0057`` worked and this one has to be shaped differently.

So the read side moves to scalar counts: ``count(*)`` per state instead of
grouping the extracted values. The expression then sits in the ``WHERE`` clause,
reaches the index as an index condition, and no ``details_json`` is read at all.

The exact expression text is what makes the index usable, so both sides are
kept byte-identical (minus the table qualifier) and a drift guard compares them
as strings. PostgreSQL normalises redundant parentheses away -- measured, both
``CAST((details_json ->> 'x') AS BOOLEAN)`` and
``CAST(details_json ->> 'x' AS BOOLEAN)`` matched the index, at 0.227 ms and
0.092 ms for the same count -- but the repository compiles the unparenthesised
form and the DDL follows it rather than relying on that.

One trap that is *not* cosmetic: the key must be an inline SQL literal, not a
bind parameter. ``details["action_state"].as_string()`` renders
``->> %(details_json_1)s``, which a generic plan cannot match to the index's
literal, so the index would silently go unused. The repository reads both keys
through ``portability.json_text`` for that reason.

Column order is load-bearing. ``(run_id, action_state, survivor)`` serves both
``action_state = …`` and the survivor predicate; the reverse order
``(run_id, survivor, action_state)`` measured 19.7 s because the filtered column
is not the one directly after the equality prefix.

Measured on a copy of the production table (63,333 rows), same cluster:

    GROUP BY, index present        19,176 – 19,465 ms
    16 scalar counts, no index     19,752 ms
    16 scalar counts + this index  6,281 / 6,162 / 8,667 / 9,646 / 12,537 ms

The last two lines are why the repository change and this index belong together:
without the index the scalar form is *slower* than the grouped one (16 passes
instead of one), so neither half is worth deploying alone.

``ANALYZE`` runs here on purpose. ``CREATE INDEX CONCURRENTLY`` leaves expression
statistics empty, and without them the planner rates the new index as unusable
and keeps the full scan — the failure ``20260925_0057`` hit in production, where
the index existed, validated, and went unused at 19,251 ms until ``ANALYZE``
brought the same query to 31 ms. Skipping it would ship an index that is built
and inert.

PostgreSQL-only, matching ``20260617_0021``, ``20260821_0028`` and
``20260925_0057``: SQLite does not parse these JSON operators. The build runs
``CONCURRENTLY`` inside an autocommit block so a large run does not block writes,
and ``_rebuild_invalid_indexes`` clears an invalid same-named index an
interrupted build may have left, which ``IF NOT EXISTS`` would otherwise treat
as done.

Deploy note: ``CONCURRENTLY`` still reads every row's ``details_json`` across
every run in the table, and the ``ANALYZE`` after it reads the table again. On a
large table the first container start after this revision can spend a while here,
and a compose healthcheck tighter than that build fails the rollout. Build the
index ahead of the deploy if that becomes the case:

    CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sfd_run_action_state_survivor
        ON stock_feature_daily (
            run_id,
            (CAST(details_json ->> 'action_state' AS VARCHAR)),
            (CAST((details_json ->> 'correction_survivor') AS BOOLEAN) IS true)
        );

The ``ANALYZE`` has to run in the same pass — an index built ahead of the deploy
still needs its statistics before the planner will use it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260926_0058"
down_revision = "20260925_0057"
branch_labels = None
depends_on = None

_TABLE = "stock_feature_daily"
_INDEX_NAME = "ix_sfd_run_action_state_survivor"

# The two keys the opportunity summary extracts, in index order. ``action_state``
# is filtered (it must sit directly after the ``run_id`` prefix to be reachable
# as an index condition); ``correction_survivor`` is only ever tested for truth,
# so it goes last.
_STATE_KEY = "action_state"
_SURVIVOR_KEY = "correction_survivor"

_INVALID_INDEX_SQL = """
SELECT pg_catalog.format('%I.%I', n.nspname, idx.relname)
FROM pg_catalog.pg_index AS i
JOIN pg_catalog.pg_class AS idx ON idx.oid = i.indexrelid
JOIN pg_catalog.pg_namespace AS n ON n.oid = idx.relnamespace
WHERE i.indrelid = pg_catalog.to_regclass('stock_feature_daily')
  AND idx.relname = :index_name
  AND NOT i.indisvalid
"""


def _state_expr() -> str:
    """SQL for the indexed action-state value.

    Must stay byte-identical (minus the table qualifier) to what
    ``details["action_state"].as_string()`` compiles for the same key, or the
    planner declines the index and the count falls back to a full JSON scan.
    ``test_opportunity_summary_index_drift`` pins that linkage.
    """
    return f"CAST(details_json ->> '{_STATE_KEY}' AS VARCHAR)"


def _survivor_expr() -> str:
    """SQL for the indexed survivor flag. Same linkage as ``_state_expr``.

    ``IS true`` is part of the expression, not decoration: the repository tests
    the flag rather than selecting it, so the indexed form has to be the tested
    one or the two never match.

    Written without inner parentheses because that is what
    ``cast(json_text(...), Boolean).is_(True)`` compiles to, and the drift guard
    compares the two as text. The parentheses would be harmless -- PostgreSQL
    normalises them away, and both spellings matched the index in a measured
    comparison (0.227 ms and 0.092 ms for the same count) -- but a byte-exact
    guard is worth more than the redundant pair.
    """
    return f"CAST(details_json ->> '{_SURVIVOR_KEY}' AS BOOLEAN) IS true"


def _rebuild_invalid_indexes() -> None:
    """Drop a same-named index a previous interrupted build left invalid.

    ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction and is not
    atomic: a failure leaves an invalid index under the target name. The
    following ``IF NOT EXISTS`` would consider the name taken and skip the
    build, so the counts would keep full-scanning with no error anywhere.

    Deliberately local to this revision, as in ``20260925_0057``.
    """
    bind = op.get_bind()
    if op.get_context().as_sql:
        # Offline / ``--sql`` generation: there is no catalog to inspect, and
        # the emitted script is expected to contain only the CREATE statements.
        return
    invalid = bind.execute(
        sa.text(_INVALID_INDEX_SQL), {"index_name": _INDEX_NAME}
    ).scalar()
    if invalid:
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {invalid}")


def _create_indexes() -> None:
    # Recovery runs before the create: an invalid index left by an interrupted
    # CONCURRENTLY build would otherwise make ``IF NOT EXISTS`` skip the rebuild.
    _rebuild_invalid_indexes()
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
            f"ON {_TABLE} (run_id, ({_state_expr()}), ({_survivor_expr()}))"
        )


def _analyze_table() -> None:
    """Refresh the expression statistics the new index needs to be usable.

    ``CREATE INDEX CONCURRENTLY`` does not create them, and without statistics
    the planner rates the expression index as unusable and keeps the sequential
    plan. ``20260925_0057`` shipped an index that existed, validated, and went
    unused at 19,251 ms for exactly this reason.
    """
    op.execute(f"ANALYZE {_TABLE}")


def _drop_indexes() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _create_indexes()
        _analyze_table()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        _drop_indexes()
