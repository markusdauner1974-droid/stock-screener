"""Redacted operational health projection for the COT pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.infra.db.models.cot import CotImportRun, CotPublicationPointer


_NEW_YORK = ZoneInfo("America/New_York")


class CotOperationsService:
    def snapshot(self, db, now: datetime | None = None) -> dict:
        current = now or datetime.now(timezone.utc)
        pointer = db.get(CotPublicationPointer, "latest_published")
        published = db.get(CotImportRun, pointer.run_id) if pointer is not None else None
        latest_hydration = (
            db.scalar(
                select(CotImportRun)
                .where(
                    CotImportRun.id >= published.id,
                    CotImportRun.status.in_(("published", "no_change")),
                )
                .order_by(CotImportRun.id.desc())
                .limit(1)
            )
            if published is not None
            else None
        )
        failed = db.scalar(
            select(CotImportRun)
            .where(CotImportRun.status.like("failed%"))
            .order_by(CotImportRun.id.desc())
            .limit(1)
        )

        source_metadata = dict(published.source_metadata_json or {}) if published else {}
        diagnostics = dict(published.diagnostics_json or {}) if published else {}
        hydration_diagnostics = (
            dict(latest_hydration.diagnostics_json or {})
            if latest_hydration is not None
            else {}
        )
        prices = dict(
            hydration_diagnostics.get("prices") or diagnostics.get("prices") or {}
        )
        failed_diagnostics = dict(failed.diagnostics_json or {}) if failed else {}
        report_date = pointer.report_date if pointer is not None else None
        publication_age_days = (
            (current.astimezone(_NEW_YORK).date() - report_date).days
            if report_date is not None
            else None
        )

        return {
            "generated_at": current.isoformat(),
            "latest_successful_run_id": published.id if published else None,
            "latest_failed_run_id": failed.id if failed else None,
            "latest_failed_status": failed.status if failed else None,
            "source_report_date": report_date.isoformat() if report_date else None,
            "source_retrieved_at": source_metadata.get("retrieved_at"),
            "expected_instrument_count": (
                published.expected_instrument_count if published else 0
            ),
            "observed_instrument_count": (
                published.observed_instrument_count if published else 0
            ),
            "validation_reason_codes": list(
                failed_diagnostics.get("reason_codes")
                or (failed_diagnostics.get("validation") or {}).get("reason_codes")
                or []
            ),
            "price_counts": {
                "exact_or_proxy": int(prices.get("available_count") or 0),
                "partial": int(prices.get("partial_count") or 0),
                "unavailable": int(prices.get("unavailable_count") or 0),
            },
            "duration_seconds": _duration_seconds(published),
            "retry_count": int(source_metadata.get("retry_count") or 0),
            "publication_age_days": publication_age_days,
            "stale": publication_age_days is None or publication_age_days > 10,
        }


def _duration_seconds(run: CotImportRun | None) -> float | None:
    if run is None or run.created_at is None or run.completed_at is None:
        return None
    created_at = _as_utc(run.created_at)
    completed_at = _as_utc(run.completed_at)
    return max(0.0, (completed_at - created_at).total_seconds())


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
