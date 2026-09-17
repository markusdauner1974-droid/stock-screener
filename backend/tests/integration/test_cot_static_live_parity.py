from __future__ import annotations

import json

from app.services.static_cot_exporter import StaticCotExporter
from tests.unit.test_cot_queries import service


def test_static_history_is_byte_value_equivalent_to_live_five_year_response(tmp_path):
    queries = service()
    cot_dir = tmp_path / "cot"
    StaticCotExporter(queries).export(
        cot_dir,
        generated_at="2026-09-16T09:00:00Z",
    )

    for instrument in queries.catalog().instruments:
        live = queries.history(instrument.slug, "5y").model_dump(mode="json")
        static = json.loads((cot_dir / f"{instrument.slug}.json").read_text())
        assert static == live
