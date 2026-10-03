"""#474: CI gate for legacy Theme reads that bypass authority routing.

Retirement criterion 4 of the economic taxonomy audit
(docs/runbooks/artifacts/economic-taxonomy-readiness-audit-2026-10-01.md).
Every API route, Celery task and MCP tool that reaches a legacy authority model
without routing through ``EconomicThemeReader`` must be listed in ``ALLOWLIST``
with its reason. Each entry is a tracked item to route, replace or remove;
retirement needs the list to be empty.
"""

from __future__ import annotations

import textwrap

import pytest

from tests.helpers.legacy_theme_read_gate import Index, unrouted_legacy_reads

_REVIEW = "Audit 'Readers with no routing': review/merge GETs serve legacy clusters and suggestions."
_INTELLIGENCE = "Audit 'Readers with no routing': equivalence and development GETs serve legacy identities."
_WATCHLIST_ALERTS = "Audit 'Readers with no routing': watchlist stewardship serves ThemeAlert."
_VALIDATION_ALERTS = "Audit 'Readers with no routing': validation_service serves ThemeAlert."
_MCP_ALERTS = (
    "Audit 'Readers with no routing': MCP market_overview reads ThemeAlert (_recent_alerts). "
    "Assistant and /mcp routes reach it through MarketCopilotService's tool table."
)
_TELEMETRY = "Audit 'Readers with no routing': matching telemetry serves legacy ThemeMention stats."
_DEVELOPMENTS = "Audit 'Readers with no routing': development preparation reads ThemeMention and links."
_CONTENT = "Audit 'Readers with no routing': content listing annotates items with ThemeMention."
_SOCIAL_PREPARATION = (
    "Audit 'Readers with no routing': every live Social run prepares baskets from legacy "
    "theme tables before its economic-mode check; move it before retirement."
)
_SNAPSHOT_BUILDER = (
    "Audit 'Readers with no routing': the economic snapshot builder reads legacy "
    "ThemeDevelopmentTheme links; migrate them before retirement."
)
_PIPELINE_DIAGNOSTICS = "Audit 'Readers with no routing': pipeline diagnostics read legacy tables."
_SOCIAL_OPERATIONS = "Audit 'Readers with no routing': Social operations snapshot counts legacy associations."
_SOCIAL_ASSOCIATIONS = "Audit 'Readers with no routing': admin associations list serves legacy associations."
_ROLLBACK = (
    "Audit 'Rollback machinery (keep until retirement)': compatibility delivery "
    "maintains legacy projections."
)
_SOCIAL_BRIDGE = (
    "Audit 'Rollback machinery (keep until retirement)': the economic Social taxonomy "
    "adapter keeps Social associations bridged, and economic-mode decisions revise them."
)

# entry point -> (reason, the legacy models it is expected to read)
ALLOWLIST: dict[str, tuple[str, set[str]]] = {
    "GET /api/v1/themes/merge-suggestions": (
        _REVIEW,
        {"ThemeCluster", "ThemeMergeSuggestion"},
    ),
    "GET /api/v1/themes/merge-history": (
        _REVIEW,
        {"ThemeMergeHistory"},
    ),
    "GET /api/v1/themes/merge-plan/dry-run": (
        _REVIEW,
        {"ThemeCluster", "ThemeEmbedding"},
    ),
    "GET /api/v1/themes/candidates/queue": (
        _REVIEW,
        {"ThemeCluster", "ThemeEquivalenceOperation", "ThemeMention", "ThemeMetrics"},
    ),
    "GET /api/v1/themes/relationship-graph": (
        _REVIEW,
        {"ThemeCluster", "ThemeEquivalenceOperation", "ThemeRelationship"},
    ),
    "GET /api/v1/themes/equivalence/preview": (
        _INTELLIGENCE,
        {"ThemeCluster", "ThemeEquivalenceOperation", "ThemeMention"},
    ),
    "GET /api/v1/themes/equivalence/history": (
        _INTELLIGENCE,
        {"ThemeEquivalenceOperation"},
    ),
    "GET /api/v1/themes/equivalence/search": (
        _INTELLIGENCE,
        {"ThemeCluster", "ThemeEquivalenceOperation"},
    ),
    "GET /api/v1/themes/{theme_id}/developments": (
        _INTELLIGENCE,
        {"ThemeCluster", "ThemeDevelopmentTheme", "ThemeEquivalenceOperation", "ThemeMention"},
    ),
    "GET /api/v1/user-watchlists/{watchlist_id}/stewardship": (
        _WATCHLIST_ALERTS,
        {"ThemeAlert"},
    ),
    "GET /api/v1/validation/overview": (
        _VALIDATION_ALERTS,
        {"ThemeAlert", "ThemeCluster"},
    ),
    "GET /api/v1/stocks/{symbol}/validation": (
        _VALIDATION_ALERTS,
        {"ThemeAlert", "ThemeCluster"},
    ),
    "mcp market_overview": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "POST /mcp/": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "GET /api/v1/assistant/health": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "GET /api/v1/assistant/conversations": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "POST /api/v1/assistant/conversations": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "GET /api/v1/assistant/conversations/{conversation_id}": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "POST /api/v1/assistant/conversations/{conversation_id}/messages": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "POST /api/v1/assistant/watchlist-add-preview": (
        _MCP_ALERTS,
        {"ThemeAlert"},
    ),
    "GET /api/v1/themes/matching/telemetry": (
        _TELEMETRY,
        {"ThemeMention"},
    ),
    "task app.tasks.theme_intelligence_tasks.prepare_developments": (
        _DEVELOPMENTS,
        {"ThemeCluster", "ThemeDevelopmentTheme", "ThemeEquivalenceOperation", "ThemeMention"},
    ),
    "POST /api/v1/themes/developments/backfill": (
        _DEVELOPMENTS,
        {"ThemeCluster", "ThemeMention"},
    ),
    "GET /api/v1/themes/content": (
        _CONTENT,
        {"ThemeMention", "table:theme_mentions"},
    ),
    "GET /api/v1/themes/content/export": (
        _CONTENT,
        {"ThemeMention", "table:theme_mentions"},
    ),
    "task app.interfaces.tasks.social_signal_tasks.refresh_social_signals": (
        _SOCIAL_PREPARATION,
        {"SocialThemeAssociation", "ThemeAlias", "ThemeCluster", "ThemeConstituent", "ThemeMention"},
    ),
    "task app.interfaces.tasks.social_signal_tasks.resume_social_analysis": (
        _SOCIAL_PREPARATION,
        {"SocialThemeAssociation", "ThemeAlias", "ThemeCluster", "ThemeConstituent", "ThemeMention"},
    ),
    "task app.tasks.economic_taxonomy_tasks.refresh_economic_taxonomy_generation": (
        _SNAPSHOT_BUILDER,
        {"ThemeDevelopmentTheme"},
    ),
    "GET /api/v1/themes/pipeline/state-health": (
        _PIPELINE_DIAGNOSTICS,
        {"ThemeMention"},
    ),
    "GET /api/v1/themes/pipeline/observability": (
        _PIPELINE_DIAGNOSTICS,
        {"ThemeCluster", "ThemeMention", "ThemeMergeSuggestion"},
    ),
    "GET /api/v1/operations/social-signals": (
        _SOCIAL_OPERATIONS,
        {"SocialThemeAssociation"},
    ),
    "GET /api/v1/social-signals/admin/health": (
        _SOCIAL_OPERATIONS,
        {"SocialThemeAssociation"},
    ),
    "GET /api/v1/social-signals/admin/associations": (
        _SOCIAL_ASSOCIATIONS,
        {"SocialThemeAssociation", "ThemeCluster"},
    ),
    "task app.tasks.economic_taxonomy_tasks.deliver_taxonomy_outbox": (
        _ROLLBACK,
        {"SocialThemeAssociation", "SocialThemeDecision", "ThemeCluster", "ThemeConstituent"},
    ),
    "task app.tasks.economic_taxonomy_tasks.process_economic_taxonomy_work": (
        _SOCIAL_BRIDGE,
        {"SocialThemeAssociation"},
    ),
    "POST /api/v1/social-signals/admin/associations/{association_id}/decision": (
        _SOCIAL_BRIDGE,
        {"SocialThemeAssociation"},
    ),
}


@pytest.fixture(scope="module")
def findings():
    from app.celery_app import celery_app
    from app.main import app

    return unrouted_legacy_reads(app, celery_app)


def _short(qualname):
    return ".".join(qualname.rsplit(".", 2)[-2:])


def test_no_new_unrouted_legacy_theme_reads(findings):
    # Keyed by entry point and model, so new debt under an allowlisted entry
    # point fails too. Not by call path: refactors would churn it.
    new = [
        finding
        for entry, found in sorted(findings.items())
        for finding in found
        if finding.model not in ALLOWLIST.get(entry, ("", set()))[1]
    ]
    report = "\n".join(
        f"  {f.entry}: {f.model} via {' > '.join(_short(p) for p in f.path)}" for f in new
    )
    assert not new, (
        "These entry points read legacy Theme tables without routing through "
        "EconomicThemeReader (or a #472 guard):\n"
        f"{report}\n"
        "Route the read by authority mode, or add it to ALLOWLIST with a reason."
    )


def test_allowlist_has_no_stale_entries(findings):
    stale = {
        entry: sorted(models - {f.model for f in findings.get(entry, [])})
        for entry, (_, models) in ALLOWLIST.items()
    }
    stale = {entry: models for entry, models in stale.items() if models}
    assert not stale, (
        f"No longer read unrouted (routed, removed or renamed); shrink ALLOWLIST: {stale}"
    )


# -- analyzer behaviour, on a small fixture package ----------------------------

_FIXTURE = {
    "models/theme.py": """
        class ThemeCluster: ...
    """,
    "services/economic_theme_read_service.py": """
        class EconomicThemeReader:
            def __init__(self, db): ...
    """,
    "services/readers.py": """
        from typing import Protocol
        from app.models.theme import ThemeCluster

        def read_clusters(db):
            return db.query(ThemeCluster).all()

        def read_raw(db):
            return db.execute("SELECT id FROM theme_clusters")

        class ClusterPort(Protocol):
            def load(self): ...

        class SqlClusterReader:
            def __init__(self, db):
                self.db = db

            def load(self):
                return read_clusters(self.db)

        class UseCase:
            def __init__(self, *, reader):
                self.reader = reader

            def run(self):
                return self.reader.load()

        def build_use_case(db):
            return UseCase(reader=SqlClusterReader(db))
    """,
    "entry.py": """
        from app.services.economic_theme_read_service import EconomicThemeReader
        from app.services.readers import build_use_case, read_clusters, read_raw

        def unrouted(db):
            return read_clusters(db)

        def raw_sql(db):
            return read_raw(db)

        def routed(db):
            if EconomicThemeReader(db):
                return []
            return read_clusters(db)

        def read_before_check(db):
            rows = read_clusters(db)
            if EconomicThemeReader(db):
                return []
            return rows

        def check_only_annotated(db, reader: EconomicThemeReader):
            return read_clusters(db)

        def check_in_other_branch(db, flag):
            if flag:
                EconomicThemeReader(db)
            return read_clusters(db)

        def injected(db):
            return build_use_case(db).run()

        def task_body(db):
            return read_clusters(db)

        def dispatches(db):
            task_body.delay(db)
    """,
}


@pytest.fixture(scope="module")
def fixture_index(tmp_path_factory):
    root = tmp_path_factory.mktemp("gate") / "app"
    for relative, source in _FIXTURE.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))
    for package in (root, root / "models", root / "services"):
        (package / "__init__.py").touch()
    return Index({"app.models.theme.ThemeCluster"}, {"theme_clusters"}, root=root)


def _reads(index, name):
    return index.legacy_reads(name, [index.funcs[f"app.entry.{name}"]])


def test_gate_reports_an_unrouted_read_with_its_call_path(fixture_index):
    [finding] = _reads(fixture_index, "unrouted")
    assert finding.model == "ThemeCluster"
    assert finding.path == ["app.entry.unrouted", "app.services.readers.read_clusters"]


def test_gate_reports_raw_sql_naming_a_legacy_table(fixture_index):
    assert [f.model for f in _reads(fixture_index, "raw_sql")] == ["table:theme_clusters"]


def test_gate_accepts_reads_routed_by_authority(fixture_index):
    assert _reads(fixture_index, "routed") == []


@pytest.mark.parametrize(
    "name", ["read_before_check", "check_only_annotated", "check_in_other_branch"]
)
def test_gate_counts_reads_the_authority_check_does_not_cover(fixture_index, name):
    assert [f.model for f in _reads(fixture_index, name)] == ["ThemeCluster"]


def test_gate_follows_injected_protocol_dependencies(fixture_index):
    [finding] = _reads(fixture_index, "injected")
    assert finding.path[-2:] == [
        "app.services.readers.SqlClusterReader.load",
        "app.services.readers.read_clusters",
    ]


def test_gate_leaves_celery_dispatch_to_the_task_entry_point(fixture_index):
    assert _reads(fixture_index, "dispatches") == []
