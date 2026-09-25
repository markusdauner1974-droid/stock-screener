from __future__ import annotations

import ast
from pathlib import Path

BACKEND_APP = Path(__file__).resolve().parents[2] / "app"
AUTHORITY_AWARE_CONSUMERS = (
    "api/v1/themes_queries.py",
    "api/v1/themes_taxonomy.py",
    "api/v1/stocks.py",
    "services/digest_service.py",
    "services/social_confirmation_reader.py",
    "services/social_theme_market_service.py",
    "interfaces/mcp/market_copilot.py",
    "services/ui_snapshot_service.py",
)
LEGACY_SEMANTIC_NAMES = {
    "ThemeCluster",
    "ThemeMention",
    "ThemeMetrics",
    "ThemeConstituent",
}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


def test_economic_mode_consumers_declare_authority_aware_reader_boundary():
    missing = []
    for relative in AUTHORITY_AWARE_CONSUMERS:
        text = (BACKEND_APP / relative).read_text(encoding="utf-8")
        if "EconomicThemeReader" not in text:
            missing.append(relative)
    assert missing == []


def test_legacy_semantic_consumers_are_explicit_authority_adapters():
    allowed_legacy_adapters = {
        "api/v1/themes_queries.py",
        "api/v1/stocks.py",
        "services/digest_service.py",
        "services/social_confirmation_reader.py",
        "services/social_theme_market_service.py",
        "interfaces/mcp/market_copilot.py",
        "services/ui_snapshot_service.py",
    }
    actual_legacy_adapters = set()
    for relative in AUTHORITY_AWARE_CONSUMERS:
        imported = _imported_names(BACKEND_APP / relative) & LEGACY_SEMANTIC_NAMES
        if imported:
            actual_legacy_adapters.add(relative)
            text = (BACKEND_APP / relative).read_text(encoding="utf-8")
            assert ".source_name" in text, relative
    assert actual_legacy_adapters == allowed_legacy_adapters
