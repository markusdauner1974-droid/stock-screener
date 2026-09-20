from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace

import pytest
from app.scripts import export_static_cot


def test_refreshes_and_exports_cot_in_one_independent_command(monkeypatch, tmp_path):
    calls: list[object] = []
    db = object()

    class RefreshUseCase:
        def execute(self, command):
            calls.append(("refresh", command.origin, command.force))
            return SimpleNamespace(
                status="published",
                run_id=42,
                report_date=date(2026, 9, 15),
            )

    class Exporter:
        def __init__(self, queries):
            calls.append(("queries", queries))

        def export(self, output_dir, *, generated_at):
            calls.append(("export", output_dir, generated_at))
            return {"publication_id": 42, "report_date": "2026-09-15"}

    monkeypatch.setattr(export_static_cot, "prepare_runtime", lambda: calls.append("prepare"))
    monkeypatch.setattr(export_static_cot, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(
        export_static_cot,
        "get_refresh_cot_use_case",
        lambda session: RefreshUseCase() if session is db else None,
    )
    monkeypatch.setattr(
        export_static_cot,
        "get_cot_queries",
        lambda session: "queries" if session is db else None,
    )
    monkeypatch.setattr(export_static_cot, "StaticCotExporter", Exporter)

    output_dir = tmp_path / "cot"
    assert export_static_cot.main(["--output-dir", str(output_dir)]) == 0

    assert calls[0] == "prepare"
    assert calls[1] == ("refresh", "static_build", False)
    assert calls[2] == ("queries", "queries")
    assert calls[3][0:2] == ("export", output_dir)
    assert calls[3][2].endswith("Z")


def test_failed_quality_refresh_reports_reasons_without_exporting(
    monkeypatch, tmp_path
):
    db = object()

    class RefreshUseCase:
        def execute(self, _command):
            return SimpleNamespace(
                status="failed_quality",
                run_id=42,
                reason_codes=(
                    "reported_long_reconciliation_failed",
                    "reported_short_reconciliation_failed",
                ),
            )

    monkeypatch.setattr(export_static_cot, "prepare_runtime", lambda: None)
    monkeypatch.setattr(export_static_cot, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(
        export_static_cot,
        "get_refresh_cot_use_case",
        lambda session: RefreshUseCase() if session is db else None,
    )
    monkeypatch.setattr(
        export_static_cot,
        "StaticCotExporter",
        lambda _queries: pytest.fail("export must not run after a failed refresh"),
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "failed_quality.*reported_long_reconciliation_failed.*"
            "reported_short_reconciliation_failed"
        ),
    ):
        export_static_cot.main(["--output-dir", str(tmp_path / "cot")])
