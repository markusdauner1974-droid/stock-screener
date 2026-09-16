"""Validation contract for the root-global static COT bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.domain.cot.models import STATIC_COT_SCHEMA_VERSION
from app.schemas.cot import CotCatalogResponse, CotHistoryResponse
from app.services.static_artifact_io import load_finite_json, safe_artifact_path


class StaticCotArtifactError(ValueError):
    """Raised when a static COT bundle is unsafe or internally inconsistent."""


def _load_json(path: Path) -> dict[str, Any]:
    return load_finite_json(
        path,
        label="COT",
        error=StaticCotArtifactError,
    )


def _history_path(cot_dir: Path, advertised: str) -> Path:
    return safe_artifact_path(
        cot_dir,
        advertised,
        prefix="cot",
        label="COT history",
        error=StaticCotArtifactError,
        exact_depth=2,
    )


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
