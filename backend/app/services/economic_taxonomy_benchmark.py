"""Dependency-free fail-closed Economic Taxonomy benchmark evaluator."""

from __future__ import annotations

from typing import Any


class BenchmarkFailure(ValueError):
    def __init__(self, report: dict[str, Any]):
        failed = [row["name"] for row in report.get("cases", []) if not row["passed"]]
        details = ", ".join(failed or report.get("errors", ["benchmark_failed"]))
        super().__init__(f"economic taxonomy benchmark failed: {details}")
        self.report = report


_BENCHMARK_CATEGORIES = (
    "identities",
    "relationships",
    "assignments",
    "interpretation_selections",
    "retractions",
)


def evaluate_benchmark(
    fixtures: dict[str, Any],
    actual: dict[str, Any],
    *,
    taxonomy_hash: str,
    policy_bundle: str,
    fail_closed: bool = False,
) -> dict[str, Any]:
    """Compare every declared required/forbidden contract without defaults."""

    errors = []
    if not isinstance(fixtures.get("benchmark_schema_version"), int):
        errors.append("benchmark_fixture_version_missing")
    if actual.get("taxonomy_hash") != taxonomy_hash:
        errors.append("taxonomy_hash_mismatch")
    if actual.get("policy_bundle") != policy_bundle:
        errors.append("policy_bundle_mismatch")
    cases = fixtures.get("benchmark_cases")
    if not isinstance(cases, list) or not cases:
        errors.append("benchmark_fixtures_missing")
        cases = []
    actual_cases = actual.get("cases")
    if not isinstance(actual_cases, dict):
        errors.append("benchmark_actual_cases_missing")
        actual_cases = {}
    expected_names = {case.get("name") for case in cases}
    if len(expected_names) != len(cases):
        errors.append("duplicate_fixture_case")
    extra_names = set(actual_cases) - expected_names
    if extra_names:
        errors.append(f"unexpected_cases:{','.join(sorted(extra_names))}")

    outcomes = []
    for case in cases:
        name = case.get("name")
        required = case.get("required")
        forbidden = case.get("forbidden")
        case_errors = []
        if not isinstance(name, str) or not name:
            name = "<unnamed>"
            case_errors.append("name_required")
        if not isinstance(required, dict) or set(required) != set(
            _BENCHMARK_CATEGORIES
        ):
            case_errors.append("required_contract_incomplete")
            required = {}
        if not isinstance(forbidden, dict) or set(forbidden) != set(
            _BENCHMARK_CATEGORIES
        ):
            case_errors.append("forbidden_contract_incomplete")
            forbidden = {}
        observed = actual_cases.get(name)
        if not isinstance(observed, dict):
            case_errors.append("actual_case_missing")
            observed = {}
        elif set(observed) != set(_BENCHMARK_CATEGORIES):
            case_errors.append("actual_contract_incomplete")
        for category in _BENCHMARK_CATEGORIES:
            required_raw = required.get(category, [])
            forbidden_raw = forbidden.get(category, [])
            observed_raw = observed.get(category, [])
            if not isinstance(required_raw, list):
                case_errors.append(f"required_{category}_must_be_list")
                required_raw = []
            if not isinstance(forbidden_raw, list):
                case_errors.append(f"forbidden_{category}_must_be_list")
                forbidden_raw = []
            if not isinstance(observed_raw, list):
                case_errors.append(f"actual_{category}_must_be_list")
                observed_raw = []
            observed_values = set(observed_raw)
            required_values = set(required_raw)
            forbidden_values = set(forbidden_raw)
            missing = sorted(required_values - observed_values)
            present = sorted(forbidden_values & observed_values)
            if missing:
                case_errors.append(f"missing_{category}:{','.join(missing)}")
            if present:
                case_errors.append(f"forbidden_{category}:{','.join(present)}")
        outcomes.append(
            {"name": name, "passed": not case_errors, "errors": case_errors}
        )

    report = {
        "fixture_version": fixtures.get("benchmark_schema_version"),
        "taxonomy_hash": taxonomy_hash,
        "policy_bundle": policy_bundle,
        "passed": not errors and all(row["passed"] for row in outcomes),
        "errors": errors,
        "cases": outcomes,
    }
    if fail_closed and not report["passed"]:
        raise BenchmarkFailure(report)
    return report
