"""Canonical discovery metadata for independently published root artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.services.static_cot_contract import (
    StaticCotArtifactError,
    validate_static_cot_artifact,
)
from app.services.static_options_contract import (
    StaticOptionsArtifactError,
    validate_static_options_artifact,
)

ArtifactValidator = Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class StaticGlobalArtifactSpec:
    key: str
    artifact_name: str
    directory_name: str
    manifest_filename: str
    as_of_field: str
    label: str
    validator: ArtifactValidator
    validation_error: type[Exception]


GLOBAL_STATIC_ARTIFACTS: Mapping[str, StaticGlobalArtifactSpec] = MappingProxyType(
    {
        "options": StaticGlobalArtifactSpec(
            key="options",
            artifact_name="static-options-US",
            directory_name="options",
            manifest_filename="manifest.json",
            as_of_field="source_as_of_date",
            label="static options",
            validator=validate_static_options_artifact,
            validation_error=StaticOptionsArtifactError,
        ),
        "cot": StaticGlobalArtifactSpec(
            key="cot",
            artifact_name="static-cot-global",
            directory_name="cot",
            manifest_filename="index.json",
            as_of_field="report_date",
            label="static COT",
            validator=validate_static_cot_artifact,
            validation_error=StaticCotArtifactError,
        ),
    }
)


def find_global_artifact(
    spec: StaticGlobalArtifactSpec,
    base: Path,
) -> Path | None:
    root = Path(base)
    candidates = [root]
    if root.exists():
        candidates.extend(path.parent for path in root.rglob(spec.manifest_filename))
    for candidate in candidates:
        try:
            spec.validator(candidate)
        except spec.validation_error:
            continue
        return candidate
    return None


def global_artifact_as_of_date(
    spec: StaticGlobalArtifactSpec,
    base: Path,
) -> date | None:
    artifact_dir = find_global_artifact(spec, base)
    if artifact_dir is None:
        return None
    try:
        payload = spec.validator(artifact_dir)
    except spec.validation_error:
        return None
    value = payload.get(spec.as_of_field)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.split("T", 1)[0])
    except ValueError:
        return None


def validate_optional_global_artifact(
    spec: StaticGlobalArtifactSpec,
    current_dir: Path | None,
    fallback_dir: Path | None,
) -> dict[str, Any] | None:
    for source in (current_dir, fallback_dir):
        if source is None:
            continue
        artifact_dir = find_global_artifact(spec, source)
        if artifact_dir is not None:
            return spec.validator(artifact_dir)
    return None


__all__ = [
    "GLOBAL_STATIC_ARTIFACTS",
    "StaticGlobalArtifactSpec",
    "find_global_artifact",
    "global_artifact_as_of_date",
    "validate_optional_global_artifact",
]
