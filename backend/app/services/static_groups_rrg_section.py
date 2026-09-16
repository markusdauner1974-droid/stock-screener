"""Translate static RRG source failures into optional-section failures."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.services.static_groups_rrg_export import (
    StaticGroupsRRGPayloadSource,
    StaticGroupsRRGUnavailableError,
)
from app.services.static_site_errors import StaticSiteSectionUnavailableError


def build_static_groups_rrg_section(
    source: StaticGroupsRRGPayloadSource,
    *,
    db: Any,
    generated_at: str,
    expected_as_of_date: date,
    market: str,
    formula_version: str,
) -> dict[str, Any]:
    """Build RRG data while preserving the static export's optional contract."""
    try:
        return source.build(
            db=db,
            generated_at=generated_at,
            expected_as_of_date=expected_as_of_date,
            market=market,
            formula_version=formula_version,
        )
    except StaticGroupsRRGUnavailableError as exc:
        raise StaticSiteSectionUnavailableError(
            section=exc.section,
            reason=exc.reason,
        ) from exc


__all__ = ["build_static_groups_rrg_section"]
