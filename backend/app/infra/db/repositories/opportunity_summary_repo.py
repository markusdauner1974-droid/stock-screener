"""SQL aggregate readers for persisted opportunity-state projections."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, literal_column
from sqlalchemy.orm import Session, sessionmaker

from app.domain.scanning.opportunity_state import ActionState
from app.domain.scanning.opportunity_summary import OpportunityStateSummary
from app.infra.db.models.feature_store import StockFeatureDaily
from app.models.scan_result import ScanResult


class SqlOpportunityStateSummaryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def for_scan(self, scan_id: str) -> OpportunityStateSummary:
        """Aggregate the opportunity projection for one legacy scan run."""
        return self._aggregate(
            model=ScanResult,
            details=ScanResult.details,
            predicate=ScanResult.scan_id == scan_id,
        )

    def for_feature_run(self, run_id: int) -> OpportunityStateSummary:
        """Aggregate the opportunity projection for one feature-store run."""
        return self._aggregate(
            model=StockFeatureDaily,
            details=StockFeatureDaily.details_json,
            predicate=StockFeatureDaily.run_id == int(run_id),
        )

    def _aggregate(self, *, model, details, predicate) -> OpportunityStateSummary:
        """Read ``action_state`` and ``correction_survivor`` once per row,
        group by the two, and pivot the buckets into a summary.

        Both columns are ``JSON`` rather than ``JSONB``, so each ``->>`` still
        parses the whole stored breakdown: two reads per row is the floor here
        without a schema change. The previous shape paid that per key *and*
        per action state, sixteen parses for the same answer.

        ``details`` is ``scan_results.details`` for a legacy scan run and
        ``stock_feature_daily.details_json`` for a feature-store run; the keys
        are the same in both.
        """
        action_state = details["action_state"].as_string()
        # The survivor test stays in SQL, as it was upstream. Deciding it in
        # Python instead makes ``JSON_EXTRACT(...) IS 1`` collapse to
        # ``bool(...)`` on SQLite, where the string "false" and the integer 2
        # are both truthy -- so identical data would count differently
        # depending on the backend.
        survivor = details["correction_survivor"].as_boolean().is_(True)
        buckets = (
            self._session.query(
                survivor.label("survivor"),
                action_state.label("action_state"),
                func.count().label("rows"),
            )
            .select_from(model)
            .filter(predicate)
            # Group by output position. Repeating the expressions would rely on
            # the driver inlining its bind parameters: psycopg2 interpolates on
            # the client, so the server sees identical text, but a driver that
            # binds server-side (asyncpg) emits $1 in the SELECT and $3 in the
            # GROUP BY, and PostgreSQL then rejects it as a grouping error.
            .group_by(literal_column("1"), literal_column("2"))
            .all()
        )

        rows_total = 0
        survivor_count = 0
        action_state_counts: dict[ActionState, int] = defaultdict(int)
        survivor_action_state_counts: dict[ActionState, int] = defaultdict(int)

        for is_survivor, raw_state, rows in buckets:
            rows_total += rows
            if is_survivor:
                survivor_count += rows
            # Unknown states stay out of every bucket; they are still counted
            # in rows_total so the totals never silently drift.
            try:
                state = ActionState(raw_state)
            except ValueError:
                continue
            action_state_counts[state] += rows
            if is_survivor:
                survivor_action_state_counts[state] += rows

        return OpportunityStateSummary(
            rows_total=rows_total,
            survivor_count=survivor_count,
            action_state_counts=dict(action_state_counts),
            survivor_action_state_counts=dict(survivor_action_state_counts),
        )


class SessionOpportunityStateSummaryReader:
    """Own a short-lived session for telemetry and other service consumers."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def for_scan(self, scan_id: str) -> OpportunityStateSummary:
        with self._session_factory() as session:
            return SqlOpportunityStateSummaryRepository(session).for_scan(scan_id)

    def for_feature_run(self, run_id: int) -> OpportunityStateSummary:
        with self._session_factory() as session:
            return SqlOpportunityStateSummaryRepository(session).for_feature_run(run_id)
