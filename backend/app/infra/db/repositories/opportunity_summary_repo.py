"""SQL aggregate readers for persisted opportunity-state projections."""

from __future__ import annotations

from sqlalchemy import func
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
        """Aggregate the projection in a single grouped pass.

        Every ``details_json`` access detoasts the whole stored value, so the
        previous shape -- one conditional aggregate per action state, twice --
        paid that cost once per expression. Reading both keys once and pivoting
        the resulting buckets keeps the same totals for a fraction of the work.
        """

        action_state = details["action_state"].as_string()
        survivor = details["correction_survivor"].as_boolean()
        buckets = (
            self._session.query(
                survivor.label("survivor"),
                action_state.label("action_state"),
                func.count().label("rows"),
            )
            .select_from(model)
            .filter(predicate)
            .group_by(survivor, action_state)
            .all()
        )

        known_states = {state.value: state for state in ActionState}
        rows_total = 0
        survivor_count = 0
        action_state_counts = {state: 0 for state in ActionState}
        survivor_action_state_counts = {state: 0 for state in ActionState}

        for is_survivor, raw_state, rows in buckets:
            rows = int(rows or 0)
            rows_total += rows
            if is_survivor:
                survivor_count += rows
            # Unknown states stay out of every bucket; they are still counted in
            # rows_total so the totals never silently drift.
            state = known_states.get(raw_state)
            if state is None:
                continue
            action_state_counts[state] += rows
            if is_survivor:
                survivor_action_state_counts[state] += rows

        return OpportunityStateSummary(
            rows_total=rows_total,
            survivor_count=survivor_count,
            action_state_counts=action_state_counts,
            survivor_action_state_counts=survivor_action_state_counts,
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
