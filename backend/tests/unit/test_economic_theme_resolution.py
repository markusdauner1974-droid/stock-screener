from __future__ import annotations

from uuid import uuid4

import pytest
from app.services.economic_theme_resolution import (
    InvalidResolution,
    ResolutionCandidate,
    resolve_candidate,
)


def _existing(name: str) -> ResolutionCandidate:
    return ResolutionCandidate(
        theme_id=uuid4(),
        display_name=name,
        definition=f"{name} exposure.",
        mechanism=f"{name} economics.",
        normalized_facets={},
    )


def test_proposed_copper_is_broader_than_existing_copper_miners():
    result = resolve_candidate(
        proposed={"display_name": "Copper", "normalized_facets": {}},
        existing=_existing("Copper Miners"),
    )

    assert result.outcome == "broader"


def test_proposed_copper_miners_is_specialization_of_existing_copper():
    result = resolve_candidate(
        proposed={"display_name": "Copper Miners", "normalized_facets": {}},
        existing=_existing("Copper"),
    )

    assert result.outcome == "specialization"


def test_provider_must_reference_a_retrieved_candidate():
    existing = _existing("Memory")

    def provider(**_kwargs):
        return {"outcome": "equivalent", "target_theme_id": str(uuid4())}

    with pytest.raises(InvalidResolution, match="target_not_retrieved"):
        resolve_candidate(
            proposed={"display_name": "DRAM", "normalized_facets": {}},
            candidates=[existing],
            provider=provider,
        )


def test_similarity_alone_does_not_authorize_equivalence():
    result = resolve_candidate(
        proposed={"display_name": "AI Memory", "normalized_facets": {}},
        existing=_existing("Memory"),
    )

    assert result.outcome == "specialization"


def test_exact_alias_with_compatible_new_facet_reuses_identity():
    existing = ResolutionCandidate(
        theme_id=uuid4(),
        display_name="Memory",
        definition="Memory exposure.",
        mechanism="Memory economics.",
        normalized_facets={"industry": "memory_semiconductors"},
        aliases=("DRAM",),
    )

    result = resolve_candidate(
        proposed={
            "display_name": "DRAM",
            "normalized_facets": {
                "industry": "memory_semiconductors",
                "end_market": "artificial_intelligence",
            },
        },
        existing=existing,
    )

    assert result.outcome == "equivalent"
    assert result.target_theme_id == existing.theme_id
