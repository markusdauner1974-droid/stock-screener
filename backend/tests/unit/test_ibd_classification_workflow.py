"""IBD Classification workflow trigger/concurrency guardrails."""

from __future__ import annotations

from pathlib import Path

import yaml


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _workflow() -> dict:
    return yaml.safe_load(
        (_PROJECT_ROOT / ".github/workflows/ibd-classification.yml").read_text(
            encoding="utf-8"
        )
    )


def test_failed_weekly_reference_completion_cannot_cancel_scheduled_ibd_fallback():
    workflow = _workflow()

    # This catches the September 2026 regression: GitHub emitted a workflow_run
    # event for a failed Weekly Reference Data run; the child skipped all jobs but
    # still cancelled the already-running scheduled fallback through concurrency.
    concurrency = workflow["concurrency"]
    group = concurrency["group"]
    cancel_in_progress = concurrency["cancel-in-progress"]

    assert "github.event_name == 'workflow_run'" in group
    assert "github.event.workflow_run.conclusion != 'success'" in group
    assert "format('noop-{0}', github.run_id)" in group
    assert cancel_in_progress == (
        "${{ github.event_name != 'workflow_run' || "
        "github.event.workflow_run.conclusion == 'success' }}"
    )


def test_ibd_workflow_keeps_successful_weekly_reference_trigger():
    workflow = _workflow()

    trigger = workflow[True]
    assert trigger["workflow_run"]["workflows"] == ["Weekly Reference Data"]
    assert trigger["workflow_run"]["types"] == ["completed"]
