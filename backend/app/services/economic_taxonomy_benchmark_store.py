"""Durable, fail-closed benchmark results used by taxonomy publication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.economic_taxonomy_runtime import TaxonomyBenchmarkResult
from app.utils.file_hashing import canonical_json_sha256


def register_verified_benchmark(
    session: Session,
    *,
    report: Mapping[str, Any],
    verified_by: str,
) -> TaxonomyBenchmarkResult:
    payload = dict(report)
    if not payload.get("passed"):
        raise ValueError("benchmark_result_not_passed")
    taxonomy_hash = str(payload.get("taxonomy_hash") or "").strip()
    policy_bundle = str(payload.get("policy_bundle") or "").strip()
    fixture_version = payload.get("fixture_version")
    if not taxonomy_hash:
        raise ValueError("benchmark_taxonomy_hash_required")
    if not policy_bundle:
        raise ValueError("benchmark_policy_bundle_required")
    if not isinstance(fixture_version, int):
        raise TypeError("benchmark_fixture_version_required")
    if not verified_by.strip():
        raise ValueError("benchmark_verifier_required")

    report_hash = canonical_json_sha256(payload)
    existing = session.scalar(
        select(TaxonomyBenchmarkResult).where(
            TaxonomyBenchmarkResult.taxonomy_semantic_hash == taxonomy_hash,
            TaxonomyBenchmarkResult.policy_bundle == policy_bundle,
            TaxonomyBenchmarkResult.report_hash == report_hash,
        )
    )
    if existing is not None:
        return existing
    result = TaxonomyBenchmarkResult(
        taxonomy_semantic_hash=taxonomy_hash,
        policy_bundle=policy_bundle,
        fixture_version=fixture_version,
        report=payload,
        report_hash=report_hash,
        passed=True,
        verified_by=verified_by.strip(),
    )
    session.add(result)
    session.flush()
    return result


def find_verified_benchmark(
    session: Session,
    *,
    taxonomy_semantic_hash: str,
    policy_bundle: str,
) -> dict[str, Any]:
    result = session.scalar(
        select(TaxonomyBenchmarkResult)
        .where(
            TaxonomyBenchmarkResult.taxonomy_semantic_hash
            == taxonomy_semantic_hash,
            TaxonomyBenchmarkResult.policy_bundle == policy_bundle,
            TaxonomyBenchmarkResult.passed.is_(True),
        )
        .order_by(
            TaxonomyBenchmarkResult.created_at.desc(),
            TaxonomyBenchmarkResult.id.desc(),
        )
        .limit(1)
    )
    if result is None:
        raise LookupError("benchmark_result_missing")
    return verify_benchmark_reference(
        session,
        {
            "benchmark_result_id": str(result.id),
            "report_hash": result.report_hash,
        },
        taxonomy_semantic_hash=taxonomy_semantic_hash,
        policy_bundle=policy_bundle,
    )


def verify_benchmark_reference(
    session: Session,
    reference: Mapping[str, Any],
    *,
    taxonomy_semantic_hash: str,
    policy_bundle: str,
) -> dict[str, Any]:
    raw_id = reference.get("benchmark_result_id")
    if not raw_id:
        raise LookupError("benchmark_result_missing")
    result = session.get(TaxonomyBenchmarkResult, UUID(str(raw_id)))
    if result is None:
        raise LookupError("benchmark_result_missing")
    if canonical_json_sha256(result.report) != result.report_hash:
        raise ValueError("benchmark_result_hash_mismatch")
    expected_report_hash = reference.get("report_hash")
    if expected_report_hash and expected_report_hash != result.report_hash:
        raise ValueError("benchmark_result_hash_mismatch")
    if (
        result.report.get("taxonomy_hash") != taxonomy_semantic_hash
        or result.report.get("policy_bundle") != policy_bundle
        or result.report.get("passed") is not True
    ):
        raise ValueError("benchmark_result_contract_mismatch")
    return {
        **dict(result.report),
        "benchmark_result_id": str(result.id),
        "report_hash": result.report_hash,
        "verified_by": result.verified_by,
    }
