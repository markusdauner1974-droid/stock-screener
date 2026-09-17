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
from app.use_cases.cot.ports import (
    CotPublicationSignature,
    CotRunRequest,
    CotSnapshotPositionRecord,
)

LATEST_PUBLICATION_KEY = "latest_published"
_COT_PUBLICATION_LOCK_ID = 0x434F5450


def _source_retrieved_at(
    source_metadata: Mapping[str, Any] | None,
) -> datetime | None:
    if source_metadata is None:
        return None
    value = source_metadata.get("retrieved_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


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

    def existing_week_keys(
        self,
        instrument_slugs: Sequence[str],
    ) -> frozenset[tuple[str, date]]:
        slugs = tuple(dict.fromkeys(instrument_slugs))
        if not slugs:
            return frozenset()
        rows = self._session.execute(
            select(CotInstrument.slug, CotWeeklyPosition.report_date)
            .join(
                CotWeeklyPosition,
                CotWeeklyPosition.instrument_id == CotInstrument.id,
            )
            .where(CotInstrument.slug.in_(slugs))
            .distinct()
        ).all()
        return frozenset((slug, report_date) for slug, report_date in rows)

    def publication_signature(self) -> CotPublicationSignature | None:
        publication = self.get_publication()
        if publication is None:
            return None
        rows = self._session.execute(
            select(
                CotWeeklyPosition.source_row_id,
                CotWeeklyPosition.source_fingerprint,
            )
            .where(CotWeeklyPosition.import_run_id == publication.run.id)
            .distinct()
        ).all()
        return CotPublicationSignature(
            source_fingerprints={
                source_row_id: fingerprint for source_row_id, fingerprint in rows
            },
            registry_version=publication.run.registry_version,
            calculation_version=publication.run.calculation_version,
            schema_version=publication.run.schema_version,
        )

    def publish(
        self,
        run_id: int,
        *,
        registry: Sequence[CotInstrumentDefinition],
        weeks: Sequence[DerivedCotWeek],
        diagnostics: Mapping[str, Any] | None = None,
        source_metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        derived_weeks = tuple(weeks)
        self._reject_duplicate_natural_keys(derived_weeks)
        if not derived_weeks:
            raise ValueError("cannot publish empty COT history")

        try:
            run = self._require_run(run_id)
            if run.status != "staged":
                raise ValueError(f"COT run {run_id} is not staged")
            report_date = max(week.report_date for week in derived_weeks)
            pointer = self._lock_publication_pointer()
            if pointer is not None and self._publication_is_newer(
                pointer,
                candidate_run_id=run_id,
                candidate_report_date=report_date,
                candidate_source_metadata=source_metadata,
            ):
                now = datetime.now(timezone.utc)
                run.status = "superseded"
                run.observed_report_date = report_date
                run.observed_instrument_count = len(
                    {week.instrument_slug for week in derived_weeks}
                )
                run.coverage_json = dict((diagnostics or {}).get("validation", {}))
                run.diagnostics_json = {
                    **dict(diagnostics or {}),
                    "superseded_by_run_id": int(pointer.run_id),
                }
                run.source_metadata_json = dict(source_metadata or {})
                run.completed_at = now
                self._session.commit()
                return False

            instruments_by_slug = self._sync_registry(tuple(registry))
            self._upsert_positions(run_id, derived_weeks, instruments_by_slug)

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
            return True
        except Exception:
            self._session.rollback()
            raise

    def _publication_is_newer(
        self,
        pointer: CotPublicationPointer,
        *,
        candidate_run_id: int,
        candidate_report_date: date,
        candidate_source_metadata: Mapping[str, Any] | None,
    ) -> bool:
        if pointer.report_date != candidate_report_date:
            return pointer.report_date > candidate_report_date

        published_run = self._session.scalar(
            select(CotImportRun)
            .where(CotImportRun.id == pointer.run_id)
            .execution_options(populate_existing=True)
        )
        candidate_retrieved_at = _source_retrieved_at(candidate_source_metadata)
        published_retrieved_at = _source_retrieved_at(
            published_run.source_metadata_json if published_run is not None else None
        )
        if candidate_retrieved_at is not None and published_retrieved_at is not None:
            return candidate_retrieved_at < published_retrieved_at
        return pointer.run_id > candidate_run_id

    def _lock_publication_pointer(self) -> CotPublicationPointer | None:
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            self._session.execute(
                select(func.pg_advisory_xact_lock(_COT_PUBLICATION_LOCK_ID))
            )
        return self._session.scalar(
            select(CotPublicationPointer)
            .where(CotPublicationPointer.key == LATEST_PUBLICATION_KEY)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
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
        self._session.rollback()
        run = self._require_run(run_id)
        run.status = status
        run.failure_reason = status
        run.diagnostics_json = dict(diagnostics)
        run.completed_at = datetime.now(timezone.utc)
        self._session.commit()

    def get_publication(self) -> CotPublication | None:
        pointer = self._session.scalar(
            select(CotPublicationPointer)
            .where(CotPublicationPointer.key == LATEST_PUBLICATION_KEY)
            .execution_options(populate_existing=True)
        )
        if pointer is None:
            return None
        run = self._session.scalar(
            select(CotImportRun)
            .where(CotImportRun.id == pointer.run_id)
            .execution_options(populate_existing=True)
        )
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
            .execution_options(populate_existing=True)
        )
        if limit is not None:
            instrument = self._session.scalar(
                select(CotInstrument).where(CotInstrument.slug == slug)
            )
            if instrument is None:
                return ()
            selected_dates = (
                select(CotWeeklyPosition.report_date)
                .where(CotWeeklyPosition.instrument_id == instrument.id)
                .distinct()
                .order_by(CotWeeklyPosition.report_date.desc())
                .limit(limit)
            )
            statement = statement.where(
                CotWeeklyPosition.report_date.in_(selected_dates)
            )
        rows = tuple(self._session.scalars(statement))
        return tuple(sorted(rows, key=lambda row: (row.report_date, row.participant)))

    def get_snapshot_history(
        self,
        *,
        weeks: int,
    ) -> tuple[CotSnapshotPositionRecord, ...]:
        if weeks <= 0:
            raise ValueError("snapshot history weeks must be positive")
        ranked = (
            select(
                CotWeeklyPosition.id.label("position_id"),
                CotInstrument.slug.label("instrument_slug"),
                CotInstrument.instrument_order.label("instrument_order"),
                func.row_number()
                .over(
                    partition_by=CotWeeklyPosition.instrument_id,
                    order_by=CotWeeklyPosition.report_date.desc(),
                )
                .label("week_rank"),
            )
            .join(
                CotInstrument,
                CotInstrument.id == CotWeeklyPosition.instrument_id,
            )
            .where(
                CotInstrument.active.is_(True),
                CotWeeklyPosition.participant == CotInstrument.focal_participant,
            )
            .subquery()
        )
        rows = self._session.execute(
            select(
                ranked.c.instrument_slug,
                CotWeeklyPosition.report_date,
                CotWeeklyPosition.participant,
                CotWeeklyPosition.long,
                CotWeeklyPosition.short,
                CotWeeklyPosition.open_interest,
                CotWeeklyPosition.net,
                CotWeeklyPosition.delta_long,
                CotWeeklyPosition.delta_short,
                CotWeeklyPosition.delta_net,
                CotWeeklyPosition.net_pct_open_interest,
                CotWeeklyPosition.percentile_3y,
                CotWeeklyPosition.percentile_status,
            )
            .join(ranked, ranked.c.position_id == CotWeeklyPosition.id)
            .where(ranked.c.week_rank <= weeks)
            .order_by(
                ranked.c.instrument_order,
                CotWeeklyPosition.report_date,
            )
        ).all()
        return tuple(
            CotSnapshotPositionRecord(
                instrument_slug=row.instrument_slug,
                report_date=row.report_date,
                participant=row.participant,
                long=int(row.long),
                short=int(row.short),
                open_interest=int(row.open_interest),
                net=int(row.net),
                delta_long=row.delta_long,
                delta_short=row.delta_short,
                delta_net=row.delta_net,
                net_pct_open_interest=row.net_pct_open_interest,
                percentile_3y=row.percentile_3y,
                percentile_status=row.percentile_status,
            )
            for row in rows
        )

    def _sync_registry(
        self,
        registry: tuple[CotInstrumentDefinition, ...],
    ) -> dict[str, CotInstrument]:
        current_by_slug = {
            instrument.slug: instrument
            for instrument in self._session.scalars(select(CotInstrument))
        }
        current_by_code = {
            instrument.cftc_code: instrument
            for instrument in current_by_slug.values()
        }
        requested_slugs = {definition.slug for definition in registry}
        for instrument in current_by_slug.values():
            if instrument.slug not in requested_slugs:
                instrument.active = False
        for definition in registry:
            instrument = current_by_slug.get(definition.slug)
            if instrument is None:
                instrument = current_by_code.get(definition.cftc_code)
                if instrument is None:
                    instrument = CotInstrument(slug=definition.slug)
                    self._session.add(instrument)
                    current_by_code[definition.cftc_code] = instrument
                else:
                    current_by_slug.pop(instrument.slug, None)
                    instrument.slug = definition.slug
                current_by_slug[definition.slug] = instrument
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
        return {slug: current_by_slug[slug] for slug in requested_slugs}

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
