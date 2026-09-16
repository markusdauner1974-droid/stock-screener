"""Celery delivery boundary for the weekly official CFTC refresh."""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.database import SessionLocal
from app.domain.cot.models import (
    COT_CALCULATION_VERSION,
    COT_REGISTRY_VERSION,
)
from app.infra.providers.cftc_cot import DATASET_BY_FAMILY
from app.tasks.data_fetch_lock import serialized_data_fetch_task
from app.use_cases.cot.refresh import CotRefreshCommand
from app.wiring.bootstrap import get_refresh_cot_use_case


logger = logging.getLogger(__name__)


@serialized_data_fetch_task(
    celery_app,
    "weekly-cot-refresh",
    name="app.interfaces.tasks.cot_tasks.refresh_cot",
)
def refresh_cot(
    self,
    *,
    origin: str = "scheduled",
    force: bool = False,
) -> dict:
    db = SessionLocal()
    try:
        result = get_refresh_cot_use_case(db).execute(
            CotRefreshCommand(origin=origin, force=force)
        )
        return {
            "status": result.status,
            "run_id": result.run_id,
            "report_date": (
                result.report_date.isoformat() if result.report_date else None
            ),
            "instrument_count": result.instrument_count,
            "price_unavailable_count": result.price_unavailable_count,
        }
    except Exception:
        logger.exception(
            "COT refresh failed datasets=%s registry=%s calculation=%s",
            sorted(DATASET_BY_FAMILY.values()),
            COT_REGISTRY_VERSION,
            COT_CALCULATION_VERSION,
        )
        raise
    finally:
        db.close()
