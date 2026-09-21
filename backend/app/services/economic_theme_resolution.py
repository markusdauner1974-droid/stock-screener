"""Semantic resolution of a proposed theme relative to retrieved identities."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

ALLOWED_OUTCOMES = frozenset(
    {"equivalent", "specialization", "broader", "related", "distinct", "ambiguous"}
)


class InvalidResolution(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    theme_id: UUID
    display_name: str
    definition: str
    mechanism: str
    normalized_facets: dict[str, str]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    outcome: str
    target_theme_id: UUID | None
    rationale: str | None = None
    provider_payload: dict[str, Any] | None = None


def _tokens(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", value.casefold()))


def _coerce_candidate(value) -> ResolutionCandidate:
    if isinstance(value, ResolutionCandidate):
        return value
    return ResolutionCandidate(
        theme_id=value.theme_id,
        display_name=value.display_name,
        definition=value.definition,
        mechanism=value.mechanism,
        normalized_facets=dict(value.normalized_facets),
        aliases=tuple(getattr(value, "aliases", ())),
    )


def _deterministic_pair(proposed: Mapping, existing: ResolutionCandidate):
    proposed_tokens = _tokens(str(proposed.get("display_name") or ""))
    existing_tokens = _tokens(existing.display_name)
    proposed_facets = dict(proposed.get("normalized_facets") or {})
    facet_conflict = any(
        key in existing.normalized_facets and existing.normalized_facets[key] != value
        for key, value in proposed_facets.items()
    )
    exact_name_or_alias = any(
        proposed_tokens == _tokens(name)
        for name in (existing.display_name, *existing.aliases)
    )
    if proposed_tokens and exact_name_or_alias and not facet_conflict:
        return ResolutionResult("equivalent", existing.theme_id, "exact_semantics")
    if proposed_tokens and proposed_tokens < existing_tokens:
        return ResolutionResult("broader", existing.theme_id, "name_scope")
    if existing_tokens and existing_tokens < proposed_tokens:
        return ResolutionResult("specialization", existing.theme_id, "name_scope")
    return ResolutionResult("distinct", None, "no_supported_relationship")


def resolve_candidate(
    *,
    proposed: Mapping,
    existing: ResolutionCandidate | None = None,
    candidates: Sequence[ResolutionCandidate] | None = None,
    provider: Callable[..., Mapping[str, Any]] | Any | None = None,
    policy_version: str = "resolver-v1",
) -> ResolutionResult:
    available = [
        _coerce_candidate(row)
        for row in (
            candidates if candidates is not None else ([existing] if existing else [])
        )
    ]
    if provider is None:
        results = [_deterministic_pair(proposed, row) for row in available]
        for outcome in ("equivalent", "specialization", "broader"):
            match = next((row for row in results if row.outcome == outcome), None)
            if match is not None:
                return match
        return ResolutionResult("distinct", None, "no_supported_relationship")

    callable_provider = provider.resolve if hasattr(provider, "resolve") else provider
    raw = callable_provider(
        proposed=dict(proposed),
        candidates=[
            {
                "theme_id": str(row.theme_id),
                "display_name": row.display_name,
                "definition": row.definition,
                "mechanism": row.mechanism,
                "normalized_facets": dict(row.normalized_facets),
                "aliases": list(row.aliases),
            }
            for row in available
        ],
        policy_version=policy_version,
    )
    if not isinstance(raw, Mapping):
        raise InvalidResolution("resolver_response_must_be_object")
    outcome = str(raw.get("outcome") or "")
    if outcome not in ALLOWED_OUTCOMES:
        raise InvalidResolution("invalid_resolver_outcome")
    raw_target = raw.get("target_theme_id")
    try:
        target = UUID(str(raw_target)) if raw_target else None
    except (TypeError, ValueError) as exc:
        raise InvalidResolution("invalid_resolver_target") from exc
    allowed_ids = {row.theme_id for row in available}
    if target is not None and target not in allowed_ids:
        raise InvalidResolution("target_not_retrieved")
    if (
        outcome in {"equivalent", "specialization", "broader", "related"}
        and target is None
    ):
        raise InvalidResolution("resolver_target_required")
    return ResolutionResult(
        outcome=outcome,
        target_theme_id=target,
        rationale=str(raw.get("rationale") or "") or None,
        provider_payload=dict(raw),
    )


class EconomicThemeResolver:
    def __init__(self, provider=None, *, policy_version: str = "resolver-v1"):
        self.provider = provider
        self.policy_version = policy_version

    def resolve(self, *, proposed, existing=None, candidates=None) -> ResolutionResult:
        return resolve_candidate(
            proposed=proposed,
            existing=existing,
            candidates=candidates,
            provider=self.provider,
            policy_version=self.policy_version,
        )


__all__ = [
    "ALLOWED_OUTCOMES",
    "EconomicThemeResolver",
    "InvalidResolution",
    "ResolutionCandidate",
    "ResolutionResult",
    "resolve_candidate",
]
