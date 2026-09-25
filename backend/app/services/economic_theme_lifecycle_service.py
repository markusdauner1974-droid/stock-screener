"""Policy-versioned lifecycle evaluation and processing-snapshot proposals."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.models.economic_taxonomy import EconomicThemeRevision
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    InterpretationSelection,
    InterpretationSet,
    TaxonomyAuthority,
    TaxonomyOperationEvent,
    TaxonomyOperationRequest,
    ThemeConstituentExposure,
)
from app.services.economic_taxonomy_operations import (
    EconomicTaxonomyOperationService,
)
from app.services.economic_theme_observation_service import (
    EconomicThemeObservationService,
)
from app.utils.datetime_utils import as_aware_utc as _utc

LIFECYCLE_POLICY_VERSION = "economic-theme-lifecycle-v1"


class LifecycleEvaluationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LifecycleRoot:
    source_family_id: UUID
    available_at: datetime
    observation_kind: str = "primary"
    direct_root: bool = True


@dataclass(frozen=True, slots=True)
class LifecycleTheme:
    theme_id: UUID
    state: str
    roots: tuple[LifecycleRoot, ...]
    accepted_constituent_security_ids: frozenset[int] = frozenset()
    reviewed_multi_security_breadth: bool = False
    breadth_assertion_actor: str | None = None
    state_since: datetime | None = None
    reactivated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LifecycleEvaluation:
    theme_id: UUID
    state: str
    prior_state: str
    roots: tuple[LifecycleRoot, ...]
    accepted_constituent_security_ids: frozenset[int]
    reviewed_multi_security_breadth: bool
    breadth_assertion_actor: str | None
    state_since: datetime | None
    reactivated_at: datetime | None
    transition: str | None
    transitioned_at: datetime | None
    policy_version: str
    evidence_counts: dict[str, int]

    @property
    def changed(self) -> bool:
        return self.state != self.prior_state


@dataclass(frozen=True, slots=True)
class LifecycleSnapshotResult:
    taxonomy_version_id: UUID
    transition_count: int
    evaluations: tuple[LifecycleEvaluation, ...]


class EconomicThemeLifecycleService:
    def __init__(self, session: Session | None = None):
        self.session = session

    @staticmethod
    def evaluate(
        theme: LifecycleTheme | LifecycleEvaluation, *, as_of: datetime
    ) -> LifecycleEvaluation:
        as_of = _utc(as_of)
        roots = tuple(
            root
            for root in theme.roots
            if root.observation_kind == "primary"
            and root.direct_root
            and _utc(root.available_at) <= as_of
        )
        prior_state = theme.state
        state = prior_state
        transition = None
        transitioned_at = None
        reactivated_at = theme.reactivated_at

        roots_30 = EconomicThemeLifecycleService._window_roots(
            roots, as_of=as_of, days=30
        )
        roots_14 = EconomicThemeLifecycleService._window_roots(
            roots, as_of=as_of, days=14
        )
        roots_90 = EconomicThemeLifecycleService._window_roots(
            roots, as_of=as_of, days=90
        )
        root_keys_30 = {
            (root.source_family_id, _utc(root.available_at).date())
            for root in roots_30
        }
        families_30 = {root.source_family_id for root in roots_30}
        dates_30 = {_utc(root.available_at).date() for root in roots_30}
        families_14 = {root.source_family_id for root in roots_14}
        root_keys_14 = {
            (root.source_family_id, _utc(root.available_at).date())
            for root in roots_14
        }
        breadth = len(theme.accepted_constituent_security_ids) >= 2 or (
            theme.reviewed_multi_security_breadth
            and bool((theme.breadth_assertion_actor or "").strip())
        )

        if prior_state == "provisional":
            if (
                len(root_keys_30) >= 3
                and len(families_30) >= 2
                and len(dates_30) >= 2
                and breadth
            ):
                state = "established"
                transition = "provisional_to_established"
        elif prior_state in {"established", "reactivated"}:
            state_age_allows_dormancy = (
                theme.state_since is None
                or _utc(theme.state_since) <= as_of - timedelta(days=90)
            )
            if not roots_90 and state_age_allows_dormancy:
                state = "dormant"
                transition = f"{prior_state}_to_dormant"
        elif prior_state == "dormant":
            if len(root_keys_14) >= 2 and len(families_14) >= 2:
                state = "reactivated"
                transition = "dormant_to_reactivated"
                reactivated_at = as_of
        elif prior_state == "retired":
            state = "retired"
        else:
            raise LifecycleEvaluationError("unsupported_lifecycle_state")

        if state != prior_state:
            transitioned_at = as_of
        return LifecycleEvaluation(
            theme_id=theme.theme_id,
            state=state,
            prior_state=prior_state,
            roots=roots,
            accepted_constituent_security_ids=frozenset(
                theme.accepted_constituent_security_ids
            ),
            reviewed_multi_security_breadth=theme.reviewed_multi_security_breadth,
            breadth_assertion_actor=theme.breadth_assertion_actor,
            state_since=(as_of if state != prior_state else theme.state_since),
            reactivated_at=reactivated_at,
            transition=transition,
            transitioned_at=transitioned_at,
            policy_version=LIFECYCLE_POLICY_VERSION,
            evidence_counts={
                "direct_roots_30d": len(root_keys_30),
                "source_families_30d": len(families_30),
                "dates_30d": len(dates_30),
                "direct_roots_14d": len(root_keys_14),
                "source_families_14d": len(families_14),
                "direct_roots_90d": len(
                    {
                        (root.source_family_id, _utc(root.available_at).date())
                        for root in roots_90
                    }
                ),
                "accepted_constituents": len(
                    theme.accepted_constituent_security_ids
                ),
            },
        )

    def propose_lifecycle_snapshot(
        self,
        *,
        as_of: datetime,
        principal: AdminPrincipal,
        expected_epoch: int,
        themes: Sequence[LifecycleTheme] | None = None,
        interpretation_set_id: UUID | None = None,
        reviewed_breadth_assertions: Mapping[UUID, str] | None = None,
    ) -> LifecycleSnapshotResult:
        if self.session is None:
            raise LifecycleEvaluationError("lifecycle_session_required")
        if themes is None:
            if interpretation_set_id is None:
                raise LifecycleEvaluationError("interpretation_set_required")
            themes = self._load_themes(
                interpretation_set_id=interpretation_set_id,
                reviewed_breadth_assertions=reviewed_breadth_assertions or {},
            )
        evaluations = tuple(self.evaluate(theme, as_of=as_of) for theme in themes)
        transitions = [evaluation for evaluation in evaluations if evaluation.changed]
        authority = self.session.get(TaxonomyAuthority, 1)
        if authority is None or authority.processing_taxonomy_version_id is None:
            raise LifecycleEvaluationError("processing_taxonomy_head_missing")
        output_version_id = authority.processing_taxonomy_version_id
        operations = EconomicTaxonomyOperationService(self.session)
        for evaluation in sorted(transitions, key=lambda item: str(item.theme_id)):
            preview = operations.preview_operation(
                {
                    "operation_kind": "lifecycle_override",
                    "theme_id": str(evaluation.theme_id),
                    "lifecycle": evaluation.state,
                    "lifecycle_policy_version": evaluation.policy_version,
                    "transition": evaluation.transition,
                    "transitioned_at": evaluation.transitioned_at,
                    "reactivated_at": evaluation.reactivated_at,
                    "evidence_counts": evaluation.evidence_counts,
                    "incompatible_with_prepared_generation": True,
                },
                principal=principal,
                expected_epoch=expected_epoch,
            )
            applied = operations.apply_operation(
                preview.preview_id,
                principal=principal,
                reason=(
                    f"Automatic {evaluation.transition} under "
                    f"{evaluation.policy_version}."
                ),
                expected_epoch=expected_epoch,
            )
            output_version_id = applied.taxonomy_version_id
        return LifecycleSnapshotResult(
            taxonomy_version_id=output_version_id,
            transition_count=len(transitions),
            evaluations=evaluations,
        )

    @staticmethod
    def _window_roots(
        roots: Sequence[LifecycleRoot], *, as_of: datetime, days: int
    ) -> tuple[LifecycleRoot, ...]:
        lower = as_of - timedelta(days=days)
        return tuple(root for root in roots if lower <= _utc(root.available_at) <= as_of)

    def _load_themes(
        self,
        *,
        interpretation_set_id: UUID,
        reviewed_breadth_assertions: Mapping[UUID, str],
    ) -> list[LifecycleTheme]:
        authority = self.session.get(TaxonomyAuthority, 1)
        if authority is None or authority.processing_taxonomy_version_id is None:
            raise LifecycleEvaluationError("processing_taxonomy_head_missing")
        version_id = authority.processing_taxonomy_version_id
        revisions = self.session.scalars(
            select(EconomicThemeRevision).where(
                EconomicThemeRevision.taxonomy_version_id == version_id
            )
        ).all()
        interpretation = self.session.get(InterpretationSet, interpretation_set_id)
        if interpretation is None:
            raise LifecycleEvaluationError("interpretation_set_not_found")
        facts = EconomicThemeObservationService._observations_for_set(
            self.session,
            interpretation_set_id,
            interpretation.generation_input_manifest_id,
        )
        roots: dict[UUID, list[LifecycleRoot]] = defaultdict(list)
        for fact in facts:
            roots[fact.economic_theme_id].append(
                LifecycleRoot(
                    source_family_id=fact.source_family_id,
                    available_at=fact.available_at,
                    observation_kind=fact.observation_kind,
                    direct_root=bool(fact.payload.get("direct_root", False)),
                )
            )
        exposure_rows = self.session.execute(
            select(ThemeConstituentExposure, ClaimAssignment)
            .join(
                ClaimAssignment,
                ClaimAssignment.id == ThemeConstituentExposure.claim_assignment_id,
            )
            .join(
                InterpretationSelection,
                InterpretationSelection.selected_classification_attempt_id
                == ClaimAssignment.classification_attempt_id,
            )
            .where(
                InterpretationSelection.interpretation_set_id
                == interpretation_set_id
            )
        ).all()
        constituents: dict[UUID, set[int]] = defaultdict(set)
        for exposure, assignment in exposure_rows:
            if exposure.payload.get("decision", "accepted") == "accepted":
                constituents[assignment.economic_theme_id].add(exposure.security_id)
        lifecycle_times, reactivated_at = self._lifecycle_times()
        return [
            LifecycleTheme(
                theme_id=revision.theme_id,
                state=revision.lifecycle,
                roots=tuple(roots.get(revision.theme_id, ())),
                accepted_constituent_security_ids=frozenset(
                    constituents.get(revision.theme_id, set())
                ),
                reviewed_multi_security_breadth=(
                    revision.theme_id in reviewed_breadth_assertions
                ),
                breadth_assertion_actor=reviewed_breadth_assertions.get(
                    revision.theme_id
                ),
                state_since=lifecycle_times.get(revision.theme_id),
                reactivated_at=reactivated_at.get(revision.theme_id),
            )
            for revision in revisions
        ]

    def _lifecycle_times(self) -> tuple[dict[UUID, datetime], dict[UUID, datetime]]:
        rows = self.session.execute(
            select(TaxonomyOperationRequest, TaxonomyOperationEvent)
            .join(
                TaxonomyOperationEvent,
                TaxonomyOperationEvent.operation_request_id
                == TaxonomyOperationRequest.id,
            )
            .where(
                TaxonomyOperationRequest.operation_kind == "lifecycle_override",
                TaxonomyOperationEvent.event_type == "applied",
            )
            .order_by(TaxonomyOperationEvent.created_at)
        ).all()
        state_times: dict[UUID, datetime] = {}
        reactivation_times: dict[UUID, datetime] = {}
        for request, event in rows:
            theme_id = UUID(str(request.request_payload["theme_id"]))
            transitioned = request.request_payload.get("transitioned_at")
            transitioned_at = (
                _utc(datetime.fromisoformat(transitioned.replace("Z", "+00:00")))
                if isinstance(transitioned, str) and transitioned
                else _utc(event.created_at)
            )
            state_times[theme_id] = transitioned_at
            if request.request_payload.get("lifecycle") == "reactivated":
                reactivated = request.request_payload.get("reactivated_at")
                reactivation_times[theme_id] = (
                    _utc(datetime.fromisoformat(reactivated.replace("Z", "+00:00")))
                    if isinstance(reactivated, str) and reactivated
                    else transitioned_at
                )
        return state_times, reactivation_times
