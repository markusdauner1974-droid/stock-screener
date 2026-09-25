"""Bounded candidate generation for semantic theme resolution."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.economic_taxonomy import (
    EconomicThemeAlias,
    EconomicThemeFacet,
    EconomicThemeRelationship,
    EconomicThemeRevision,
)
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    ThemeConstituentExposure,
)


@dataclass(frozen=True, slots=True)
class RetrievedThemeCandidate:
    theme_id: UUID
    display_name: str
    definition: str
    mechanism: str
    lifecycle: str
    normalized_facets: dict[str, str]
    aliases: tuple[str, ...]
    score: float
    retrieval_reasons: tuple[str, ...]


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def retrieve_candidates(
    session: Session,
    *,
    taxonomy_version_id: UUID,
    proposed: Mapping,
    limit: int = 20,
) -> list[RetrievedThemeCandidate]:
    """Retrieve candidates without making an identity decision."""

    bounded_limit = max(1, min(int(limit), 20))
    revisions = session.scalars(
        select(EconomicThemeRevision).where(
            EconomicThemeRevision.taxonomy_version_id == taxonomy_version_id
        )
    ).all()
    aliases: dict[UUID, list[str]] = defaultdict(list)
    for row in session.scalars(
        select(EconomicThemeAlias).where(
            EconomicThemeAlias.taxonomy_version_id == taxonomy_version_id
        )
    ):
        aliases[row.theme_id].append(row.alias)
    facets: dict[UUID, dict[str, str]] = defaultdict(dict)
    for row in session.scalars(
        select(EconomicThemeFacet).where(
            EconomicThemeFacet.taxonomy_version_id == taxonomy_version_id
        )
    ):
        facets[row.theme_id][row.dimension_key] = row.normalized_value

    proposed_tokens = _tokens(str(proposed.get("display_name") or ""))
    proposed_facets = {
        str(key): str(value)
        for key, value in (proposed.get("normalized_facets") or {}).items()
    }
    proposed_security_ids = {
        row.get("security_id")
        for row in proposed.get("securities") or []
        if isinstance(row, Mapping) and isinstance(row.get("security_id"), int)
    }
    constituent_theme_ids: set[UUID] = set()
    if proposed_security_ids:
        constituent_theme_ids.update(
            session.scalars(
                select(ClaimAssignment.economic_theme_id)
                .join(
                    ThemeConstituentExposure,
                    ThemeConstituentExposure.claim_assignment_id == ClaimAssignment.id,
                )
                .where(ThemeConstituentExposure.security_id.in_(proposed_security_ids))
            ).all()
        )

    scored: dict[UUID, tuple[float, set[str]]] = {}
    revision_by_id = {row.theme_id: row for row in revisions}
    for revision in revisions:
        reasons: set[str] = set()
        score = 0.0
        names = [revision.display_name, *aliases[revision.theme_id]]
        for index, name in enumerate(names):
            name_tokens = _tokens(name)
            overlap = len(proposed_tokens & name_tokens)
            if overlap:
                score += overlap / max(len(proposed_tokens | name_tokens), 1)
                reasons.add("name" if index == 0 else "alias")
            if proposed_tokens and proposed_tokens == name_tokens:
                score += 4.0
        facet_matches = sum(
            facets[revision.theme_id].get(key) == value
            for key, value in proposed_facets.items()
        )
        if facet_matches:
            score += 2.0 * facet_matches
            reasons.add("facet")
        if revision.theme_id in constituent_theme_ids:
            score += 1.5
            reasons.add("constituent")
        if reasons:
            scored[revision.theme_id] = (score, reasons)

    direct_ids = set(scored)
    if direct_ids:
        for relationship in session.scalars(
            select(EconomicThemeRelationship).where(
                EconomicThemeRelationship.taxonomy_version_id == taxonomy_version_id
            )
        ):
            if relationship.source_theme_id in direct_ids:
                neighbor = relationship.target_theme_id
            elif relationship.target_theme_id in direct_ids:
                neighbor = relationship.source_theme_id
            else:
                continue
            if neighbor in revision_by_id:
                old_score, old_reasons = scored.get(neighbor, (0.0, set()))
                scored[neighbor] = (max(old_score, 0.25), old_reasons | {"graph"})

    ordered = sorted(
        scored.items(),
        key=lambda item: (
            -item[1][0],
            revision_by_id[item[0]].display_name.casefold(),
            str(item[0]),
        ),
    )[:bounded_limit]
    return [
        RetrievedThemeCandidate(
            theme_id=theme_id,
            display_name=revision_by_id[theme_id].display_name,
            definition=revision_by_id[theme_id].definition,
            mechanism=revision_by_id[theme_id].mechanism,
            lifecycle=revision_by_id[theme_id].lifecycle,
            normalized_facets=dict(facets[theme_id]),
            aliases=tuple(sorted(aliases[theme_id], key=str.casefold)),
            score=score,
            retrieval_reasons=tuple(sorted(reasons)),
        )
        for theme_id, (score, reasons) in ordered
    ]
