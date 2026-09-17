from __future__ import annotations

import json
import shutil

import pytest
from app.services.static_cot_artifact_selector import (
    StaticCotArtifactSelector,
    StaticCotUnavailable,
)
from app.services.static_cot_contract import validate_static_cot_artifact
from app.services.static_cot_exporter import StaticCotExporter

from tests.unit.test_cot_queries import service


def test_static_export_writes_index_and_31_five_year_histories(tmp_path):
    cot_dir = tmp_path / "cot"

    index = StaticCotExporter(service()).export(
        cot_dir,
        generated_at="2026-09-16T09:00:00Z",
    )

    assert index["schema_version"] == "static-cot-v1"
    assert index["default_slug"] == "sp-500"
    assert len(index["histories"]) == 31
    assert json.loads((cot_dir / "sp-500.json").read_text())["range"] == "5y"
    assert validate_static_cot_artifact(cot_dir) == index


def test_static_export_rejects_corrupt_or_unsafe_history_paths(tmp_path):
    cot_dir = tmp_path / "cot"
    StaticCotExporter(service()).export(
        cot_dir,
        generated_at="2026-09-16T09:00:00Z",
    )
    index_path = cot_dir / "index.json"
    index = json.loads(index_path.read_text())
    index["histories"]["sp-500"]["path"] = "../secret.json"
    index_path.write_text(json.dumps(index))

    with pytest.raises(ValueError, match="unsafe"):
        validate_static_cot_artifact(cot_dir)


@pytest.mark.parametrize("generated_at", [None, 17, "not-a-timestamp"])
def test_static_export_contract_rejects_invalid_generated_at(
    tmp_path, generated_at
):
    cot_dir = tmp_path / "cot"
    StaticCotExporter(service()).export(
        cot_dir,
        generated_at="2026-09-16T09:00:00Z",
    )
    index_path = cot_dir / "index.json"
    index = json.loads(index_path.read_text())
    index["generated_at"] = generated_at
    index_path.write_text(json.dumps(index))

    with pytest.raises(ValueError, match="generated timestamp"):
        validate_static_cot_artifact(cot_dir)


def test_selector_uses_newer_valid_report_date_and_rejects_no_candidate(tmp_path):
    current = tmp_path / "current" / "cot"
    fallback = tmp_path / "fallback" / "cot"
    output = tmp_path / "published" / "cot"
    StaticCotExporter(service()).export(
        current,
        generated_at="2026-09-16T09:00:00Z",
    )
    shutil.copytree(current, fallback)
    _rewrite_report_date(fallback, "2026-09-15")

    selected = StaticCotArtifactSelector().select(
        current_cot_dir=current,
        fallback_cot_dir=fallback,
        output_cot_dir=output,
    )

    assert selected["report_date"] == "2026-09-15"
    assert validate_static_cot_artifact(output)["report_date"] == "2026-09-15"
    with pytest.raises(StaticCotUnavailable):
        StaticCotArtifactSelector().select(
            current_cot_dir=tmp_path / "missing-current",
            fallback_cot_dir=tmp_path / "missing-fallback",
            output_cot_dir=tmp_path / "unused" / "cot",
        )


def _rewrite_report_date(cot_dir, report_date):
    index_path = cot_dir / "index.json"
    index = json.loads(index_path.read_text())
    index["report_date"] = report_date
    index["catalog"]["publication"]["report_date"] = report_date
    index_path.write_text(json.dumps(index))
    for entry in index["histories"].values():
        path = cot_dir / entry["path"].removeprefix("cot/")
        payload = json.loads(path.read_text())
        payload["publication"]["report_date"] = report_date
        path.write_text(json.dumps(payload))
