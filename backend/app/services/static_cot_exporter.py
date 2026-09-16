"""Atomic exporter for live/static-parity COT read models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.infra.serialization import json_safe
from app.schemas.cot import CotCatalogResponse, CotHistoryResponse
from app.services.atomic_directory_publisher import AtomicDirectoryPublisher
from app.services.static_cot_contract import (
    STATIC_COT_SCHEMA_VERSION,
    validate_static_cot_artifact,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), allow_nan=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


class StaticCotExporter:
    def __init__(self, queries, *, publisher: AtomicDirectoryPublisher | None = None):
        self._queries = queries
        self._publisher = publisher or AtomicDirectoryPublisher()

    def export(self, cot_dir: Path, *, generated_at: str) -> dict[str, Any]:
        destination = Path(cot_dir)
        if destination.name != "cot":
            raise ValueError("Static COT destination must be named 'cot'")
        catalog = CotCatalogResponse.from_view(self._queries.catalog())

        def populate(stage: Path) -> dict[str, Any]:
            histories: dict[str, dict[str, str]] = {}
            for instrument in catalog.instruments:
                history = CotHistoryResponse.from_view(
                    self._queries.history(instrument.slug, "5y")
                )
                _write_json(
                    stage / f"{instrument.slug}.json",
                    history.model_dump(mode="json"),
                )
                histories[instrument.slug] = {
                    "path": f"cot/{instrument.slug}.json"
                }
            publication = catalog.publication
            index = {
                "schema_version": STATIC_COT_SCHEMA_VERSION,
                "data_schema_version": publication.schema_version,
                "calculation_version": publication.calculation_version,
                "publication_id": publication.publication_id,
                "report_date": publication.report_date.isoformat(),
                "generated_at": generated_at,
                "default_slug": catalog.default_slug,
                "catalog": catalog.model_dump(mode="json"),
                "histories": histories,
            }
            _write_json(stage / "index.json", index)
            return index

        return self._publisher.publish(
            destination,
            populate,
            validate=validate_static_cot_artifact,
        )


__all__ = ["StaticCotExporter"]
