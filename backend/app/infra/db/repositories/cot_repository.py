from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.cot.models import (
    COT_REGISTRY_VERSION,
    CotInstrumentDefinition,
    DerivedCotWeek,
)
from app.infra.db.models.cot import (
    CotImportRun,
    CotInstrument,
    CotPublicationPointer,
    CotWeeklyPosition,
)
from app.use_cases.cot.ports import CotRunRequest


LATEST_PUBLICATION_KEY = "latest_published"


@dataclass(frozen=True)
class CotPublication:
    pointer: CotPublicationPointer
    run: CotImportRun


class SqlCotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(self, request: CotRunRequest) -> int:
        run = CotImportRun(
            origin=request.origin.strip(),
            status="staged",
            requested_report_date=request.requested_report_date,
            expected_instrument_count=request.expected_instrument_count,
            observed_instrument_count=0,
            registry_version=request.registry_version,
            calculation_version=request.calculation_version,
            schema_version=request.schema_version,
        )
        self._session.add(run)
        self._session.commit()
        return int(run.id)

    def existing_week_keys(self) -> frozenset[tuple[str, date]]:
        rows = self._session.execute(
            select(CotInstrument.slug, CotWeeklyPosition.report_date)
            .join(
                CotWeeklyPosition,
                CotWeeklyPosition.instrument_id == CotInstrument.id,
            )
            .distinct()
        ).all()
        return frozenset((slug, report_date) for slug, report_date in rows)

    def stored_fingerprints(self) -> Mapping[str, str]:
        rows = self._session.execute(
            select(
                CotWeeklyPosition.source_row_id,
                CotWeeklyPosition.source_fingerprint,
            ).distinct()
        ).all()
        return {source_row_id: fingerprint for source_row_id, fingerprint in rows}

    def publish(
        self,
        run_id: int,
        *,
        registry: Sequence[CotInstrumentDefinition],
        weeks: Sequence[DerivedCotWeek],
        diagnostics: Mapping[str, Any] | None = None,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        derived_weeks = tuple(weeks)
        self._reject_duplicate_natural_keys(derived_weeks)
        if not derived_weeks:
            raise ValueError("cannot publish empty COT history")

        try:
            run = self._require_run(run_id)
            if run.status != "staged":
                raise ValueError(f"COT run {run_id} is not staged")
            instruments_by_slug = self._sync_registry(tuple(registry))
            self._upsert_positions(run_id, derived_weeks, instruments_by_slug)

            report_date = max(week.report_date for week in derived_weeks)
            now = datetime.now(timezone.utc)
            run.status = "published"
            run.observed_report_date = report_date
            run.observed_instrument_count = len(
                {week.instrument_slug for week in derived_weeks}
            )
            run.coverage_json = dict((diagnostics or {}).get("validation", {}))
            run.diagnostics_json = dict(diagnostics or {})
            run.source_metadata_json = dict(source_metadata or {})
            run.completed_at = now
            run.published_at = now

            pointer = self._session.get(CotPublicationPointer, LATEST_PUBLICATION_KEY)
            if pointer is None:
                self._session.add(
                    CotPublicationPointer(
                        key=LATEST_PUBLICATION_KEY,
                        run_id=run_id,
                        report_date=report_date,
                    )
                )
            else:
                pointer.run_id = run_id
                pointer.report_date = report_date
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def mark_no_change(
        self,
        run_id: int,
        diagnostics: Mapping[str, Any],
    ) -> None:
        run = self._require_run(run_id)
        run.status = "no_change"
        run.diagnostics_json = dict(diagnostics)
        run.coverage_json = dict(diagnostics)
        run.completed_at = datetime.now(timezone.utc)
        self._session.commit()

    def mark_failed(
        self,
        run_id: int,
        status: str,
        diagnostics: Mapping[str, Any],
    ) -> None:
        if not status.startswith("failed"):
            raise ValueError("failed run status must begin with 'failed'")
        run = self._require_run(run_id)
        run.status = status
        run.failure_reason = status
        run.diagnostics_json = dict(diagnostics)
        run.completed_at = datetime.now(timezone.utc)
        self._session.commit()

    def get_publication(self) -> CotPublication | None:
        pointer = self._session.get(CotPublicationPointer, LATEST_PUBLICATION_KEY)
        if pointer is None:
            return None
        run = self._session.get(CotImportRun, pointer.run_id)
        if run is None:
            return None
        return CotPublication(pointer=pointer, run=run)

    def get_instruments(self) -> tuple[CotInstrument, ...]:
        return tuple(
            self._session.scalars(
                select(CotInstrument)
                .where(CotInstrument.active.is_(True))
                .order_by(CotInstrument.instrument_order)
            )
        )

    def get_history(
        self,
        slug: str,
        *,
        limit: int | None = None,
    ) -> tuple[CotWeeklyPosition, ...]:
        statement = (
            select(CotWeeklyPosition)
            .join(
                CotInstrument,
                CotInstrument.id == CotWeeklyPosition.instrument_id,
            )
            .where(CotInstrument.slug == slug)
            .order_by(
                CotWeeklyPosition.report_date.desc(),
                CotWeeklyPosition.participant,
            )
        )
        if limit is not None:
            instrument = self._session.scalar(
                select(CotInstrument).where(CotInstrument.slug == slug)
            )
            if instrument is None:
                return ()
            selected_dates = select(CotWeeklyPosition.report_date).where(
                CotWeeklyPosition.instrument_id == instrument.id
            ).distinct().order_by(CotWeeklyPosition.report_date.desc()).limit(limit)
            statement = statement.where(
                CotWeeklyPosition.report_date.in_(selected_dates)
            )
        rows = tuple(self._session.scalars(statement))
        return tuple(
            sorted(rows, key=lambda row: (row.report_date, row.participant))
        )

    def get_snapshot(self) -> tuple[CotWeeklyPosition, ...]:
        latest = (
            select(
                CotWeeklyPosition.instrument_id,
                func.max(CotWeeklyPosition.report_date).label("report_date"),
            )
            .group_by(CotWeeklyPosition.instrument_id)
            .subquery()
        )
        return tuple(
            self._session.scalars(
                select(CotWeeklyPosition)
                .join(
                    latest,
                    (latest.c.instrument_id == CotWeeklyPosition.instrument_id)
                    & (latest.c.report_date == CotWeeklyPosition.report_date),
                )
                .join(
                    CotInstrument,
                    CotInstrument.id == CotWeeklyPosition.instrument_id,
                )
                .order_by(
                    CotInstrument.instrument_order,
                    CotWeeklyPosition.participant,
                )
            )
        )

    def _sync_registry(
        self,
        registry: tuple[CotInstrumentDefinition, ...],
    ) -> dict[str, CotInstrument]:
        current = {
            instrument.slug: instrument
            for instrument in self._session.scalars(select(CotInstrument))
        }
        requested_slugs = {definition.slug for definition in registry}
        for instrument in current.values():
            if instrument.slug not in requested_slugs:
                instrument.active = False
        for definition in registry:
            instrument = current.get(definition.slug)
            if instrument is None:
                instrument = CotInstrument(slug=definition.slug)
                self._session.add(instrument)
                current[definition.slug] = instrument
            instrument.cftc_code = definition.cftc_code
            instrument.display_name = definition.display_name
            instrument.category = definition.category.value
            instrument.category_order = definition.category_order
            instrument.instrument_order = definition.instrument_order
            instrument.report_family = definition.report_family.value
            instrument.focal_participant = definition.focal_participant.value
            instrument.active = True
            instrument.registry_version = COT_REGISTRY_VERSION
        self._session.flush()
        return {slug: current[slug] for slug in requested_slugs}

    def _upsert_positions(
        self,
        run_id: int,
        weeks: tuple[DerivedCotWeek, ...],
        instruments_by_slug: Mapping[str, CotInstrument],
    ) -> None:
        values = [
            {
                "instrument_id": instruments_by_slug[week.instrument_slug].id,
                "report_date": week.report_date,
                "participant": position.participant.value,
                "long": position.long,
                "short": position.short,
                "spreading": position.spreading,
                "open_interest": week.open_interest,
                "net": position.net,
                "delta_long": position.delta_long,
                "delta_short": position.delta_short,
                "delta_net": position.delta_net,
                "net_pct_open_interest": position.net_pct_open_interest,
                "percentile_3y": position.percentile_3y,
                "percentile_status": position.percentile_status,
                "source_dataset_id": week.source_dataset_id,
                "source_row_id": week.source_row_id,
                "source_fingerprint": week.source_fingerprint,
                "import_run_id": run_id,
            }
            for week in weeks
            for position in week.positions
        ]
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name not in {"postgresql", "sqlite"}:
            raise RuntimeError(f"unsupported COT repository dialect: {dialect_name}")
        insert = postgresql_insert if dialect_name == "postgresql" else sqlite_insert
        statement = insert(CotWeeklyPosition)
        update_fields = {
            field: getattr(statement.excluded, field)
            for field in (
                "long",
                "short",
                "spreading",
                "open_interest",
                "net",
                "delta_long",
                "delta_short",
                "delta_net",
                "net_pct_open_interest",
                "percentile_3y",
                "percentile_status",
                "source_dataset_id",
                "source_row_id",
                "source_fingerprint",
                "import_run_id",
            )
        }
        self._session.execute(
            statement.on_conflict_do_update(
                index_elements=("instrument_id", "report_date", "participant"),
                set_=update_fields,
            ),
            values,
        )

    @staticmethod
    def _reject_duplicate_natural_keys(weeks: tuple[DerivedCotWeek, ...]) -> None:
        keys = [
            (week.instrument_slug, week.report_date, position.participant.value)
            for week in weeks
            for position in week.positions
        ]
        if len(keys) != len(set(keys)):
            raise IntegrityError(
                "duplicate COT weekly position",
                params=None,
                orig=ValueError("duplicate natural key"),
            )

    def _require_run(self, run_id: int) -> CotImportRun:
        run = self._session.get(CotImportRun, run_id)
        if run is None:
            raise LookupError(f"COT run not found: {run_id}")
        return run
