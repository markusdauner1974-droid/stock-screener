"""Choose and atomically promote the newest valid static COT artifact."""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.services.atomic_directory_publisher import AtomicDirectoryPublisher
from app.services.static_cot_contract import (
    StaticCotArtifactError,
    validate_static_cot_artifact,
)


class StaticCotUnavailable(RuntimeError):
    """Raised when neither current nor fallback contains compatible COT data."""


def _validated(path: Path | None) -> tuple[Path, dict[str, Any]] | None:
    if path is None or not Path(path).is_dir():
        return None
    try:
        return Path(path), validate_static_cot_artifact(Path(path))
    except StaticCotArtifactError:
        return None


def _order_key(candidate: tuple[Path, dict[str, Any]]) -> tuple[date, datetime]:
    index = candidate[1]
    generated = datetime.fromisoformat(index["generated_at"].replace("Z", "+00:00"))
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    return date.fromisoformat(index["report_date"]), generated.astimezone(UTC)


class StaticCotArtifactSelector:
    def __init__(self, *, publisher: AtomicDirectoryPublisher | None = None):
        self._publisher = publisher or AtomicDirectoryPublisher()

    def select(
        self,
        *,
        current_cot_dir: Path | None,
        fallback_cot_dir: Path | None,
        output_cot_dir: Path,
    ) -> dict[str, Any]:
        current = _validated(current_cot_dir)
        fallback = _validated(fallback_cot_dir)
        candidates = [item for item in (fallback, current) if item is not None]
        if not candidates:
            raise StaticCotUnavailable("No compatible static COT artifact is available")
        selected = max(
            candidates,
            key=lambda item: (*_order_key(item), item is current),
        )

        def populate(stage: Path) -> None:
            shutil.copytree(selected[0], stage, dirs_exist_ok=True)

        self._publisher.publish(
            Path(output_cot_dir),
            populate,
            validate=validate_static_cot_artifact,
        )
        return validate_static_cot_artifact(Path(output_cot_dir))


__all__ = ["StaticCotArtifactSelector", "StaticCotUnavailable"]
