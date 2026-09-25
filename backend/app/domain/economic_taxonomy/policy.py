"""Pure policy rules shared by economic-taxonomy services."""

from __future__ import annotations

import re
from collections.abc import Hashable, Iterable, Mapping

from .contracts import (
    AdminPrincipal,
    EvidencePacketDescriptor,
    EvidencePrecedenceDecision,
    InterpretationCandidate,
    ServingGenerationEvent,
    SocialDecisionResult,
    SplitAllocationResult,
)


def decide_evidence_precedence(
    accepted: EvidencePacketDescriptor | None,
    candidate: EvidencePacketDescriptor,
) -> EvidencePrecedenceDecision:
    """Compare packets without treating admission order as source freshness."""

    if accepted is None:
        return EvidencePrecedenceDecision.ADVANCE
    if candidate.packet_id == accepted.packet_id:
        return EvidencePrecedenceDecision.REUSE_EQUIVALENT
    if candidate.equivalent_to_packet_id == accepted.packet_id:
        return EvidencePrecedenceDecision.REUSE_EQUIVALENT
    if (
        candidate.evidence_content_fingerprint
        == accepted.evidence_content_fingerprint
    ):
        return EvidencePrecedenceDecision.REUSE_EQUIVALENT
    if candidate.supersedes_packet_id == accepted.packet_id:
        return EvidencePrecedenceDecision.ADVANCE
    if accepted.supersedes_packet_id == candidate.packet_id:
        return EvidencePrecedenceDecision.IGNORE_SUPERSEDED

    accepted_order = accepted.provider_revision_order
    candidate_order = candidate.provider_revision_order
    if accepted_order is not None and candidate_order is not None:
        if candidate_order > accepted_order:
            return EvidencePrecedenceDecision.ADVANCE
        if candidate_order < accepted_order:
            return EvidencePrecedenceDecision.IGNORE_SUPERSEDED
        return EvidencePrecedenceDecision.HOLD_REVIEW

    # A recapture that silently loses previously admitted evidence is never a
    # correction unless authoritative revision data or an explicit relation
    # above proves it.
    if not accepted.attachment_hashes.issubset(candidate.attachment_hashes):
        return EvidencePrecedenceDecision.HOLD_REVIEW

    return EvidencePrecedenceDecision.HOLD_REVIEW


def choose_interpretation(
    *,
    previous: InterpretationCandidate | None,
    candidates: Iterable[InterpretationCandidate],
    override_attempt_id: str | None = None,
    override_principal: AdminPrincipal | None = None,
) -> InterpretationCandidate | None:
    """Choose one completed, effective attempt; completed-empty is valid."""

    considered = list(candidates)
    if previous is not None:
        considered.append(previous)
    eligible = [
        candidate
        for candidate in considered
        if candidate.status == "completed"
        and candidate.precedence_state in {"effective", "equivalent"}
    ]

    if override_attempt_id is not None:
        if override_principal is None or not override_principal.can_review_taxonomy:
            raise PermissionError("override requires an authenticated taxonomy reviewer")
        for candidate in eligible:
            if candidate.attempt_id == override_attempt_id:
                return candidate
        raise ValueError("override must select an eligible completed attempt")

    if not eligible:
        return previous

    return max(
        eligible,
        key=lambda candidate: (
            candidate.evidence_revision_ordinal,
            candidate.provider_revision_order or -1,
            candidate.attempt_id,
        ),
    )


def projection_is_deliverable(
    generation_event: ServingGenerationEvent | str | Iterable[ServingGenerationEvent | str],
) -> bool:
    """A committed ``published`` event is the durable delivery eligibility."""

    if isinstance(generation_event, (str, ServingGenerationEvent)):
        values = {str(generation_event)}
    else:
        values = {str(event) for event in generation_event}
    return ServingGenerationEvent.PUBLISHED.value in values


def _name_tokens(value: str) -> frozenset[str]:
    return frozenset(token for token in re.split(r"[^a-z0-9]+", value.lower()) if token)


def relationship_from_proposed(proposed: str, existing: str) -> str:
    """Return direction with the proposed candidate as the first endpoint."""

    proposed_tokens = _name_tokens(proposed)
    existing_tokens = _name_tokens(existing)
    if not proposed_tokens or not existing_tokens:
        return "ambiguous"
    if proposed_tokens == existing_tokens:
        return "equivalent"
    if proposed_tokens < existing_tokens:
        return "broader"
    if proposed_tokens > existing_tokens:
        return "narrower"
    return "ambiguous"


def reconcile_social_decisions(decisions: Iterable[str]) -> SocialDecisionResult:
    normalized = tuple(decision.strip().lower() for decision in decisions)
    states = set(normalized)
    if not states or states == {"proposed"}:
        return SocialDecisionResult(state="proposed", live=False)
    if "accepted" in states and "rejected" in states:
        return SocialDecisionResult(state="conflict_review_required", live=False)
    if states == {"accepted"}:
        return SocialDecisionResult(state="accepted", live=True)
    if states == {"rejected"}:
        return SocialDecisionResult(state="rejected", live=False)
    if states <= {"proposed", "accepted"}:
        return SocialDecisionResult(state="proposed", live=False)
    if states <= {"proposed", "rejected"}:
        return SocialDecisionResult(state="rejected", live=False)
    return SocialDecisionResult(state="conflict_review_required", live=False)


def _allocation_count(destination: object) -> int:
    if destination is None:
        return 0
    if isinstance(destination, str):
        return 1 if destination.strip() else 0
    if isinstance(destination, Iterable):
        return len(tuple(destination))
    return 1


def validate_split_allocations(
    *,
    claim_ids: Iterable[Hashable],
    allocations: Mapping[Hashable, object],
    reviewed_exclusions: Iterable[Hashable] = (),
) -> SplitAllocationResult:
    """Require exactly one destination or reviewed exclusion per current claim."""

    claims = frozenset(claim_ids)
    exclusions = frozenset(reviewed_exclusions)
    allocation_ids = frozenset(allocations)
    unexpected = (allocation_ids | exclusions) - claims
    unallocated: set[Hashable] = set()
    multiplied: set[Hashable] = set()

    for claim_id in claims:
        count = _allocation_count(allocations.get(claim_id))
        if claim_id in exclusions:
            count += 1
        if count == 0:
            unallocated.add(claim_id)
        elif count > 1:
            multiplied.add(claim_id)

    return SplitAllocationResult(
        complete=not unallocated and not multiplied and not unexpected,
        unallocated_claim_ids=frozenset(unallocated),
        multiply_allocated_claim_ids=frozenset(multiplied),
        unexpected_claim_ids=frozenset(unexpected),
    )

