from __future__ import annotations

from app.scripts.download_static_market_fallbacks import find_cot_artifact_dir
from app.scripts.validate_static_market_artifacts import (
    validate_optional_cot_artifacts,
)
from app.services.static_cot_exporter import StaticCotExporter
from tests.unit.test_cot_queries import service


def test_fallback_finder_and_validator_recognize_nested_cot_artifact(tmp_path):
    wrapper = tmp_path / "static-cot-global"
    cot_dir = wrapper / "cot"
    StaticCotExporter(service()).export(
        cot_dir,
        generated_at="2026-09-16T09:00:00Z",
    )

    assert find_cot_artifact_dir(wrapper) == cot_dir
    assert validate_optional_cot_artifacts(wrapper, None)["report_date"] == "2026-09-08"


def test_cot_validator_uses_fallback_when_current_is_corrupt(tmp_path):
    current = tmp_path / "current"
    current.mkdir()
    (current / "index.json").write_text("not-json")
    fallback = tmp_path / "fallback" / "cot"
    StaticCotExporter(service()).export(
        fallback,
        generated_at="2026-09-16T09:00:00Z",
    )

    assert validate_optional_cot_artifacts(current, fallback)["publication_id"] == 7
