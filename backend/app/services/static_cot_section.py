"""Root-global COT composition for direct and combined static exports."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.static_cot_artifact_selector import (
    StaticCotArtifactSelector,
    StaticCotUnavailable,
)
from app.services.static_cot_contract import StaticCotArtifactError
from app.services.static_cot_exporter import StaticCotExporter
from app.use_cases.cot.queries import CotPublicationUnavailable

CotExporterFactory = Callable[[Session], StaticCotExporter]


@dataclass(frozen=True)
class StaticCotSectionResult:
    selected: bool
    warnings: tuple[str, ...] = ()


def _default_exporter_factory(db: Session) -> StaticCotExporter:
    from app.wiring.bootstrap import get_cot_queries

    return StaticCotExporter(get_cot_queries(db))


class StaticCotSection:
    def __init__(
        self,
        *,
        enabled: bool = True,
        exporter_factory: CotExporterFactory | None = None,
        selector: StaticCotArtifactSelector | None = None,
    ) -> None:
        self._enabled = enabled
        self._exporter_factory = exporter_factory or _default_exporter_factory
        self._selector = selector or StaticCotArtifactSelector()

    def compose_live(
        self,
        *,
        db: Session,
        output_dir: Path,
        generated_at: str,
        fallback_cot_dir: Path | None,
        global_assets: dict[str, Any],
    ) -> StaticCotSectionResult:
        if not self._enabled:
            return StaticCotSectionResult(False)
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        candidate_root = Path(tempfile.mkdtemp(prefix=".cot-current-", dir=root))
        current: Path | None = None
        warnings: list[str] = []
        try:
            try:
                current = candidate_root / "cot"
                self._exporter_factory(db).export(current, generated_at=generated_at)
            except (CotPublicationUnavailable, SQLAlchemyError):
                current = None
            except (RuntimeError, StaticCotArtifactError, ValueError) as exc:
                current = None
                warnings.append(f"Current COT artifact unavailable: {exc}")
            try:
                self._selector.select(
                    current_cot_dir=current,
                    fallback_cot_dir=fallback_cot_dir,
                    output_cot_dir=root / "cot",
                )
            except StaticCotUnavailable:
                global_assets.pop("cot", None)
                if current is not None or fallback_cot_dir is not None:
                    warnings.append("Static COT data is unavailable")
                return StaticCotSectionResult(False, tuple(warnings))
        finally:
            if candidate_root.exists():
                shutil.rmtree(candidate_root)
        global_assets["cot"] = {"path": "cot/index.json"}
        return StaticCotSectionResult(True, tuple(warnings))

    def compose_combined(
        self,
        *,
        output_dir: Path,
        current_cot_dir: Path | None,
        fallback_cot_dir: Path | None,
        global_assets: dict[str, Any],
    ) -> StaticCotSectionResult:
        if not self._enabled:
            global_assets.pop("cot", None)
            return StaticCotSectionResult(False)
        try:
            self._selector.select(
                current_cot_dir=current_cot_dir,
                fallback_cot_dir=fallback_cot_dir,
                output_cot_dir=Path(output_dir) / "cot",
            )
        except StaticCotUnavailable:
            global_assets.pop("cot", None)
            return StaticCotSectionResult(False)
        global_assets["cot"] = {"path": "cot/index.json"}
        return StaticCotSectionResult(True)


__all__ = ["StaticCotSection", "StaticCotSectionResult"]
