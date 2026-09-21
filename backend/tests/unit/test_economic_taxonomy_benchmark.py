from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.economic_taxonomy_migration import (
    BenchmarkFailure,
    evaluate_benchmark,
)
from scripts.run_economic_taxonomy_benchmark import main

FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "economic_taxonomy"
    / "contract_cases.json"
)


def _fixture():
    return json.loads(FIXTURE.read_text())


def _matching_actual(payload):
    return {
        "taxonomy_hash": "taxonomy-sha256",
        "policy_bundle": "policy-bundle-v1",
        "cases": {
            case["name"]: {
                category: sorted(values)
                for category, values in case["required"].items()
            }
            for case in payload["benchmark_cases"]
        },
    }


def test_contract_benchmark_covers_every_required_counterexample():
    payload = _fixture()

    assert {case["name"] for case in payload["benchmark_cases"]} == {
        "pseudo_theme_rejection",
        "tanker_segmentation",
        "ai_memory_cooccurrence",
        "ai_memory_hbm_specificity",
        "ai_security_mechanism_contrast",
        "copper_relationship_direction",
        "refining_split",
        "social_consolidation",
        "social_decision_conflict",
        "same_source_reclassification",
        "successful_empty_correction",
        "late_archive_after_corrected_empty_benchmark",
        "less_complete_recapture",
        "duplicate_route_deduplication",
    }
    for case in payload["benchmark_cases"]:
        assert set(case["required"]) == {
            "identities",
            "relationships",
            "assignments",
            "interpretation_selections",
            "retractions",
        }
        assert set(case["forbidden"]) == set(case["required"])


def test_benchmark_report_is_bound_to_taxonomy_and_policy_hashes():
    fixtures = _fixture()
    actual = _matching_actual(fixtures)

    report = evaluate_benchmark(
        fixtures,
        actual,
        taxonomy_hash="taxonomy-sha256",
        policy_bundle="policy-bundle-v1",
    )

    assert report["passed"] is True
    assert report["fixture_version"] == fixtures["benchmark_schema_version"]
    assert report["taxonomy_hash"] == "taxonomy-sha256"
    assert report["policy_bundle"] == "policy-bundle-v1"
    assert all(case["passed"] for case in report["cases"])


def test_benchmark_fails_closed_on_missing_required_or_present_forbidden():
    fixtures = _fixture()
    actual = _matching_actual(fixtures)
    actual["cases"]["refining_split"]["assignments"].remove(
        "mention:metals->theme:metals-refining"
    )
    actual["cases"]["refining_split"]["assignments"].append(
        "mention:metals->theme:petroleum-refining"
    )

    with pytest.raises(BenchmarkFailure) as exc_info:
        evaluate_benchmark(
            fixtures,
            actual,
            taxonomy_hash="taxonomy-sha256",
            policy_bundle="policy-bundle-v1",
            fail_closed=True,
        )

    assert "refining_split" in str(exc_info.value)


def test_benchmark_cli_returns_nonzero_for_hash_mismatch(tmp_path):
    fixtures = _fixture()
    actual = _matching_actual(fixtures)
    actual["taxonomy_hash"] = "wrong-taxonomy"
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(json.dumps(actual))
    report_path = tmp_path / "report.json"

    exit_code = main(
        [
            "--fixtures",
            str(FIXTURE),
            "--actual",
            str(actual_path),
            "--taxonomy-hash",
            "taxonomy-sha256",
            "--policy-bundle",
            "policy-bundle-v1",
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 1
    assert json.loads(report_path.read_text())["passed"] is False
