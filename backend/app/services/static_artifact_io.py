"""Shared, strict filesystem helpers for static JSON artifacts."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.infra.serialization import json_safe


def require_finite_json(
    value: Any,
    *,
    location: str,
    error: Callable[[str], Exception],
) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise error(f"non-finite number at {location}")
    if isinstance(value, dict):
        for key, item in value.items():
            require_finite_json(
                item,
                location=f"{location}.{key}",
                error=error,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            require_finite_json(
                item,
                location=f"{location}[{index}]",
                error=error,
            )


def load_finite_json(
    path: Path,
    *,
    label: str,
    error: Callable[[str], Exception],
) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise error(f"invalid {label} artifact file: {path}") from exc
    if not isinstance(payload, dict):
        raise error(f"{label} artifact must be an object: {path}")
    require_finite_json(payload, location=Path(path).as_posix(), error=error)
    return payload


def safe_artifact_path(
    root: Path,
    advertised: str,
    *,
    prefix: str,
    label: str,
    error: Callable[[str], Exception],
    exact_depth: int | None = None,
) -> Path:
    relative = Path(str(advertised))
    unsafe = (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.parts[0] != prefix
        or (exact_depth is not None and len(relative.parts) != exact_depth)
    )
    if unsafe:
        raise error(f"unsafe {label} path: {advertised}")
    resolved_root = Path(root).resolve()
    resolved = (resolved_root / Path(*relative.parts[1:])).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise error(f"unsafe {label} path: {advertised}")
    return resolved


def write_static_json(path: Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(json_safe(payload), allow_nan=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "load_finite_json",
    "require_finite_json",
    "safe_artifact_path",
    "write_static_json",
]
