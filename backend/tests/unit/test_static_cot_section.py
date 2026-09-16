from __future__ import annotations

import json

from app.services.static_cot_exporter import StaticCotExporter
from app.services.static_cot_section import StaticCotSection
from tests.unit.test_cot_queries import service


def test_live_section_exports_and_advertises_one_root_global_asset(tmp_path):
    section = StaticCotSection(
        exporter_factory=lambda _db: StaticCotExporter(service()),
    )
    global_assets = {}

    result = section.compose_live(
        db=object(),
        output_dir=tmp_path,
        generated_at="2026-09-16T09:00:00Z",
        fallback_cot_dir=None,
        global_assets=global_assets,
    )

    assert result.selected is True
    assert global_assets == {"cot": {"path": "cot/index.json"}}
    assert json.loads((tmp_path / "cot" / "index.json").read_text())[
        "default_slug"
    ] == "sp-500"


def test_unavailable_section_does_not_advertise_or_block_other_assets(tmp_path):
    class MissingExporter:
        def export(self, *_args, **_kwargs):
            raise RuntimeError("no publication")

    section = StaticCotSection(exporter_factory=lambda _db: MissingExporter())
    global_assets = {"existing": {"path": "existing.json"}}

    result = section.compose_live(
        db=object(),
        output_dir=tmp_path,
        generated_at="2026-09-16T09:00:00Z",
        fallback_cot_dir=None,
        global_assets=global_assets,
    )

    assert result.selected is False
    assert global_assets == {"existing": {"path": "existing.json"}}
    assert result.warnings
