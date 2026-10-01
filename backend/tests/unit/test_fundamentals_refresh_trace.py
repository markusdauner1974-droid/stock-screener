"""Golden traces of the two weekly fundamentals refresh tasks (#429).

Every activity and progress call, plus the response, for each path of
``refresh_all_fundamentals`` and ``refresh_all_fundamentals_hybrid``. Keeps
the shared-step extraction behaviour-preserving. Regenerate deliberately with
``UPDATE_FUNDAMENTALS_TRACES=1``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.unit.test_fundamentals_tasks import (
    _hybrid_recording_stub,
    _prepare_refresh,
    _recording_cache,
    _runtime_markets,
)

GOLDEN = Path(__file__).parent / "golden" / "fundamentals_refresh_traces.json"
_VOLATILE = {"timestamp", "duration_seconds", "duration_minutes", "progress_state", "task_id"}
_TASKS = ("refresh_all_fundamentals", "refresh_all_fundamentals_hybrid")
_PATHS = ("github", "snapshot", "fetch", "empty", "fatal")


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in sorted(value.items()) if k not in _VOLATILE}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _snapshot_result(*_args, **_kwargs):
    return {
        "mode": "snapshot_publish",
        "universe": {"active_symbols": 1},
        "snapshot": {"published": True},
        "hydrate": None,
    }


def _run_path(monkeypatch, module, task_name, path):
    run_market = "US"
    if path == "github":
        _runtime_markets(monkeypatch, "US")
        _prepare_refresh(monkeypatch, module, github_statuses={"US": "success"})
    elif path == "snapshot":
        _runtime_markets(monkeypatch, "US")
        _prepare_refresh(monkeypatch, module, cutover=True)
        monkeypatch.setattr(module, "_run_snapshot_pipeline", _snapshot_result)
    elif path == "fetch":
        _runtime_markets(monkeypatch, "US", "HK")
        _prepare_refresh(monkeypatch, module)
        run_market = None  # unscoped: every enabled market
    elif path == "empty":
        _runtime_markets(monkeypatch, "US", "KR")
        _prepare_refresh(monkeypatch, module)
        run_market = "KR"  # enabled, but no KR stocks in the universe
    elif path == "fatal":
        _runtime_markets(monkeypatch, "US")
        _prepare_refresh(monkeypatch, module)

        def boom(*_args, **_kwargs):
            raise RuntimeError("universe unavailable")

        monkeypatch.setattr(module, "_load_active_universe_stocks", boom)

    fetched: list[str] = []
    monkeypatch.setattr(module, "get_fundamentals_cache", lambda: _recording_cache(fetched))
    monkeypatch.setattr(module, "HybridFundamentalsService", _hybrid_recording_stub(fetched))

    calls = []

    def recorder(name):
        return lambda *_args, **kwargs: calls.append([name, _clean(kwargs)])

    for name in (
        "mark_market_activity_started",
        "mark_market_activity_completed",
        "mark_market_activity_failed",
        "_mark_market_activity_failed_safely",
    ):
        monkeypatch.setattr(module, name, recorder(name))
    # Record progress at the throttle's entry: what it publishes depends on the clock.
    monkeypatch.setattr(module, "_maybe_publish_fundamentals_progress", recorder("progress"))

    kwargs = {"market": run_market}
    if task_name.endswith("hybrid"):
        kwargs["include_finviz"] = False
    result = getattr(module, task_name).run(**kwargs)
    return {"calls": calls, "fetched": sorted(fetched), "result": _clean(result)}


@pytest.mark.parametrize("path", _PATHS)
@pytest.mark.parametrize("task_name", _TASKS)
def test_refresh_trace_matches_golden(monkeypatch, task_name, path):
    import app.tasks.fundamentals_tasks as module

    trace = json.loads(json.dumps(_run_path(monkeypatch, module, task_name, path), default=str))
    key = f"{task_name}:{path}"

    if os.environ.get("UPDATE_FUNDAMENTALS_TRACES") == "1":
        golden = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        golden[key] = trace
        GOLDEN.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
        pytest.skip("golden trace updated")

    assert trace == json.loads(GOLDEN.read_text())[key]
