from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs/runbooks/economic-taxonomy-cutover.md"
DESIGN = ROOT / "docs/superpowers/specs/2026-09-20-economic-taxonomy-design.md"
PLAN = ROOT / "docs/superpowers/plans/2026-09-21-economic-taxonomy.md"
APP = ROOT / "backend/app"


def test_runbook_names_catchup_barrier_recovery_and_exact_commands():
    text = RUNBOOK.read_text(encoding="utf-8")
    for phrase in (
        "catch-up outside the publication transaction",
        "exclusive writer fence",
        "generation-input manifest",
        "reader capability",
        "final compare-and-set barrier",
        "rollback_recovery",
        "run_required_economic_taxonomy_postgres.py",
        "publish_economic_taxonomy.py",
    ):
        assert phrase in text


def test_runbook_has_every_mandatory_stop_condition_and_backlog_rule():
    text = RUNBOOK.read_text(encoding="utf-8")
    for phrase in (
        "unresolved allocation",
        "unresolved Social conflict",
        "parent generation mismatch",
        "semantic-invalidation mismatch",
        "pending required prior-generation delivery",
        "unstaged candidate projection",
        "stale snapshot hash",
        "missing reader capability",
        "benchmark failure",
        "unauthorized principal",
        "skipped required PostgreSQL node",
        "ordinary revisions after C are backlog",
    ):
        assert phrase in text


def test_deferred_boundary_is_explicit_and_non_blocking_for_v1():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "None of these capabilities is required for V1 cutover" in text
    assert "approved driver-pack design and ADR" in text
    for capability in (
        "Directional economic driver pack",
        "Remove legacy Theme/Social storage or compatibility writes",
        "Automatically approve structural changes",
        "Recursive ontology propagation",
        "General asset master beyond `StockUniverse`",
        "Statistical source independence",
    ):
        assert capability in text


def test_production_ready_documents_link_runbook_and_rehearsal_artifact():
    design = DESIGN.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    for text in (design, plan):
        assert "production-ready" in text
        assert "docs/runbooks/economic-taxonomy-cutover.md" in text
        assert "docs/runbooks/artifacts/economic-taxonomy-rehearsal-2026-09-21.md" in text


def test_no_runtime_api_or_schema_reserves_directional_fundamental_momentum():
    offenders = []
    for path in APP.rglob("*.py"):
        if "fundamental_momentum" in path.read_text(encoding="utf-8").casefold():
            offenders.append(path.relative_to(APP).as_posix())
    assert offenders == []
