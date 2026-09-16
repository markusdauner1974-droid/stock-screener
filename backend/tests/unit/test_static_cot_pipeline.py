from __future__ import annotations

from app.scripts.download_static_market_fallbacks import find_cot_artifact_dir
from app.scripts.validate_static_market_artifacts import (
    validate_optional_cot_artifacts,
)
from app.services.static_cot_exporter import StaticCotExporter
from app.services.static_global_artifacts import (
    GLOBAL_STATIC_ARTIFACTS,
    find_global_artifact,
    validate_optional_global_artifact,
)
from app.services.static_options_exporter import StaticOptionsExporter
from tests.unit.test_cot_queries import service
from tests.unit.test_static_options_exporter import _item, _Queries, _run


def test_global_artifact_specs_find_nested_options_and_cot_bundles(tmp_path):
    options_dir = tmp_path / "options-wrapper" / "options"
    StaticOptionsExporter(_Queries(_run(_item("AAPL")))).export(
        options_dir,
        generated_at="2026-09-16T09:00:00Z",
    )
    cot_dir = tmp_path / "cot-wrapper" / "cot"
    StaticCotExporter(service()).export(
        cot_dir,
        generated_at="2026-09-16T09:00:00Z",
    )

    assert (
        find_global_artifact(
            GLOBAL_STATIC_ARTIFACTS["options"],
            options_dir.parent,
        )
        == options_dir
    )
    assert (
        find_global_artifact(
            GLOBAL_STATIC_ARTIFACTS["cot"],
            cot_dir.parent,
        )
        == cot_dir
    )
    assert (
        validate_optional_global_artifact(
            GLOBAL_STATIC_ARTIFACTS["cot"],
            cot_dir.parent,
            None,
        )["report_date"]
        == "2026-09-08"
    )


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
