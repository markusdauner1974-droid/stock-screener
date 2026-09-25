from __future__ import annotations

from app.services.economic_taxonomy_seed import INITIAL_DIMENSIONS
from app.services.economic_theme_naming import name_candidate


def _snapshot():
    return {
        "dimensions": [{"key": key} for key in INITIAL_DIMENSIONS],
        "facet_values": [
            {
                "dimension_key": "end_market",
                "normalized_value": "artificial_intelligence",
                "display_value": "AI",
            },
            {
                "dimension_key": "industry",
                "normalized_value": "memory_semiconductors",
                "display_value": "Memory",
            },
            {
                "dimension_key": "product",
                "normalized_value": "hbm",
                "display_value": "HBM",
            },
            {
                "dimension_key": "technology",
                "normalized_value": "artificial_intelligence",
                "display_value": "Artificial Intelligence",
            },
        ],
    }


def test_ai_memory_uses_end_market_and_industry():
    result = name_candidate(
        facets={"end_market": "AI", "industry": "Memory", "product": None},
        snapshot=_snapshot(),
    )

    assert result.display_name == "AI Memory"
    assert result.normalized_facets == {
        "end_market": "artificial_intelligence",
        "industry": "memory_semiconductors",
    }
    assert "technology" not in result.normalized_facets


def test_ai_hbm_requires_direct_product_specificity():
    result = name_candidate(
        facets={"end_market": "AI", "industry": "Memory", "product": "HBM"},
        snapshot=_snapshot(),
    )

    assert result.display_name == "AI HBM"
    assert result.normalized_facets["product"] == "hbm"


def test_unknown_dimension_preserves_candidate_and_opens_proposal():
    result = name_candidate(facets={"moon_phase": "waxing"}, snapshot=_snapshot())

    assert result.candidate is not None
    assert result.candidate.raw_facets == {"moon_phase": "waxing"}
    assert result.failure_code == "unknown_dimension"
    assert result.proposal.dimension_key == "moon_phase"
    assert result.proposal.raw_value == "waxing"


def test_provider_receives_only_validated_facets_and_mechanism():
    received = {}

    def provider_namer(*, mechanism, facets):
        received["mechanism"] = mechanism
        received["facets"] = dict(facets)
        return "AI Memory"

    result = name_candidate(
        facets={"end_market": "AI", "industry": "Memory"},
        mechanism="AI demand increases memory intensity",
        snapshot=_snapshot(),
        provider_namer=provider_namer,
    )

    assert result.display_name == "AI Memory"
    assert received == {
        "mechanism": "AI demand increases memory intensity",
        "facets": {
            "end_market": "artificial_intelligence",
            "industry": "memory_semiconductors",
        },
    }


def test_provider_is_not_called_without_a_validated_mechanism():
    called = False

    def provider_namer(**_inputs):
        nonlocal called
        called = True
        return "Memory"

    result = name_candidate(
        facets={"industry": "Memory"},
        mechanism="  ",
        snapshot=_snapshot(),
        provider_namer=provider_namer,
    )

    assert called is False
    assert result.failure_code == "requires_naming_review"


def test_provider_cannot_introduce_unsupported_hbm_specificity():
    result = name_candidate(
        facets={"end_market": "AI", "industry": "Memory"},
        mechanism="AI demand increases memory intensity",
        snapshot=_snapshot(),
        provider_namer=lambda **_inputs: "AI HBM",
    )

    assert result.display_name is None
    assert result.failure_code == "requires_naming_review"
    assert result.candidate is not None


def test_provider_returned_facets_must_equal_validated_input():
    result = name_candidate(
        facets={"industry": "Memory"},
        mechanism="Memory supply and demand",
        snapshot=_snapshot(),
        provider_namer=lambda **_inputs: {
            "display_name": "AI Memory",
            "facets": {
                "industry": "memory_semiconductors",
                "end_market": "artificial_intelligence",
            },
        },
    )

    assert result.failure_code == "requires_naming_review"
    assert result.display_name is None
