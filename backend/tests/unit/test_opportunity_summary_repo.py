"""Contract tests for shared persisted opportunity-state aggregation."""

from sqlalchemy import case, create_engine, event, func
from sqlalchemy.orm import Session

from app.database import Base
from app.domain.scanning.opportunity_state import ActionState
from app.infra.db.repositories.opportunity_summary_repo import (
    SqlOpportunityStateSummaryRepository,
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


def test_survivor_test_matches_sql_semantics_on_non_boolean_json():
    """The survivor test stays in SQL, so SQLite and PostgreSQL agree.

    ``correction_survivor`` is written as a real JSON boolean by the scanner,
    but the column is untyped JSON and older rows can hold ``"false"`` or
    ``2``. Deciding the flag with Python truthiness instead of
    ``JSON_EXTRACT(...) IS 1`` makes those rows survivors, so the same data
    counts differently on SQLite than on PostgreSQL.
    """
    rows = [
        ("REAL-TRUE", {"correction_survivor": True, "action_state": "watch"}),
        ("REAL-FALSE", {"correction_survivor": False, "action_state": "watch"}),
        ("STR-FALSE", {"correction_survivor": "false", "action_state": "watch"}),
        ("STR-TRUE", {"correction_survivor": "true", "action_state": "watch"}),
        ("INT-2", {"correction_survivor": 2, "action_state": "watch"}),
    ]
    with _session_with(rows) as session:
        summary = SqlOpportunityStateSummaryRepository(session).for_scan("scan-extra")

        # The same flag decided in SQL, as the pre-change code did it.
        details = ScanResult.details
        survivor_expr = details["correction_survivor"].as_boolean()
        sql_count = session.query(
            func.coalesce(
                func.sum(case((survivor_expr.is_(True), 1), else_=0)), 0
            )
        ).select_from(ScanResult).filter(ScanResult.scan_id == "scan-extra").scalar()

    assert summary.survivor_count == sql_count == 1
