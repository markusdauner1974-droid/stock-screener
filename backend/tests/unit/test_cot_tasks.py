from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.tasks.data_fetch_lock import disable_serialized_data_fetch_lock
from app.use_cases.cot.refresh import CotRefreshResult


def test_refresh_task_returns_published_summary(monkeypatch):
    from app.interfaces.tasks import cot_tasks as module

    closed = []
    db = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        module,
        "get_refresh_cot_use_case",
        lambda session: SimpleNamespace(
            execute=lambda command: CotRefreshResult(
                status="published",
                run_id=42,
                report_date=date(2026, 9, 8),
                instrument_count=31,
                price_unavailable_count=1,
            )
        ),
    )

    with disable_serialized_data_fetch_lock():
        result = module.refresh_cot.run(origin="scheduled")

    assert result == {
        "status": "published",
        "run_id": 42,
        "report_date": "2026-09-08",
        "instrument_count": 31,
        "price_unavailable_count": 1,
    }
    assert closed == [True]
