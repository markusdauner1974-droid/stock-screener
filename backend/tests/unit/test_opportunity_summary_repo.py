"""Contract tests for shared persisted opportunity-state aggregation."""

from datetime import date

from sqlalchemy import case, create_engine, event, func
from sqlalchemy.orm import Session

from app.database import Base
from app.domain.scanning.opportunity_state import ActionState
from app.infra.db.models.feature_store import FeatureRun, StockFeatureDaily
from app.infra.db.repositories.opportunity_summary_repo import (
    SqlOpportunityStateSummaryRepository,
    survivor_predicate,
)
from app.models.scan_result import Scan, ScanResult


def test_scan_summary_aggregates_all_counts_in_one_query():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Scan(scan_id="scan-summary", status="completed"))
        session.add_all(
            [
                ScanResult(
                    scan_id="scan-summary",
                    symbol="READY",
                    details={
                        "correction_survivor": True,
                        "action_state": "setup_ready",
                    },
                ),
                ScanResult(
                    scan_id="scan-summary",
                    symbol="WATCH",
                    details={
                        "correction_survivor": True,
                        "action_state": "watch",
                    },
                ),
                ScanResult(
                    scan_id="scan-summary",
                    symbol="NOT-SURVIVOR",
                    details={
                        "correction_survivor": False,
                        "action_state": "watch",
                    },
                ),
                ScanResult(
                    scan_id="scan-summary",
                    symbol="LEGACY",
                    details={},
                ),
            ]
        )
        session.commit()

        statements = []

        def capture(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            summary = SqlOpportunityStateSummaryRepository(session).for_scan(
                "scan-summary"
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 1
    assert summary.rows_total == 4
    assert summary.survivor_count == 2
    assert summary.action_state_counts[ActionState.SETUP_READY] == 1
    assert summary.action_state_counts[ActionState.WATCH] == 2
    assert summary.survivor_action_state_counts[ActionState.SETUP_READY] == 1
    assert summary.survivor_action_state_counts[ActionState.WATCH] == 1
    assert all(
        summary.action_state_counts[state] == 0
        for state in ActionState
        if state not in {ActionState.SETUP_READY, ActionState.WATCH}
    )


def _session_with(rows):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Scan(scan_id="scan-extra", status="completed"))
    session.add_all(
        [
            ScanResult(scan_id="scan-extra", symbol=name, details=details)
            for name, details in rows
        ]
    )
    session.commit()
    return session


def test_unknown_action_state_counts_in_total_only():
    """An unrecognised state is counted in rows_total, in no bucket.

    Moving the skip below ``rows_total +=`` would still pass the original
    fixture, because every row there carries a known state. This pins the
    intent: unknown states must not vanish from the total, and must not land
    in a bucket that does not exist for them.
    """
    with _session_with(
        [
            ("KNOWN", {"correction_survivor": False, "action_state": "watch"}),
            ("UNKNOWN", {"correction_survivor": False, "action_state": "not-a-state"}),
            ("MISSING", {"correction_survivor": False}),
        ]
    ) as session:
        summary = SqlOpportunityStateSummaryRepository(session).for_scan("scan-extra")

    assert summary.rows_total == 3
    assert summary.action_state_counts[ActionState.WATCH] == 1
    assert sum(summary.action_state_counts.values()) == 1
    assert summary.survivor_count == 0


def test_survivor_with_unknown_state_counts_in_survivor_count():
    """A survivor whose state is unknown still counts as a survivor.

    The two counters answer different questions: ``survivor_count`` is about
    the survivor flag, the per-state buckets are about the state. A survivor
    with no usable state must therefore appear in the first and in neither of
    the state mappings.
    """
    with _session_with(
        [
            ("SURV-BAD-STATE", {"correction_survivor": True, "action_state": "nope"}),
            ("SURV-NO-STATE", {"correction_survivor": True}),
            ("NON-SURV", {"correction_survivor": False, "action_state": "watch"}),
        ]
    ) as session:
        summary = SqlOpportunityStateSummaryRepository(session).for_scan("scan-extra")

    assert summary.rows_total == 3
    assert summary.survivor_count == 2
    assert summary.action_state_counts[ActionState.WATCH] == 1
    assert sum(summary.survivor_action_state_counts.values()) == 0


def test_survivor_predicate_is_shared_and_cast_free():
    """One survivor test decides every path, and it cannot raise.

    The regression this pins: the counted path used ``lower(...) IN
    ('true','1')`` while the grouped path used ``as_boolean().is_(True)``, so
    the same row classified differently depending on which path read it. On
    PostgreSQL the cast also accepts ``'t'``, ``'yes'`` and ``'on'``, and it
    raises on ``'2'`` while the text comparison does not.

    Both paths are compared on identical data rather than against a hand-written
    number, so the comparison cannot pass by restating one of them.
    """
    rows = [
        ("REAL-TRUE", {"correction_survivor": True, "action_state": "watch"}),
        ("REAL-FALSE", {"correction_survivor": False, "action_state": "watch"}),
        ("STR-TRUE", {"correction_survivor": "true", "action_state": "watch"}),
        ("STR-FALSE", {"correction_survivor": "false", "action_state": "watch"}),
        ("INT-1", {"correction_survivor": 1, "action_state": "watch"}),
        ("INT-2", {"correction_survivor": 2, "action_state": "watch"}),
    ]
    with _session_with(rows) as session:
        summary = SqlOpportunityStateSummaryRepository(session).for_scan("scan-extra")
        details = ScanResult.details
        grouped_count = (
            session.query(
                func.coalesce(func.sum(case((survivor_predicate(details), 1), else_=0)), 0)
            )
            .select_from(ScanResult)
            .filter(ScanResult.scan_id == "scan-extra")
            .scalar()
        )

    # ``true``, the string ``"true"`` and ``1`` are the canonical spellings;
    # ``false`` and ``2`` are not. Same answer through the shared predicate.
    assert summary.survivor_count == grouped_count == 3

    # It is cast-free: the expression must not raise for any stored value, which
    # is what lets migration 20260926_0058 index it against every historical row.
    assert "CAST" not in str(survivor_predicate(details)).upper()
    assert "BOOLEAN" not in str(survivor_predicate(details)).upper()


# ── Feature-store path: counted, not grouped ──────────────────────────────


def _feature_session_with(rows, run_id=7):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        FeatureRun(
            id=run_id,
            as_of_date=date(2026, 9, 25),
            run_type="daily_snapshot",
            status="published",
        )
    )
    session.add_all(
        [
            StockFeatureDaily(
                run_id=run_id,
                symbol=name,
                as_of_date=date(2026, 9, 25),
                details_json=details,
            )
            for name, details in rows
        ]
    )
    session.commit()
    return session


def test_feature_run_counts_match_the_grouped_pass():
    """``for_feature_run`` must answer exactly what the grouped pivot answered.

    The feature-store path counts per state instead of grouping both keys,
    because the grouped shape's per-row document reads are what make the Daily
    Snapshot exceed the client timeout. Counting changes how the answer is
    reached, not what it is -- so the two shapes are compared directly rather
    than against hand-written expectations, which would only restate one of
    them.
    """
    with _feature_session_with(
        [
            ("READY-SURV", {"correction_survivor": True, "action_state": "setup_ready"}),
            ("WATCH-SURV", {"correction_survivor": True, "action_state": "watch"}),
            ("WATCH-NOSURV", {"correction_survivor": False, "action_state": "watch"}),
            ("UNKNOWN", {"correction_survivor": False, "action_state": "not-a-state"}),
            ("MISSING", {"correction_survivor": False}),
            ("SURV-BAD", {"correction_survivor": True, "action_state": "nope"}),
            ("SURV-NONE", {"correction_survivor": True}),
            ("STR-FALSE", {"correction_survivor": "false", "action_state": "watch"}),
            ("INT-2", {"correction_survivor": 2, "action_state": "watch"}),
        ]
    ) as session:
        repo = SqlOpportunityStateSummaryRepository(session)
        counted = repo.for_feature_run(7)
        grouped = repo._aggregate(
            model=StockFeatureDaily,
            details=StockFeatureDaily.details_json,
            predicate=StockFeatureDaily.run_id == 7,
        )

    assert counted == grouped
    # Anchor the fixture so a broken comparison cannot pass vacuously.
    assert counted.rows_total == 9
    assert counted.survivor_count == 4
    assert counted.action_state_counts[ActionState.SETUP_READY] == 1
    assert counted.action_state_counts[ActionState.WATCH] == 4
    assert sum(counted.action_state_counts.values()) == 5
    assert sum(counted.survivor_action_state_counts.values()) == 2


def test_feature_run_unknown_states_stay_out_of_buckets_but_in_totals():
    """An unrecognised state is counted in no bucket, in both totals.

    Counted per state, an unknown value matches no predicate at all; grouped,
    the pivot skipped it after adding it to ``rows_total``. Same contract, two
    mechanisms -- so it is pinned on the path that actually runs.
    """
    with _feature_session_with(
        [
            ("KNOWN", {"correction_survivor": True, "action_state": "watch"}),
            ("UNKNOWN", {"correction_survivor": True, "action_state": "not-a-state"}),
            ("MISSING", {"correction_survivor": True}),
        ]
    ) as session:
        summary = SqlOpportunityStateSummaryRepository(session).for_feature_run(7)

    assert summary.rows_total == 3
    assert summary.survivor_count == 3
    assert summary.action_state_counts[ActionState.WATCH] == 1
    assert sum(summary.action_state_counts.values()) == 1
    assert sum(summary.survivor_action_state_counts.values()) == 1


def test_feature_run_issues_a_single_statement():
    """One index probe plus one counted statement -- not sixteen round trips.

    The counts are correlated scalar subqueries in one ``SELECT``. Sixteen
    separate queries would be correct and sixteen times the latency on a slow
    link -- and would quietly reintroduce the round-trip cost this rewrite is
    meant to remove.

    The probe is a second statement by design: it decides whether the counted
    shape has the index it needs. It is one cheap catalog lookup, so the
    guarantee that matters is "no per-state round trip", not "exactly one
    statement". Both are asserted to keep either from regressing.
    """
    with _feature_session_with(
        [("A", {"correction_survivor": True, "action_state": "watch"})]
    ) as session:
        engine = session.get_bind()
        statements = []

        def capture(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            SqlOpportunityStateSummaryRepository(session).for_feature_run(7)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert len(statements) == 2, statements
    # The probe is the catalog lookup. On SQLite it fails ("no such table:
    # pg_index"), which is the documented fallback -- so the second statement is
    # legitimately the grouped one. The guarantee is that the shape is chosen by
    # the probe and issued once, not split per state.
    assert sum("pg_index" in s for s in statements) <= 1, statements
    counted = [s for s in statements if "pg_index" not in s]
    assert len(counted) == 1, statements
    assert "GROUP BY" not in counted[0].upper() or "JSON_EXTRACT" in counted[0], counted[0]


# ── The fallback when the count index is missing or unusable ──────────────


def test_feature_run_falls_back_to_grouping_without_the_index(monkeypatch):
    """A missing or invalid index must degrade, not stall.

    Measured on a copy of the production table: the same sixteen counts take
    6.8 ms with this index and 56.7 s without it, because each count scans the
    run on its own. A build that never ran, was rolled back, or died halfway
    would turn the Daily Snapshot into a minute-long scan.

    Both shapes answer the same question, so the fallback has to return the same
    summary -- asserted by comparing them rather than by a written-out number.
    """
    rows = [
        ("READY-SURV", {"correction_survivor": True, "action_state": "setup_ready"}),
        ("WATCH-SURV", {"correction_survivor": True, "action_state": "watch"}),
        ("WATCH-NOSURV", {"correction_survivor": False, "action_state": "watch"}),
        ("UNKNOWN", {"correction_survivor": False, "action_state": "not-a-state"}),
    ]
    with _feature_session_with(rows) as session:
        repo = SqlOpportunityStateSummaryRepository(session)
        expected = repo._aggregate(
            model=StockFeatureDaily,
            details=StockFeatureDaily.details_json,
            predicate=StockFeatureDaily.run_id == 7,
        )
        monkeypatch.setattr(
            "app.infra.db.repositories.opportunity_summary_repo._count_index_is_usable",
            lambda _session: False,
        )
        engine = session.get_bind()
        statements = []

        def capture(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            fallen_back = repo.for_feature_run(7)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    # The result alone cannot prove the fallback ran: on this fixture the counted
    # path happens to produce the same numbers, so asserting only the summary
    # would pass with the fallback deleted. The shape is what is asserted.
    assert fallen_back == expected
    assert fallen_back.rows_total == 4
    assert fallen_back.survivor_count == 2
    shapes = [s for s in statements if "pg_index" not in s]
    assert len(shapes) == 1, statements
    assert "GROUP BY" in shapes[0].upper(), (
        "the fallback did not group; the counted shape ran without its index: "
        f"{shapes[0]}"
    )


def test_feature_run_uses_the_counted_shape_when_the_index_is_usable(monkeypatch):
    """The probe gates the counted shape; with a usable index it is used.

    Without this, making the probe always return False would silently keep the
    slower grouped path forever and no test would notice.
    """
    monkeypatch.setattr(
        "app.infra.db.repositories.opportunity_summary_repo._count_index_is_usable",
        lambda _session: True,
    )
    with _feature_session_with(
        [("A", {"correction_survivor": True, "action_state": "watch"})]
    ) as session:
        engine = session.get_bind()
        statements = []

        def capture(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            summary = SqlOpportunityStateSummaryRepository(session).for_feature_run(7)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert summary.rows_total == 1
    assert len(statements) == 1, statements
    assert "GROUP BY" not in statements[0].upper(), statements[0]


def test_index_probe_treats_an_unreadable_catalog_as_not_usable():
    """A backend without ``pg_index`` falls back instead of raising.

    SQLite has no ``pg_index``, so the probe's own query fails there. The
    fallback is correct on every backend, so an unreadable catalog has to mean
    "not usable" rather than propagate the error to the caller.
    """
    with _feature_session_with(
        [("A", {"correction_survivor": True, "action_state": "watch"})]
    ) as session:
        from app.infra.db.repositories.opportunity_summary_repo import (
            _count_index_is_usable,
        )

        assert _count_index_is_usable(session) is False
        # And the caller still answers correctly.
        assert SqlOpportunityStateSummaryRepository(session).for_feature_run(7).rows_total == 1


def test_index_probe_reads_validity_and_readiness_not_just_presence():
    """An interrupted CONCURRENTLY build leaves a same-named, unusable index.

    ``indisvalid`` is false while a concurrent build is in progress or after it
    failed. Counting the name alone would treat that index as present and hand
    the query back to a plan that cannot use it.
    """
    from app.infra.db.repositories.opportunity_summary_repo import _INDEX_USABLE_SQL

    sql = str(_INDEX_USABLE_SQL).lower()
    assert "indisvalid" in sql
    assert "indisready" in sql
    assert _INDEX_USABLE_SQL._bindparams["name"] is not None
