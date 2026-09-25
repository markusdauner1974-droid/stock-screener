"""Resolve reviewed claims and atomically advance the processing taxonomy."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
    WorkLeaseError,
)
from app.models.economic_taxonomy import (
    EconomicThemeAlias,
    EconomicThemeFacet,
    FacetValue,
    TaxonomyVersion,
)
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    ClaimReviewArtifact,
    ClassificationAttempt,
    ClassificationAttemptEvent,
    ExtractionArtifact,
    ProcessingRequest,
    TaxonomyAuthority,
)
from app.services.economic_social_taxonomy_adapter import (
    EconomicSocialTaxonomyAdapter,
)
from app.services.economic_taxonomy_fence import producer_write
from app.services.economic_theme_candidate_retrieval import (
    RetrievedThemeCandidate,
    retrieve_candidates,
)
from app.services.economic_theme_naming import name_candidate
from app.services.economic_theme_resolution import (
    EconomicThemeResolver,
    ResolutionCandidate,
)

SYSTEM_ACTOR = "system:economic-taxonomy-refresh"


class ProviderResultUnavailable(RuntimeError):
    """No reusable, accepted Task 6 artifact exists for this request."""


class ResolutionReviewRequired(RuntimeError):
    """Semantic resolution cannot be accepted automatically."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    classification_attempt_id: UUID
    input_taxonomy_version_id: UUID
    output_taxonomy_version_id: UUID | None
    assignment_ids: tuple[UUID, ...]
    created_identity_count: int
    classification_attempt_count: int
    reused: bool = False


@dataclass(frozen=True, slots=True)
class _PreparedCandidate:
    candidate_key: str
    display_name: str
    definition: str
    mechanism: str
    normalized_facets: dict[str, str]
    raw_facets: dict[str, Any]
    raw_payload: dict[str, Any]
    outcome: str
    target_theme_id: UUID | None
    identity_key: str
    alias_to_add: bool
    alias_value: str | None
    facets_to_add: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _PreparedPlan:
    request_id: UUID
    lease_token: UUID
    authority_epoch: int
    processing_head_revision: int
    input_taxonomy_version_id: UUID
    claim_review_artifact_id: UUID
    successful_empty: bool
    candidates: tuple[_PreparedCandidate, ...]

    @property
    def semantic_delta(self) -> bool:
        return any(
            candidate.outcome != "equivalent"
            or candidate.alias_to_add
            or candidate.facets_to_add
            for candidate in self.candidates
        )


@dataclass(frozen=True, slots=True)
class _StalePlan:
    pass


class EconomicTaxonomyProcessor:
    def __init__(
        self,
        session_factory,
        *,
        resolver_policy_version: str,
        naming_policy_version: str,
        derivation_policy_version: str,
        lifecycle_policy_version: str,
        resolver=None,
        fault_injector=None,
    ):
        versions = (
            resolver_policy_version,
            naming_policy_version,
            derivation_policy_version,
            lifecycle_policy_version,
        )
        if any(not value or not value.strip() for value in versions):
            raise ValueError("processor policy versions must be non-empty")
        self.session_factory = session_factory
        self.resolver_policy_version = resolver_policy_version
        self.naming_policy_version = naming_policy_version
        self.derivation_policy_version = derivation_policy_version
        self.lifecycle_policy_version = lifecycle_policy_version
        self.resolver = resolver or EconomicThemeResolver(
            policy_version=resolver_policy_version
        )
        self.fault_injector = fault_injector

    def process(self, request_id: UUID, lease_token: UUID) -> ProcessResult:
        for _stale_retry in range(5):
            reused = self._completed_result(request_id)
            if reused is not None:
                return reused
            plan = self._prepare(request_id, lease_token)
            if self.fault_injector is not None:
                self.fault_injector.after("resolution_complete")
            committed = self._commit(plan)
            if isinstance(committed, _StalePlan):
                continue
            if self.fault_injector is not None:
                self.fault_injector.after("processing_head_commit")
            return committed
        raise RuntimeError("processing_head_changed_repeatedly")

    def processing_head(self) -> tuple[int, UUID | None]:
        with self.session_factory() as session:
            authority = session.get(TaxonomyAuthority, 1)
            if authority is None:
                raise RuntimeError("taxonomy_authority_missing")
            return (
                authority.processing_head_revision,
                authority.processing_taxonomy_version_id,
            )

    def _prepare(self, request_id: UUID, lease_token: UUID) -> _PreparedPlan:
        with self.session_factory() as session:
            request = session.get(ProcessingRequest, request_id)
            if request is None:
                raise KeyError(f"processing request {request_id} not found")
            if request.status != "leased" or request.lease_token != lease_token:
                raise WorkLeaseError("lease token does not own request")
            authority = session.get(TaxonomyAuthority, 1)
            if authority is None or authority.processing_taxonomy_version_id is None:
                raise RuntimeError("processing_taxonomy_head_missing")
            input_version_id = self._input_version_for_request(
                session, request=request, authority=authority
            )
            taxonomy_repo = EconomicTaxonomyRepository(session)
            facet_hash = taxonomy_repo.facet_catalog_semantic_hash(input_version_id)
            review = self._selected_review(
                session, request, facet_catalog_semantic_hash=facet_hash
            )
            payload = dict(review.result_payload or {})
            if review.result_status not in {
                "accepted_candidates",
                "successful_empty",
            }:
                raise ProviderResultUnavailable("claim_review_not_accepted")
            if review.result_status == "successful_empty":
                accepted: list[Mapping[str, Any]] = []
            else:
                raw_accepted = payload.get("accepted")
                if not isinstance(raw_accepted, list) or not raw_accepted:
                    raise ProviderResultUnavailable("accepted_claims_missing")
                if any(not isinstance(row, Mapping) for row in raw_accepted):
                    raise ProviderResultUnavailable("accepted_claim_invalid")
                accepted = raw_accepted

            snapshot = taxonomy_repo.load_snapshot(input_version_id)
            prepared: list[_PreparedCandidate] = []
            for raw_candidate in accepted:
                prepared.append(
                    self._prepare_candidate(
                        session,
                        taxonomy_version_id=input_version_id,
                        snapshot=snapshot,
                        candidate=raw_candidate,
                    )
                )
            return _PreparedPlan(
                request_id=request.id,
                lease_token=lease_token,
                authority_epoch=int(request.observed_authority_epoch or 0),
                processing_head_revision=request.observed_processing_head_revision,
                input_taxonomy_version_id=input_version_id,
                claim_review_artifact_id=review.id,
                successful_empty=review.result_status == "successful_empty",
                candidates=tuple(prepared),
            )

    def _prepare_candidate(
        self,
        session,
        *,
        taxonomy_version_id: UUID,
        snapshot: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> _PreparedCandidate:
        raw_facets = dict(candidate.get("raw_facets") or {})
        named = name_candidate(
            facets=raw_facets,
            snapshot=snapshot,
            mechanism=str(candidate.get("mechanism") or "") or None,
        )
        if named.failure_code or not named.display_name:
            raise ResolutionReviewRequired(named.failure_code or "naming_failed")
        proposed = {
            **dict(candidate),
            "display_name": named.display_name,
            "normalized_facets": dict(named.normalized_facets),
        }
        retrieved = retrieve_candidates(
            session,
            taxonomy_version_id=taxonomy_version_id,
            proposed=proposed,
        )
        resolution_candidates = [self._resolution_candidate(row) for row in retrieved]
        result = self.resolver.resolve(
            proposed=proposed,
            candidates=resolution_candidates,
        )
        if result.outcome == "ambiguous":
            raise ResolutionReviewRequired("ambiguous_identity")
        target = next(
            (row for row in retrieved if row.theme_id == result.target_theme_id), None
        )
        if result.outcome == "equivalent" and target is None:
            raise ResolutionReviewRequired("equivalent_target_missing")
        observed_name = str(candidate.get("display_name") or "").strip()
        alias_to_add = bool(
            target is not None
            and observed_name
            and observed_name.casefold() != target.display_name.casefold()
            and observed_name.casefold()
            not in {alias.casefold() for alias in target.aliases}
        )
        facets_to_add = tuple(
            sorted(
                (key, value)
                for key, value in named.normalized_facets.items()
                if target is None or target.normalized_facets.get(key) != value
            )
        )
        identity_payload = {
            "display_name": named.display_name.casefold(),
            "facets": facets_to_add if target is None else (),
        }
        identity_key = sha256(
            json.dumps(identity_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        mechanism = str(candidate.get("mechanism") or "").strip()
        return _PreparedCandidate(
            candidate_key=str(candidate.get("candidate_key") or identity_key),
            display_name=named.display_name,
            definition=f"Economic exposure to {named.display_name}.",
            mechanism=mechanism or f"{named.display_name} economic mechanism.",
            normalized_facets=dict(named.normalized_facets),
            raw_facets=raw_facets,
            raw_payload=dict(candidate),
            outcome=result.outcome,
            target_theme_id=result.target_theme_id,
            identity_key=identity_key,
            alias_to_add=alias_to_add,
            alias_value=observed_name if alias_to_add else None,
            facets_to_add=facets_to_add,
        )

    def _commit(self, plan: _PreparedPlan) -> ProcessResult | _StalePlan:
        with (
            self.session_factory() as session,
            producer_write(
                session,
                expected_epoch=plan.authority_epoch,
                allowed_modes={"shadow", "dual", "economic"},
            ) as authority,
        ):
            request = session.execute(
                select(ProcessingRequest)
                .where(ProcessingRequest.id == plan.request_id)
                .with_for_update()
            ).scalar_one()
            if request.status == "completed":
                session.rollback()
                reused = self._completed_result(plan.request_id)
                if reused is None:
                    raise RuntimeError("completed_request_missing_attempt")
                return reused
            if request.status != "leased" or request.lease_token != plan.lease_token:
                raise WorkLeaseError("lease token does not own request")
            existing = self._find_attempt(
                session,
                request_id=plan.request_id,
                review_id=plan.claim_review_artifact_id,
                input_version_id=plan.input_taxonomy_version_id,
            )
            if (
                authority.processing_head_revision != plan.processing_head_revision
                or authority.processing_taxonomy_version_id
                != plan.input_taxonomy_version_id
            ):
                if existing is None:
                    existing = self._persist_attempt(
                        session,
                        plan,
                        result_status="superseded_before_acceptance",
                        output_version_id=None,
                        result_payload=self._plan_payload(plan),
                        event_types=("started", "superseded_before_acceptance"),
                    )
                request.observed_processing_head_revision = (
                    authority.processing_head_revision
                )
                EconomicTaxonomyWorkRepository(session)._append_request_event(
                    request.id,
                    "superseded_before_acceptance",
                    {
                        "classification_attempt_id": str(existing.id),
                        "old_taxonomy_version_id": str(plan.input_taxonomy_version_id),
                        "new_taxonomy_version_id": str(
                            authority.processing_taxonomy_version_id
                        ),
                    },
                )
                session.commit()
                return _StalePlan()
            if existing is not None:
                session.rollback()
                reused = self._result_from_attempt(
                    session_factory=self.session_factory,
                    attempt_id=existing.id,
                    reused=True,
                )
                return reused

            theme_ids: dict[str, UUID] = {}
            output_version_id = None
            created_count = 0
            if plan.semantic_delta:
                output_version_id, theme_ids, created_count = (
                    self._apply_semantic_patch(session, plan)
                )
                authority.processing_taxonomy_version_id = output_version_id
                authority.processing_head_revision += 1
            for candidate in plan.candidates:
                if candidate.outcome == "equivalent":
                    if candidate.target_theme_id is None:
                        raise RuntimeError("equivalent target missing")
                    theme_ids[candidate.identity_key] = candidate.target_theme_id

            result_payload = self._plan_payload(
                plan,
                resolved_theme_ids=theme_ids,
            )
            attempt = self._persist_attempt(
                session,
                plan,
                result_status="completed",
                output_version_id=output_version_id,
                result_payload=result_payload,
                event_types=("started", "completed"),
            )
            assignments = self._persist_assignments(
                session, plan, attempt.id, theme_ids
            )
            if authority.mode == "economic":
                EconomicSocialTaxonomyAdapter(session).project_native_assignments(
                    assignments,
                    evidence_packet_id=request.evidence_packet_id,
                    authority_epoch=authority.authority_epoch,
                )
            EconomicTaxonomyPublicationRepository(session).append_source_revision(
                producer_kind="economic_taxonomy",
                logical_source_key=f"processing_request:{plan.request_id}",
                revision_kind="classification_attempt",
                revision_number=1,
                content_hash=self._hash(result_payload),
                authority_epoch=authority.authority_epoch,
            )
            request.status = "completed"
            request.completion_code = "completed"
            request.result_payload = {
                "classification_attempt_id": str(attempt.id),
                "output_taxonomy_version_id": (
                    str(output_version_id) if output_version_id else None
                ),
            }
            request.lease_token = None
            request.lease_owner = None
            request.lease_expires_at = None
            EconomicTaxonomyWorkRepository(session)._append_request_event(
                request.id,
                "completed",
                {
                    "classification_attempt_id": str(attempt.id),
                    "processing_head_revision": authority.processing_head_revision,
                },
            )
            session.commit()
            count = session.scalar(
                select(func.count())
                .select_from(ClassificationAttempt)
                .where(ClassificationAttempt.processing_request_id == plan.request_id)
            )
            return ProcessResult(
                classification_attempt_id=attempt.id,
                input_taxonomy_version_id=plan.input_taxonomy_version_id,
                output_taxonomy_version_id=output_version_id,
                assignment_ids=tuple(row.id for row in assignments),
                created_identity_count=created_count,
                classification_attempt_count=int(count or 0),
            )

    def _apply_semantic_patch(
        self, session, plan: _PreparedPlan
    ) -> tuple[UUID, dict[str, UUID], int]:
        repo = EconomicTaxonomyRepository(session)
        draft = repo.clone_draft(
            plan.input_taxonomy_version_id,
            actor=SYSTEM_ACTOR,
            reason=f"classification request {plan.request_id}",
        )
        theme_ids: dict[str, UUID] = {}
        created = 0
        for candidate in plan.candidates:
            if candidate.outcome == "equivalent":
                theme_id = candidate.target_theme_id
                if theme_id is None:
                    raise RuntimeError("equivalent target missing")
                theme_ids[candidate.identity_key] = theme_id
                if candidate.alias_to_add and not self._alias_exists(
                    session, draft.id, theme_id, candidate.alias_value
                ):
                    repo.add_alias(
                        draft.id,
                        theme_id,
                        candidate.alias_value,
                        actor=SYSTEM_ACTOR,
                    )
                self._apply_facets(session, repo, draft.id, theme_id, candidate)
                continue
            theme_id = theme_ids.get(candidate.identity_key)
            if theme_id is None:
                theme = repo.create_theme(
                    draft.id,
                    display_name=candidate.display_name,
                    definition=candidate.definition,
                    mechanism=candidate.mechanism,
                    lifecycle="provisional",
                    lifecycle_policy_version=self.lifecycle_policy_version,
                    actor=SYSTEM_ACTOR,
                )
                theme_id = theme.id
                theme_ids[candidate.identity_key] = theme_id
                created += 1
                self._apply_facets(session, repo, draft.id, theme_id, candidate)

        for candidate in plan.candidates:
            if candidate.outcome in {"equivalent", "distinct"}:
                continue
            new_theme_id = theme_ids[candidate.identity_key]
            target = candidate.target_theme_id
            if target is None:
                raise RuntimeError("semantic relationship target missing")
            if candidate.outcome == "specialization":
                repo.add_specialization(
                    draft.id,
                    narrower=new_theme_id,
                    broader=target,
                    actor=SYSTEM_ACTOR,
                )
            elif candidate.outcome == "broader":
                repo.add_specialization(
                    draft.id,
                    narrower=target,
                    broader=new_theme_id,
                    actor=SYSTEM_ACTOR,
                )
            elif candidate.outcome == "related":
                repo.add_relationship(
                    draft.id,
                    source_theme_id=new_theme_id,
                    target_theme_id=target,
                    kind="distinct",
                    direction="symmetric",
                    discriminator="related",
                    actor=SYSTEM_ACTOR,
                )
        sealed = repo.seal_draft(draft.id)
        return sealed.id, theme_ids, created

    @staticmethod
    def _apply_facets(session, repo, version_id, theme_id, candidate):
        for dimension, normalized_value in candidate.facets_to_add:
            if (
                session.get(FacetValue, (version_id, dimension, normalized_value))
                is None
            ):
                raw_value = candidate.raw_facets.get(dimension, normalized_value)
                repo.add_facet_value(
                    version_id,
                    dimension,
                    normalized_value,
                    str(raw_value),
                    actor=SYSTEM_ACTOR,
                )
            if (
                session.get(
                    EconomicThemeFacet,
                    (version_id, theme_id, dimension, normalized_value),
                )
                is None
            ):
                repo.assign_facet(
                    version_id,
                    theme_id,
                    dimension,
                    normalized_value,
                    actor=SYSTEM_ACTOR,
                )

    @staticmethod
    def _alias_exists(session, version_id, theme_id, alias):
        if not alias:
            return False
        normalized = " ".join(alias.strip().casefold().split())
        return (
            session.scalar(
                select(func.count())
                .select_from(EconomicThemeAlias)
                .where(
                    EconomicThemeAlias.taxonomy_version_id == version_id,
                    EconomicThemeAlias.theme_id == theme_id,
                    EconomicThemeAlias.normalized_alias == normalized,
                )
            )
            > 0
        )

    def _persist_attempt(
        self,
        session,
        plan,
        *,
        result_status,
        output_version_id,
        result_payload,
        event_types,
    ):
        attempt = ClassificationAttempt(
            processing_request_id=plan.request_id,
            claim_review_artifact_id=plan.claim_review_artifact_id,
            input_taxonomy_version_id=plan.input_taxonomy_version_id,
            output_taxonomy_version_id=output_version_id,
            resolver_policy_version=self.resolver_policy_version,
            naming_policy_version=self.naming_policy_version,
            derivation_policy_version=self.derivation_policy_version,
            result_status=result_status,
            result_payload=result_payload,
        )
        session.add(attempt)
        session.flush()
        for sequence, event_type in enumerate(event_types, start=1):
            session.add(
                ClassificationAttemptEvent(
                    classification_attempt_id=attempt.id,
                    sequence_number=sequence,
                    event_type=event_type,
                    event_payload={},
                )
            )
        session.flush()
        return attempt

    @staticmethod
    def _persist_assignments(session, plan, attempt_id, theme_ids):
        rows = []
        for candidate in plan.candidates:
            theme_id = theme_ids[candidate.identity_key]
            fingerprint = sha256(
                json.dumps(
                    candidate.raw_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            row = ClaimAssignment(
                classification_attempt_id=attempt_id,
                claim_fingerprint=fingerprint,
                economic_theme_id=theme_id,
                exposure_support=str(
                    candidate.raw_payload.get("exposure_support") or "unresolved"
                ),
                claim_payload=candidate.raw_payload,
                provenance={
                    "candidate_key": candidate.candidate_key,
                    "relationship_outcome": candidate.outcome,
                },
            )
            session.add(row)
            rows.append(row)
        session.flush()
        return rows

    @staticmethod
    def _input_version_for_request(session, *, request, authority) -> UUID:
        observed_revision = request.observed_processing_head_revision
        if observed_revision is None:
            raise WorkLeaseError("request has no observed processing head")
        distance = authority.processing_head_revision - observed_revision
        if distance < 0:
            raise RuntimeError("observed_processing_head_is_in_the_future")
        version_id = authority.processing_taxonomy_version_id
        for _step in range(distance):
            version = session.get(TaxonomyVersion, version_id)
            if version is None or version.parent_version_id is None:
                raise RuntimeError("observed_processing_version_not_reconstructable")
            version_id = version.parent_version_id
        return version_id

    def _selected_review(self, session, request, *, facet_catalog_semantic_hash: str):
        review = session.execute(
            select(ClaimReviewArtifact)
            .join(
                ExtractionArtifact,
                ClaimReviewArtifact.extraction_artifact_id == ExtractionArtifact.id,
            )
            .where(
                ExtractionArtifact.evidence_packet_id == request.evidence_packet_id,
                ClaimReviewArtifact.facet_catalog_semantic_hash
                == facet_catalog_semantic_hash,
            )
            .order_by(ClaimReviewArtifact.created_at.desc(), ClaimReviewArtifact.id)
            .limit(1)
        ).scalar_one_or_none()
        if review is None:
            raise ProviderResultUnavailable("claim_review_artifact_missing")
        return review

    def _find_attempt(
        self, session, *, request_id, review_id, input_version_id
    ) -> ClassificationAttempt | None:
        return session.execute(
            select(ClassificationAttempt).where(
                ClassificationAttempt.processing_request_id == request_id,
                ClassificationAttempt.claim_review_artifact_id == review_id,
                ClassificationAttempt.input_taxonomy_version_id == input_version_id,
                ClassificationAttempt.resolver_policy_version
                == self.resolver_policy_version,
                ClassificationAttempt.naming_policy_version
                == self.naming_policy_version,
                ClassificationAttempt.derivation_policy_version
                == self.derivation_policy_version,
            )
        ).scalar_one_or_none()

    def _completed_result(self, request_id: UUID) -> ProcessResult | None:
        with self.session_factory() as session:
            attempt = session.execute(
                select(ClassificationAttempt)
                .where(
                    ClassificationAttempt.processing_request_id == request_id,
                    ClassificationAttempt.result_status == "completed",
                    ClassificationAttempt.resolver_policy_version
                    == self.resolver_policy_version,
                    ClassificationAttempt.naming_policy_version
                    == self.naming_policy_version,
                    ClassificationAttempt.derivation_policy_version
                    == self.derivation_policy_version,
                )
                .order_by(ClassificationAttempt.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if attempt is None:
                return None
            return self._result_from_loaded_attempt(session, attempt, reused=True)

    @staticmethod
    def _result_from_attempt(*, session_factory, attempt_id, reused):
        with session_factory() as session:
            attempt = session.get(ClassificationAttempt, attempt_id)
            if attempt is None:
                raise RuntimeError("classification attempt disappeared")
            return EconomicTaxonomyProcessor._result_from_loaded_attempt(
                session, attempt, reused=reused
            )

    @staticmethod
    def _result_from_loaded_attempt(session, attempt, *, reused):
        assignment_ids = tuple(
            session.scalars(
                select(ClaimAssignment.id)
                .where(ClaimAssignment.classification_attempt_id == attempt.id)
                .order_by(ClaimAssignment.created_at, ClaimAssignment.id)
            ).all()
        )
        count = session.scalar(
            select(func.count())
            .select_from(ClassificationAttempt)
            .where(
                ClassificationAttempt.processing_request_id
                == attempt.processing_request_id
            )
        )
        return ProcessResult(
            classification_attempt_id=attempt.id,
            input_taxonomy_version_id=attempt.input_taxonomy_version_id,
            output_taxonomy_version_id=attempt.output_taxonomy_version_id,
            assignment_ids=assignment_ids,
            created_identity_count=0,
            classification_attempt_count=int(count or 0),
            reused=reused,
        )

    @staticmethod
    def _resolution_candidate(row: RetrievedThemeCandidate) -> ResolutionCandidate:
        return ResolutionCandidate(
            theme_id=row.theme_id,
            display_name=row.display_name,
            definition=row.definition,
            mechanism=row.mechanism,
            normalized_facets=dict(row.normalized_facets),
            aliases=tuple(row.aliases),
        )

    @staticmethod
    def _plan_payload(plan, *, resolved_theme_ids=None):
        resolved_theme_ids = resolved_theme_ids or {}
        return {
            "status": "successful_empty" if plan.successful_empty else "classified",
            "claims": [
                {
                    "candidate_key": candidate.candidate_key,
                    "identity_key": candidate.identity_key,
                    "outcome": candidate.outcome,
                    "target_theme_id": (
                        str(candidate.target_theme_id)
                        if candidate.target_theme_id
                        else None
                    ),
                    "resolved_theme_id": (
                        str(resolved_theme_ids[candidate.identity_key])
                        if candidate.identity_key in resolved_theme_ids
                        else None
                    ),
                }
                for candidate in plan.candidates
            ],
        }

    @staticmethod
    def _hash(payload) -> str:
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
