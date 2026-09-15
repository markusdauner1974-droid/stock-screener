"""IBD Classification workflow trigger/concurrency guardrails."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ALL_MARKETS = ["US", "HK", "IN", "JP", "KR", "TW", "CN", "CA", "DE", "SG", "AU", "MY"]
_SCHEDULED_MARKETS = ["US", "JP", "IN", "HK", "KR", "TW", "CN", "CA", "DE", "SG", "AU", "MY"]
_SCHEDULED_CRONS = [
    "30 14 * * 6",
    "30 17 * * 6",
    "30 20 * * 6",
    "30 23 * * 6",
    "30 2 * * 0",
    "30 5 * * 0",
    "30 8 * * 0",
    "30 11 * * 0",
    "30 14 * * 0",
    "30 17 * * 0",
    "30 20 * * 0",
    "30 23 * * 0",
]


def _workflow() -> dict:
    return yaml.safe_load(
        (_PROJECT_ROOT / ".github/workflows/ibd-classification.yml").read_text(
            encoding="utf-8"
        )
    )


def _select_markets_script(workflow: dict) -> str:
    return workflow["jobs"]["select_markets"]["steps"][0]["run"]


def test_ibd_workflow_uses_scheduled_single_market_runs_instead_of_workflow_run():
    workflow = _workflow()

    trigger = workflow[True]

    assert "workflow_run" not in trigger
    assert [entry["cron"] for entry in trigger["schedule"]] == _SCHEDULED_CRONS


def test_ibd_scheduled_crons_map_to_single_markets_in_order():
    workflow = _workflow()

    selector = _select_markets_script(workflow)

    for cron, market in zip(_SCHEDULED_CRONS, _SCHEDULED_MARKETS, strict=True):
        assert f'schedule:"{cron}") markets=\'["{market}"]\' ;;' in selector


def test_ibd_manual_all_keeps_full_serial_market_matrix():
    workflow = _workflow()

    selector = _select_markets_script(workflow)
    match = re.search(r"^ALL_MARKETS='(\[[^']+\])'", selector, re.MULTILINE)
    assert match is not None
    assert json.loads(match.group(1)) == _ALL_MARKETS

    classify = workflow["jobs"]["classify"]
    assert classify["strategy"]["max-parallel"] == 1
    assert classify["strategy"]["matrix"]["market"] == (
        "${{ fromJSON(needs.select_markets.outputs.markets) }}"
    )


def test_ibd_concurrency_is_scoped_to_the_selected_market_run():
    workflow = _workflow()

    concurrency = workflow["concurrency"]
    group = concurrency["group"]

    assert "github.event.schedule" in group
    assert "github.event.inputs.market" in group
    assert "|| 'all'" in group
    assert concurrency["cancel-in-progress"] == (
        "${{ github.event_name != 'workflow_dispatch' || "
        "github.event.inputs.market != 'all' }}"
    )


def test_ibd_classify_jobs_serialize_same_market_across_trigger_types():
    workflow = _workflow()

    classify_concurrency = workflow["jobs"]["classify"]["concurrency"]

    assert classify_concurrency["group"] == (
        "${{ github.workflow }}-classify-${{ matrix.market }}"
    )
    assert classify_concurrency["cancel-in-progress"] is False


def test_ibd_workflow_defaults_llm_dispatch_pacing_to_opencode_budget():
    workflow = _workflow()

    classify_env = workflow["jobs"]["classify"]["env"]

    assert classify_env["IBD_LLM_MIN_INTERVAL_SECONDS"] == (
        "${{ vars.IBD_LLM_MIN_INTERVAL_SECONDS || '1.5' }}"
    )
