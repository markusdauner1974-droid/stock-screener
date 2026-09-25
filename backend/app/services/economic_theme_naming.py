"""Deterministic and provider-assisted naming for governed theme candidates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app.services.economic_taxonomy_seed import normalize_facet


@dataclass(frozen=True, slots=True)
class ThemeNamingCandidate:
    raw_facets: dict[str, str | None]
    normalized_facets: dict[str, str]
    mechanism: str | None


@dataclass(frozen=True, slots=True)
class DimensionProposal:
    dimension_key: str
    raw_value: str


@dataclass(frozen=True, slots=True)
class NamingResult:
    display_name: str | None
    normalized_facets: dict[str, str]
    candidate: ThemeNamingCandidate
    failure_code: str | None = None
    proposal: DimensionProposal | None = None


ProviderNamer = Callable[..., str | Mapping[str, Any]]


def _approved_dimensions(snapshot) -> set[str]:
    dimensions = (
        snapshot.get("dimensions", [])
        if isinstance(snapshot, dict)
        else getattr(snapshot, "dimensions", [])
    )
    return {
        str(row.get("key") if isinstance(row, dict) else row.key)
        for row in dimensions
    }


def _display(value: str) -> str:
    labels = {
        "artificial_intelligence": "AI",
        "memory_semiconductors": "Memory",
        "hbm": "HBM",
    }
    return labels.get(value, value.replace("_", " ").title())


def _deterministic_name(facets: Mapping[str, str]) -> str | None:
    is_ai_demand = facets.get("end_market") == "artificial_intelligence"
    is_memory = facets.get("industry") == "memory_semiconductors"
    is_hbm = facets.get("product") == "hbm"
    if is_ai_demand and is_hbm:
        return "AI HBM"
    if is_ai_demand and is_memory:
        return "AI Memory"
    if is_hbm:
        return "HBM"
    if is_memory:
        return "Memory"
    if facets.get("technology") == "artificial_intelligence":
        return "Artificial Intelligence"
    for key in (
        "product",
        "industry",
        "commodity",
        "infrastructure",
        "end_market",
        "technology",
        "supply_chain",
        "customer",
        "geography",
        "policy",
        "regulation",
        "macro",
    ):
        if key in facets:
            return _display(facets[key])
    return None


def _implies_unsupported_specificity(
    display_name: str, facets: Mapping[str, str]
) -> bool:
    lowered = display_name.casefold()
    if ("hbm" in lowered or "high bandwidth memory" in lowered) and facets.get(
        "product"
    ) != "hbm":
        return True
    if "memory" in lowered and not (
        facets.get("industry") == "memory_semiconductors"
        or facets.get("product") == "hbm"
    ):
        return True
    return (
        "ai" in lowered.split() or "artificial intelligence" in lowered
    ) and not (
        facets.get("end_market") == "artificial_intelligence"
        or facets.get("technology") == "artificial_intelligence"
    )


def name_candidate(
    *,
    facets: Mapping[str, str | None],
    snapshot,
    mechanism: str | None = None,
    provider_namer: ProviderNamer | None = None,
) -> NamingResult:
    """Validate facets first, then name without inventing semantic specificity."""

    raw_facets = dict(facets)
    validated_mechanism = mechanism.strip() if mechanism and mechanism.strip() else None
    approved_dimensions = _approved_dimensions(snapshot)
    normalized: dict[str, str] = {}
    for raw_key, raw_value in raw_facets.items():
        if raw_value is None:
            continue
        key = str(raw_key).strip().lower().replace(" ", "_")
        if key not in approved_dimensions:
            candidate = ThemeNamingCandidate(
                raw_facets, normalized, validated_mechanism
            )
            return NamingResult(
                display_name=None,
                normalized_facets=normalized,
                candidate=candidate,
                failure_code="unknown_dimension",
                proposal=DimensionProposal(key, str(raw_value)),
            )
        normalized[key] = normalize_facet(key, str(raw_value))

    candidate = ThemeNamingCandidate(raw_facets, normalized, validated_mechanism)
    if provider_namer is None:
        return NamingResult(
            display_name=_deterministic_name(normalized),
            normalized_facets=normalized,
            candidate=candidate,
        )

    if validated_mechanism is None:
        return NamingResult(
            display_name=None,
            normalized_facets=normalized,
            candidate=candidate,
            failure_code="requires_naming_review",
        )

    provider_result = provider_namer(
        mechanism=validated_mechanism,
        facets=MappingProxyType(dict(normalized)),
    )
    returned_facets = normalized
    if isinstance(provider_result, str):
        display_name = provider_result.strip()
    elif isinstance(provider_result, Mapping):
        display_name = str(provider_result.get("display_name") or "").strip()
        proposed_facets = provider_result.get("facets", normalized)
        if not isinstance(proposed_facets, Mapping):
            display_name = ""
        else:
            returned_facets = dict(proposed_facets)
    else:
        display_name = ""

    if (
        not display_name
        or returned_facets != normalized
        or _implies_unsupported_specificity(display_name, normalized)
    ):
        return NamingResult(
            display_name=None,
            normalized_facets=normalized,
            candidate=candidate,
            failure_code="requires_naming_review",
        )
    return NamingResult(
        display_name=display_name,
        normalized_facets=normalized,
        candidate=candidate,
    )
