from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.infra.db.models.cot import (
    CotImportRun,
    CotInstrument,
    CotPublicationPointer,
    CotWeeklyPosition,
)
from app.services.cot_operations_service import CotOperationsService


def test_operations_snapshot_reports_redacted_health_and_staleness():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CotInstrument.__table__,
            CotImportRun.__table__,
            CotWeeklyPosition.__table__,
            CotPublicationPointer.__table__,
        ],
    )
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    published = CotImportRun(
        origin="scheduled",
        status="published",
        observed_report_date=date(2026, 9, 1),
        expected_instrument_count=31,
        observed_instrument_count=31,
        diagnostics_json={
            "validation": {"reason_codes": []},
            "prices": {
                "available_count": 24,
                "partial_count": 6,
                "unavailable_count": 1,
            },
        },
        source_metadata_json={
            "retrieved_at": "2026-09-04T21:00:00+00:00",
            "retry_count": 2,
        },
        registry_version="cot-curated-v1",
        calculation_version="cot-positions-v1",
        schema_version="cot-v1",
        created_at=datetime(2026, 9, 4, 21, tzinfo=timezone.utc),
        completed_at=datetime(2026, 9, 4, 21, 0, 12, tzinfo=timezone.utc),
        published_at=datetime(2026, 9, 4, 21, 0, 12, tzinfo=timezone.utc),
    )
    failed = CotImportRun(
        origin="scheduled",
        status="failed_quality",
        expected_instrument_count=31,
        observed_instrument_count=29,
        diagnostics_json={"reason_codes": ["incomplete_latest_family_coverage"]},
        registry_version="cot-curated-v1",
        calculation_version="cot-positions-v1",
        schema_version="cot-v1",
    )
    no_change = CotImportRun(
        origin="scheduled",
        status="no_change",
        expected_instrument_count=31,
        observed_instrument_count=31,
        diagnostics_json={
            "prices": {
                "available_count": 30,
                "partial_count": 1,
                "unavailable_count": 0,
            },
        },
        registry_version="cot-curated-v1",
        calculation_version="cot-positions-v1",
        schema_version="cot-v1",
    )
    db.add_all((published, failed, no_change))
    db.flush()
    db.add(
        CotPublicationPointer(
            key="latest_published",
            run_id=published.id,
            report_date=date(2026, 9, 1),
        )
    )
    db.commit()

    result = CotOperationsService().snapshot(
        db,
        now=datetime(2026, 9, 12, 12, tzinfo=timezone.utc),
    )

    assert result["latest_successful_run_id"] == published.id
    assert result["latest_failed_run_id"] == failed.id
    assert result["source_report_date"] == "2026-09-01"
    assert result["source_retrieved_at"] == "2026-09-04T21:00:00+00:00"
    assert result["expected_instrument_count"] == 31
    assert result["observed_instrument_count"] == 31
    assert result["price_counts"] == {"exact_or_proxy": 30, "partial": 1, "unavailable": 0}
    assert result["duration_seconds"] == 12.0
    assert result["retry_count"] == 2
    assert result["publication_age_days"] == 11
    assert result["stale"] is True
    assert "source_metadata_json" not in result
    db.close()
    engine.dispose()
