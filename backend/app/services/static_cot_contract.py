"""Validation contract for the root-global static COT bundle."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.cot import CotCatalogResponse, CotHistoryResponse

STATIC_COT_SCHEMA_VERSION = "static-cot-v1"


class StaticCotArtifactError(ValueError):
    """Raised when a static COT bundle is unsafe or internally inconsistent."""


def _require_finite(value: Any, *, location: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise StaticCotArtifactError(f"non-finite number at {location}")
    if isinstance(value, dict):
        for key, item in value.items():
            _require_finite(item, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _require_finite(item, location=f"{location}[{index}]")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StaticCotArtifactError(f"invalid COT artifact file: {path}") from exc
    if not isinstance(payload, dict):
        raise StaticCotArtifactError(f"COT artifact must be an object: {path}")
    _require_finite(payload, location=path.as_posix())
    return payload


def _history_path(cot_dir: Path, advertised: str) -> Path:
    relative = Path(str(advertised))
    if relative.is_absolute() or ".." in relative.parts:
        raise StaticCotArtifactError(f"unsafe COT history path: {advertised}")
    if len(relative.parts) != 2 or relative.parts[0] != "cot":
        raise StaticCotArtifactError(f"unsafe COT history path: {advertised}")
    root = cot_dir.resolve()
    resolved = (root / relative.parts[1]).resolve()
    if root not in resolved.parents:
        raise StaticCotArtifactError(f"unsafe COT history path: {advertised}")
    return resolved


def _same_publication(
    payload: CotHistoryResponse,
    index: dict[str, Any],
    *,
    slug: str,
) -> None:
    publication = payload.publication
    expected = {
        "schema_version": index["data_schema_version"],
        "calculation_version": index["calculation_version"],
        "publication_id": index["publication_id"],
        "report_date": index["report_date"],
    }
    actual = publication.model_dump(mode="json")
    for key, value in expected.items():
        if actual[key] != value:
            raise StaticCotArtifactError(
                f"publication identity mismatch for {slug}: {key}"
            )


def validate_static_cot_artifact(cot_dir: Path) -> dict[str, Any]:
    """Validate a complete COT directory and return its index."""

    cot_dir = Path(cot_dir)
    index = _load_json(cot_dir / "index.json")
    required = {
        "schema_version",
        "data_schema_version",
        "calculation_version",
        "publication_id",
        "report_date",
        "generated_at",
        "default_slug",
        "catalog",
        "histories",
    }
    if not required.issubset(index):
        raise StaticCotArtifactError("incomplete COT index")
    if index["schema_version"] != STATIC_COT_SCHEMA_VERSION:
        raise StaticCotArtifactError("incompatible static COT schema version")
    try:
        catalog = CotCatalogResponse.model_validate(index["catalog"])
    except ValidationError as exc:
        raise StaticCotArtifactError("invalid COT catalog contract") from exc
    if index["data_schema_version"] != catalog.publication.schema_version:
        raise StaticCotArtifactError("COT data schema version mismatch")
    if index["calculation_version"] != catalog.publication.calculation_version:
        raise StaticCotArtifactError("COT calculation version mismatch")
    if index["publication_id"] != catalog.publication.publication_id:
        raise StaticCotArtifactError("COT publication ID mismatch")
    if index["report_date"] != catalog.publication.report_date.isoformat():
        raise StaticCotArtifactError("COT report date mismatch")
    if index["default_slug"] != catalog.default_slug:
        raise StaticCotArtifactError("COT default instrument mismatch")

    histories = index["histories"]
    if not isinstance(histories, dict):
        raise StaticCotArtifactError("COT histories must be an object")
    slugs = [instrument.slug for instrument in catalog.instruments]
    if set(histories) != set(slugs):
        raise StaticCotArtifactError("COT history coverage does not match catalog")
    paths: set[str] = set()
    for slug in slugs:
        entry = histories[slug]
        if not isinstance(entry, dict) or set(entry) != {"path"}:
            raise StaticCotArtifactError(f"invalid COT history entry: {slug}")
        advertised = entry["path"]
        if advertised in paths:
            raise StaticCotArtifactError("duplicate COT history path")
        paths.add(advertised)
        path = _history_path(cot_dir, advertised)
        if path.stem != slug:
            raise StaticCotArtifactError(f"COT slug/path mismatch: {slug}")
        try:
            history = CotHistoryResponse.model_validate(_load_json(path))
        except ValidationError as exc:
            raise StaticCotArtifactError(
                f"invalid COT history contract: {slug}"
            ) from exc
        if history.slug != slug or history.range != "5y":
            raise StaticCotArtifactError(f"invalid COT history identity: {slug}")
        _same_publication(history, index, slug=slug)
    return index


__all__ = [
    "STATIC_COT_SCHEMA_VERSION",
    "StaticCotArtifactError",
    "validate_static_cot_artifact",
]
