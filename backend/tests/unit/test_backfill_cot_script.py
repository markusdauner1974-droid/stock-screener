from __future__ import annotations

from contextlib import contextmanager
from datetime import date

from app.scripts.backfill_cot import main
from app.use_cases.cot.refresh import CotRefreshResult


def test_backfill_runs_one_forced_administrative_refresh(capsys):
    commands = []

    class FakeUseCase:
        def execute(self, command):
            commands.append(command)
            return CotRefreshResult(
                status="published",
                run_id=42,
                report_date=date(2026, 9, 8),
                instrument_count=31,
                price_unavailable_count=1,
            )

    @contextmanager
    def fake_factory():
        yield FakeUseCase()

    exit_code = main([], use_case_factory=fake_factory)

    assert exit_code == 0
    assert commands[0].origin == "administrative_backfill"
    assert commands[0].force is True
    assert '"run_id": 42' in capsys.readouterr().out


def test_backfill_returns_nonzero_for_quality_failure():
    class FakeUseCase:
        def execute(self, _command):
            return CotRefreshResult.failed(9, ("source_history_truncated",))

    @contextmanager
    def fake_factory():
        yield FakeUseCase()

    assert main([], use_case_factory=fake_factory) == 1


def test_backfill_treats_a_newer_competing_publication_as_success():
    class FakeUseCase:
        def execute(self, _command):
            return CotRefreshResult(
                status="superseded",
                run_id=41,
                report_date=date(2026, 9, 8),
                instrument_count=31,
                price_unavailable_count=0,
            )

    @contextmanager
    def fake_factory():
        yield FakeUseCase()

    assert main([], use_case_factory=fake_factory) == 0
