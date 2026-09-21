"""Reusable claim review for structured Economic Theme exposures."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select

from app.domain.economic_taxonomy.contracts import ProviderAttemptOutcome
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy_runtime import (
    ClaimReviewArtifact,
    EvidencePacket,
    ExtractionArtifact,
    ProcessingRequest,
)
from app.services.economic_exposure_extraction import (
    BudgetExhausted,
    ProviderCallError,
    ProviderOutcomeUncertain,
    ProviderReservation,
    ProviderTerminalFailure,
    ReservationManager,
    RetryableProviderFailure,
    TerminalProviderError,
    UncertainProviderError,
    canonical_response_hash,
    jsonable,
    provider_metadata,
)
from app.services.economic_taxonomy_seed import normalize_facet


class ClaimReviewSchemaError(ValueError):
    pass


class ClaimReviewProvider(Protocol):
    def review(
        self,
        *,
        extraction: Mapping[str, Any],
        policy_version: str,
        facet_catalog_semantic_hash: str,
    ): ...


class _NoopReservation:
    state = "reserved"

    def mark_dispatched(self) -> None:
        self.state = "dispatched"

    def release_pre_dispatch(self) -> None:
        self.state = "released"

    def reconcile(
        self, *, actual_cost: Decimal | None, provider_request_id: str | None
    ) -> None:
        self.state = "uncertain" if actual_cost is None else "reconciled"


class EconomicExposureClaimReviewer:
    def __init__(
        self,
        session_factory,
        *,
        provider: ClaimReviewProvider,
        claim_review_policy_version: str,
        approved_dimensions: Iterable[str],
        reservations: ReservationManager | None = None,
    ):
        if not claim_review_policy_version.strip():
            raise ValueError("claim_review_policy_version must be non-empty")
        self.session_factory = session_factory
        self.provider = provider
        self.claim_review_policy_version = claim_review_policy_version
        self.approved_dimensions = frozenset(
            str(value) for value in approved_dimensions
        )
        self.reservations = reservations

    def review(
        self,
        extraction: ExtractionArtifact | UUID,
        *,
        policy_version: str | None = None,
        facet_hash: str,
    ) -> ClaimReviewArtifact:
        extraction_id = extraction if isinstance(extraction, UUID) else extraction.id
        policy = policy_version or self.claim_review_policy_version
        if not policy.strip() or not facet_hash.strip():
            raise ValueError("claim review policy and facet hash must be non-empty")

        with self.session_factory() as session:
            persisted = session.get(ExtractionArtifact, extraction_id)
            if persisted is None:
                raise KeyError(f"extraction artifact {extraction_id} not found")
            existing = self._find_existing(session, extraction_id, policy, facet_hash)
            if existing is not None:
                return self._detach(session, existing)
            request = session.execute(
                select(ProcessingRequest)
                .where(
                    ProcessingRequest.evidence_packet_id == persisted.evidence_packet_id
                )
                .order_by(ProcessingRequest.created_at, ProcessingRequest.id)
                .limit(1)
            ).scalar_one_or_none()
            if request is None:
                raise KeyError("processing request for extraction not found")
            packet = session.get(EvidencePacket, persisted.evidence_packet_id)
            if packet is None:
                raise KeyError(
                    f"evidence packet {persisted.evidence_packet_id} not found"
                )
            request_id = request.id
            extraction_payload = dict(persisted.result_payload or {})
            grounded_security_ids = self._grounded_security_ids(
                packet.grounding_snapshot or {}
            )

        deterministic = self._deterministic_review(
            extraction_payload,
            grounded_security_ids=grounded_security_ids,
        )
        if (
            deterministic["all_held"]
            or extraction_payload.get("status") == "successful_empty"
        ):
            payload = self._result_from_deterministic(extraction_payload, deterministic)
            return self._persist_artifact(
                extraction_id=extraction_id,
                policy=policy,
                facet_hash=facet_hash,
                result_payload=payload,
                provider_response_hash=None,
                attempt_id=None,
            )

        dispatch_id = str(uuid4())
        reservation = self._reserve(request_id, dispatch_id)
        with self.session_factory() as session:
            attempt = EconomicTaxonomyWorkRepository(session).begin_provider_attempt(
                request_id,
                operation="claim_review",
                dispatch_id=dispatch_id,
            )
            attempt_id = attempt.id
            session.commit()

        reservation.mark_dispatched()
        try:
            raw_response = self.provider.review(
                extraction=extraction_payload,
                policy_version=policy,
                facet_catalog_semantic_hash=facet_hash,
            )
        except ProviderCallError as exc:
            self._handle_provider_failure(attempt_id, reservation, exc)
        except Exception as exc:
            wrapped = TerminalProviderError(str(exc), dispatch_confirmed=True)
            self._handle_provider_failure(attempt_id, reservation, wrapped)
            raise AssertionError("unreachable") from exc

        if not isinstance(raw_response, Mapping):
            reservation.reconcile(actual_cost=None, provider_request_id=None)
            self._record_terminal_schema_failure(attempt_id)
            raise ClaimReviewSchemaError("review_response_must_be_object")
        provider_request_id, actual_cost = provider_metadata(raw_response)
        reservation.reconcile(
            actual_cost=actual_cost,
            provider_request_id=provider_request_id,
        )
        response_hash = canonical_response_hash(raw_response)
        try:
            payload = self._apply_provider_decisions(
                extraction_payload, deterministic, raw_response
            )
        except ClaimReviewSchemaError:
            self._record_terminal_schema_failure(attempt_id)
            raise
        return self._persist_artifact(
            extraction_id=extraction_id,
            policy=policy,
            facet_hash=facet_hash,
            result_payload=payload,
            provider_response_hash=response_hash,
            attempt_id=attempt_id,
        )

    def _deterministic_review(
        self,
        extraction: Mapping[str, Any],
        *,
        grounded_security_ids: frozenset[int],
    ) -> dict[str, Any]:
        held: dict[str, str] = {}
        candidates = extraction.get("candidates") or []
        for candidate in candidates:
            key = candidate["candidate_key"]
            reason = self._deterministic_hold_reason(
                candidate,
                grounded_security_ids=grounded_security_ids,
            )
            if reason is not None:
                held[key] = reason
        return {
            "held": held,
            "all_held": bool(candidates) and len(held) == len(candidates),
        }

    def _deterministic_hold_reason(
        self,
        candidate: Mapping[str, Any],
        *,
        grounded_security_ids: frozenset[int],
    ) -> str | None:
        display_name = str(candidate.get("display_name") or "").casefold()
        technical_markers = ("vcp", "breakout", "cup with handle", "pocket pivot")
        if candidate.get("candidate_kind") == "technical_setup" or any(
            marker in display_name for marker in technical_markers
        ):
            return "technical_setup_not_theme"
        facets = candidate.get("raw_facets") or {}
        normalized_facets = {
            str(key): normalize_facet(str(key), str(value))
            for key, value in facets.items()
            if key in self.approved_dimensions and value is not None
        }
        if ("hbm" in display_name or "high bandwidth memory" in display_name) and (
            normalized_facets.get("product") != "hbm"
        ):
            return "unsupported_specificity"
        if "memory" in display_name and not (
            normalized_facets.get("industry") == "memory_semiconductors"
            or normalized_facets.get("product") == "hbm"
        ):
            return "unsupported_specificity"
        if ("ai" in display_name.split() or "artificial intelligence" in display_name) and not (
            normalized_facets.get("end_market") == "artificial_intelligence"
            or normalized_facets.get("technology") == "artificial_intelligence"
        ):
            return "unsupported_specificity"
        securities = candidate.get("securities") or []
        if any(
            not isinstance(row, Mapping)
            or not isinstance(row.get("security_id"), int)
            or isinstance(row.get("security_id"), bool)
            or row["security_id"] < 1
            or row["security_id"] not in grounded_security_ids
            for row in securities
        ):
            return "security_grounding_required"
        unknown = set(facets) - self.approved_dimensions
        if unknown:
            return f"unknown_dimension:{min(unknown)}"
        review_reasons = candidate.get("review_reasons") or []
        if review_reasons:
            return str(review_reasons[0])
        return None

    @classmethod
    def _grounded_security_ids(cls, payload: Any) -> frozenset[int]:
        found: set[int] = set()

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                security_id = value.get("security_id")
                if (
                    isinstance(security_id, int)
                    and not isinstance(security_id, bool)
                    and security_id > 0
                ):
                    found.add(security_id)
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, (list, tuple)):
                for nested in value:
                    visit(nested)

        visit(payload)
        return frozenset(found)

    @staticmethod
    def _result_from_deterministic(
        extraction: Mapping[str, Any], deterministic: Mapping[str, Any]
    ) -> dict[str, Any]:
        if extraction.get("status") == "successful_empty":
            return {"status": "successful_empty", "accepted": [], "held": []}
        held = [
            {"candidate_key": key, "reason": reason}
            for key, reason in deterministic["held"].items()
        ]
        return {"status": "review_required", "accepted": [], "held": held}

    @staticmethod
    def _apply_provider_decisions(
        extraction: Mapping[str, Any],
        deterministic: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> dict[str, Any]:
        decisions = response.get("decisions")
        if not isinstance(decisions, list):
            raise ClaimReviewSchemaError("review_decisions_must_be_list")
        candidate_keys = {
            str(candidate["candidate_key"])
            for candidate in extraction.get("candidates") or []
        }
        by_key = {}
        for decision in decisions:
            if not isinstance(decision, Mapping):
                raise ClaimReviewSchemaError("review_decision_must_be_object")
            key = str(decision.get("candidate_key") or "")
            state = str(decision.get("decision") or "")
            if not key or state not in {"accepted", "held", "rejected"}:
                raise ClaimReviewSchemaError("invalid_review_decision")
            if key not in candidate_keys:
                raise ClaimReviewSchemaError("unknown_review_candidate")
            if key in by_key:
                raise ClaimReviewSchemaError("duplicate_review_decision")
            by_key[key] = decision

        accepted = []
        held = []
        for candidate in extraction.get("candidates") or []:
            key = candidate["candidate_key"]
            deterministic_reason = deterministic["held"].get(key)
            decision = by_key.get(key)
            if deterministic_reason is not None:
                held.append({"candidate_key": key, "reason": deterministic_reason})
            elif decision is None:
                held.append({"candidate_key": key, "reason": "review_decision_missing"})
            elif decision["decision"] == "accepted":
                accepted.append(jsonable(candidate))
            else:
                held.append(
                    {
                        "candidate_key": key,
                        "reason": str(
                            decision.get("reason") or f"provider_{decision['decision']}"
                        ),
                    }
                )
        return {
            "status": "review_required" if held else "accepted_candidates",
            "accepted": accepted,
            "held": held,
        }

    def _persist_artifact(
        self,
        *,
        extraction_id: UUID,
        policy: str,
        facet_hash: str,
        result_payload: dict[str, Any],
        provider_response_hash: str | None,
        attempt_id: UUID | None,
    ) -> ClaimReviewArtifact:
        with self.session_factory() as session:
            artifact = self._find_existing(session, extraction_id, policy, facet_hash)
            if artifact is None:
                artifact = ClaimReviewArtifact(
                    extraction_artifact_id=extraction_id,
                    claim_review_policy_version=policy,
                    facet_catalog_semantic_hash=facet_hash,
                    result_status=result_payload["status"],
                    result_payload=jsonable(result_payload),
                    provider_response_hash=provider_response_hash,
                )
                session.add(artifact)
                session.flush()
            if attempt_id is not None:
                EconomicTaxonomyWorkRepository(session).succeed_attempt(
                    attempt_id,
                    result_artifact_id=artifact.id,
                    payload={"provider_response_hash": provider_response_hash},
                )
            session.commit()
            session.refresh(artifact)
            return self._detach(session, artifact)

    @staticmethod
    def _find_existing(session, extraction_id, policy, facet_hash):
        return session.execute(
            select(ClaimReviewArtifact).where(
                ClaimReviewArtifact.extraction_artifact_id == extraction_id,
                ClaimReviewArtifact.claim_review_policy_version == policy,
                ClaimReviewArtifact.facet_catalog_semantic_hash == facet_hash,
            )
        ).scalar_one_or_none()

    def _reserve(self, request_id: UUID, dispatch_id: str) -> ProviderReservation:
        if self.reservations is None:
            return _NoopReservation()
        reservation = self.reservations.reserve(
            attempt_key=dispatch_id,
            logical_request_id=request_id,
            operation_kind="claim_review",
        )
        if reservation is None:
            raise BudgetExhausted("budget_exhausted")
        return reservation

    def _handle_provider_failure(
        self,
        attempt_id: UUID,
        reservation: ProviderReservation,
        error: ProviderCallError,
    ) -> None:
        if not error.dispatch_confirmed:
            reservation.release_pre_dispatch()
            outcome = ProviderAttemptOutcome.RETRYABLE_FAILURE.value
            raised = RetryableProviderFailure(str(error))
        else:
            reservation.reconcile(
                actual_cost=error.actual_cost,
                provider_request_id=error.provider_request_id,
            )
            if isinstance(error, TerminalProviderError):
                outcome = ProviderAttemptOutcome.TERMINAL_FAILURE.value
                raised = ProviderTerminalFailure(str(error))
            elif isinstance(error, UncertainProviderError) or error.actual_cost is None:
                outcome = ProviderAttemptOutcome.UNCERTAIN.value
                raised = ProviderOutcomeUncertain(str(error))
            else:
                outcome = ProviderAttemptOutcome.RETRYABLE_FAILURE.value
                raised = RetryableProviderFailure(str(error))
        with self.session_factory() as session:
            EconomicTaxonomyWorkRepository(session).fail_attempt(
                attempt_id,
                outcome=outcome,
                payload={"provider_request_id": error.provider_request_id},
            )
            session.commit()
        raise raised from error

    def _record_terminal_schema_failure(self, attempt_id: UUID) -> None:
        with self.session_factory() as session:
            EconomicTaxonomyWorkRepository(session).fail_attempt(
                attempt_id,
                outcome=ProviderAttemptOutcome.TERMINAL_FAILURE.value,
                payload={"failure_code": "invalid_schema"},
            )
            session.commit()

    @staticmethod
    def _detach(session, row):
        if row is not None:
            session.expunge(row)
        return row


__all__ = ["ClaimReviewSchemaError", "EconomicExposureClaimReviewer"]
