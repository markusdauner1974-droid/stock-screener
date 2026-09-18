from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.scripts import export_static_cot


def test_refreshes_and_exports_cot_in_one_independent_command(monkeypatch, tmp_path):
    calls: list[object] = []
    db = object()

    class SessionContext:
        def __enter__(self):
            return db

        def __exit__(self, *_args):
            return False

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
    monkeypatch.setattr(export_static_cot, "SessionLocal", SessionContext)
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
