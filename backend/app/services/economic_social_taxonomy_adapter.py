"""Economic Social association revisions, admission, and legacy mirroring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.domain.economic_taxonomy.policy import reconcile_social_decisions
from app.infra.db.models.social_analysis import (
    EconomicSocialAssociation,
    EconomicSocialAssociationRevision,
    EconomicSocialAssociationSource,
    EconomicSocialDecisionRevision,
    SocialExtractionWork,
    SocialRunWork,
    SocialThemeAssociation,
    SocialThemeDecision,
)
from app.infra.db.models.social_signals import SocialSignalRun
from app.models.economic_taxonomy_runtime import (
    SocialAssociationRevisionRef,
    TaxonomyAuthority,
)
from app.models.stock_universe import StockUniverse
from app.models.theme import ThemeCluster
from app.services.economic_source_admission import (
    AdmissionResult,
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_fence import producer_write
from app.services.economic_taxonomy_runtime import EconomicTaxonomyRuntimeService
from app.utils.file_hashing import canonical_json_sha256 as _semantic_hash


@dataclass(frozen=True, slots=True)
class EconomicSocialProjectionResult:
    association_id: UUID
    association_revision_id: UUID
    global_association_count: int
    bridge_count: int
    state: str
    live: bool


@dataclass(frozen=True, slots=True)
class EconomicSocialMembership:
    association_id: UUID
    association_revision_id: UUID
    revision_number: int
    economic_theme_id: UUID
    security_id: int
    state: str
    live: bool
    admission_state: str
    mirror_state: str


@dataclass(frozen=True, slots=True)
class SocialEvidenceAdmissionResult:
    source_family_id: UUID
    source_lineage_id: UUID
    packet_id: UUID
    evidence_revision_ordinal: int
    precedence_state: str
    admission_state: str
    live: bool


class EconomicSocialTaxonomyAdapter:
    """Preserve legacy Social history while projecting global memberships."""

    def __init__(self, db):
        self.db = db

    def get_or_create_association(
        self, economic_theme_id: UUID, security_id: int
    ) -> EconomicSocialAssociation:
        association = self.db.scalar(
            select(EconomicSocialAssociation).where(
                EconomicSocialAssociation.economic_theme_id == economic_theme_id,
                EconomicSocialAssociation.security_id == security_id,
            )
        )
        if association is not None:
            return association
        try:
            with self.db.begin_nested():
                association = EconomicSocialAssociation(
                    economic_theme_id=economic_theme_id,
                    security_id=security_id,
                )
                self.db.add(association)
                self.db.flush()
                return association
        except IntegrityError:
            return self.db.scalar(
                select(EconomicSocialAssociation).where(
                    EconomicSocialAssociation.economic_theme_id
                    == economic_theme_id,
                    EconomicSocialAssociation.security_id == security_id,
                )
            )

    def project_legacy_associations(
        self,
        *,
        economic_theme_id: UUID,
        security_id: int,
        legacy_association_ids: tuple[int, ...],
    ) -> EconomicSocialProjectionResult:
        if not legacy_association_ids:
            raise ValueError("legacy_association_ids_required")
        association = self.get_or_create_association(economic_theme_id, security_id)
        legacy_rows = self.db.scalars(
            select(SocialThemeAssociation).where(
                SocialThemeAssociation.id.in_(set(legacy_association_ids))
            )
        ).all()
        if {row.id for row in legacy_rows} != set(legacy_association_ids):
            raise ValueError("legacy_association_missing")
        security = self.db.get(StockUniverse, security_id)
        if security is None or any(
            row.market != security.market or row.canonical_symbol != security.symbol
            for row in legacy_rows
        ):
            raise ValueError("legacy_association_security_mismatch")

        for legacy in legacy_rows:
            source_key = f"legacy_association:{legacy.id}"
            existing = self.db.scalar(
                select(EconomicSocialAssociationSource).where(
                    EconomicSocialAssociationSource.association_id == association.id,
                    EconomicSocialAssociationSource.source_kind
                    == "legacy_association",
                    EconomicSocialAssociationSource.source_key == source_key,
                )
            )
            if existing is None:
                self.db.add(
                    EconomicSocialAssociationSource(
                        association_id=association.id,
                        source_kind="legacy_association",
                        source_key=source_key,
                        legacy_association_id=legacy.id,
                    )
                )
            for work_id in sorted(set(legacy.evidence_work_ids or ())):
                work_key = f"social_work:{work_id}"
                work_source = self.db.scalar(
                    select(EconomicSocialAssociationSource).where(
                        EconomicSocialAssociationSource.association_id
                        == association.id,
                        EconomicSocialAssociationSource.source_kind == "social_work",
                        EconomicSocialAssociationSource.source_key == work_key,
                    )
                )
                if work_source is None:
                    self.db.add(
                        EconomicSocialAssociationSource(
                            association_id=association.id,
                            source_kind="social_work",
                            source_key=work_key,
                            social_work_id=work_id,
                        )
                    )
        self.db.flush()

        all_legacy_ids = tuple(
            self.db.scalars(
                select(EconomicSocialAssociationSource.legacy_association_id).where(
                    EconomicSocialAssociationSource.association_id == association.id,
                    EconomicSocialAssociationSource.source_kind
                    == "legacy_association",
                    EconomicSocialAssociationSource.legacy_association_id.is_not(None),
                )
            )
        )
        legacy_rows = self.db.scalars(
            select(SocialThemeAssociation).where(
                SocialThemeAssociation.id.in_(all_legacy_ids)
            )
        ).all()

        admin_states = {
            row.state for row in legacy_rows if row.decision_owner == "admin"
        }
        if {"accepted", "rejected"} <= admin_states:
            reconciled = reconcile_social_decisions(("accepted", "rejected"))
        elif "rejected" in admin_states:
            reconciled = reconcile_social_decisions(("rejected",))
        elif "accepted" in admin_states:
            reconciled = reconcile_social_decisions(("accepted",))
        else:
            reconciled = reconcile_social_decisions(
                tuple(
                    row.state for row in sorted(legacy_rows, key=lambda row: row.id)
                )
            )
        legacy_decisions = self.db.scalars(
            select(SocialThemeDecision).where(
                SocialThemeDecision.association_id.in_(set(all_legacy_ids))
            )
        ).all()
        source_payload = {
            "legacy_associations": [
                {
                    "association_id": row.id,
                    "decision_owner": row.decision_owner,
                    "state": row.state,
                    "version": row.version,
                }
                for row in sorted(legacy_rows, key=lambda row: row.id)
            ],
            "legacy_decision_ids": sorted(row.id for row in legacy_decisions),
        }
        digest = _semantic_hash(source_payload)
        revision = self.db.scalar(
            select(EconomicSocialAssociationRevision).where(
                EconomicSocialAssociationRevision.association_id == association.id,
                EconomicSocialAssociationRevision.reconciliation_hash == digest,
            )
        )
        if revision is None:
            decision = self._create_decision(
                association.id,
                state=reconciled.state,
                idempotency_key=f"legacy-reconciliation:{digest}",
                actor="system:economic-social-reconciliation",
                reason="legacy_association_reconciliation",
                source_payload=source_payload,
            )
            revision = self._create_revision(
                association.id,
                state=reconciled.state,
                live=reconciled.live,
                admission_state="live",
                mirror_state="acknowledged",
                reconciliation_hash=digest,
                decision_revision_id=decision.id,
                details=source_payload,
            )
        bridge_count = self.db.scalar(
            select(func.count())
            .select_from(EconomicSocialAssociationSource)
            .where(
                EconomicSocialAssociationSource.association_id == association.id,
                EconomicSocialAssociationSource.source_kind == "legacy_association",
            )
        )
        return EconomicSocialProjectionResult(
            association_id=association.id,
            association_revision_id=revision.id,
            global_association_count=1,
            bridge_count=int(bridge_count or 0),
            state=revision.state,
            live=revision.live,
        )

    def revise(
        self,
        association_id: UUID,
        *,
        state: str,
        idempotency_key: str,
        actor: str,
        reason: str,
        mirror_acknowledged: bool,
        admission_state: str = "live",
        evidence_packet_id: UUID | None = None,
    ) -> EconomicSocialAssociationRevision:
        if state not in {"proposed", "accepted", "rejected"}:
            raise ValueError("invalid_economic_social_decision")
        existing_decision = self.db.scalar(
            select(EconomicSocialDecisionRevision).where(
                EconomicSocialDecisionRevision.association_id == association_id,
                EconomicSocialDecisionRevision.idempotency_key == idempotency_key,
            )
        )
        if existing_decision is not None:
            if (
                existing_decision.state != state
                or existing_decision.actor != actor
                or existing_decision.reason != reason
            ):
                raise ValueError("economic_social_decision_idempotency_conflict")
            return self.db.scalar(
                select(EconomicSocialAssociationRevision).where(
                    EconomicSocialAssociationRevision.decision_revision_id
                    == existing_decision.id
                )
            )
        decision = self._create_decision(
            association_id,
            state=state,
            idempotency_key=idempotency_key,
            actor=actor,
            reason=reason,
            source_payload={},
        )
        pending_mirror = state == "accepted" and not mirror_acknowledged
        effective_state = "pending_legacy_mirror" if pending_mirror else state
        live = (
            state == "accepted"
            and admission_state == "live"
            and mirror_acknowledged
        )
        projection_event_id = None
        if pending_mirror:
            authority = self.db.get(TaxonomyAuthority, 1)
            if (
                authority is not None
                and authority.mode in {"dual", "economic"}
                and authority.serving_generation_id is not None
            ):
                association = self.db.get(EconomicSocialAssociation, association_id)
                lineage = f"economic-social-association:{association_id}"
                event = EconomicTaxonomyRuntimeService(self.db).stage_projection_fanout(
                    generation_id=authority.serving_generation_id,
                    affected_lineages=(lineage,),
                    projection_kind="social_membership",
                    projection_version=1,
                    target="legacy",
                    payload_by_lineage={
                        lineage: {
                            "association_id": str(association_id),
                            "economic_theme_id": str(association.economic_theme_id),
                            "security_id": association.security_id,
                            "state": state,
                        }
                    },
                    staged_epoch=authority.authority_epoch,
                    origin_representation="economic",
                    selected_interpretation_version=f"social-decision:{decision.id}",
                    mapping_version="economic-social-v1",
                )[0]
                projection_event_id = event.id
        return self._create_revision(
            association_id,
            state=effective_state,
            live=live,
            admission_state=admission_state,
            mirror_state="acknowledged" if mirror_acknowledged else "pending",
            reconciliation_hash=_semantic_hash(
                {
                    "decision_revision_id": decision.id,
                    "admission_state": admission_state,
                    "mirror_acknowledged": mirror_acknowledged,
                    "evidence_packet_id": evidence_packet_id,
                }
            ),
            decision_revision_id=decision.id,
            evidence_packet_id=evidence_packet_id,
            projection_event_id=projection_event_id,
            details={"requested_state": state},
        )

    def apply_legacy_mirror(
        self,
        association_revision_id: UUID,
        *,
        now: datetime | None = None,
    ) -> EconomicSocialAssociationRevision:
        """Create compatibility rows and append an acknowledged global revision."""

        authority = self.db.get(TaxonomyAuthority, 1)
        expected_epoch = authority.authority_epoch if authority is not None else 1
        with producer_write(
            self.db,
            expected_epoch=expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ):
            return self._apply_legacy_mirror(
                association_revision_id,
                now=now,
            )

    def _apply_legacy_mirror(
        self,
        association_revision_id: UUID,
        *,
        now: datetime | None = None,
    ) -> EconomicSocialAssociationRevision:
        """Apply the mirror while the shared authority fence is held."""

        now = now or datetime.now(timezone.utc)
        revision = self.db.get(
            EconomicSocialAssociationRevision, association_revision_id
        )
        if revision is None:
            raise KeyError(
                f"economic social revision {association_revision_id} not found"
            )
        if revision.state != "pending_legacy_mirror":
            return revision
        association = self.db.get(EconomicSocialAssociation, revision.association_id)
        security = self.db.get(StockUniverse, association.security_id)
        if security is None:
            raise ValueError("economic_social_security_missing")
        canonical_key = f"economic_{association.economic_theme_id.hex}"
        cluster = self.db.scalar(
            select(ThemeCluster).where(
                ThemeCluster.pipeline == "technical",
                ThemeCluster.canonical_key == canonical_key,
            )
        )
        if cluster is None:
            display_name = f"Economic Theme {association.economic_theme_id}"
            cluster = ThemeCluster(
                name=display_name,
                display_name=display_name,
                canonical_key=canonical_key,
                pipeline="technical",
                aliases=[],
                discovery_source="economic_mirror",
                first_seen_at=now,
                last_seen_at=now,
                lifecycle_state="candidate",
                is_active=True,
            )
            self.db.add(cluster)
            self.db.flush()
        legacy = self.db.scalar(
            select(SocialThemeAssociation).where(
                SocialThemeAssociation.theme_cluster_id == cluster.id,
                SocialThemeAssociation.market == security.market,
                SocialThemeAssociation.canonical_symbol == security.symbol,
            )
        )
        if legacy is None:
            legacy = SocialThemeAssociation(
                theme_cluster_id=cluster.id,
                company_key=None,
                market=security.market,
                canonical_symbol=security.symbol,
                state="accepted",
                origin="social",
                decision_owner="system",
                evidence_work_ids=[],
                policy_version="economic-social-v1",
                version=1,
                first_seen_at=now,
                accepted_at=now,
                updated_at=now,
            )
            self.db.add(legacy)
            self.db.flush()
        source_key = f"legacy_association:{legacy.id}"
        bridge = self.db.scalar(
            select(EconomicSocialAssociationSource).where(
                EconomicSocialAssociationSource.association_id == association.id,
                EconomicSocialAssociationSource.source_kind == "legacy_association",
                EconomicSocialAssociationSource.source_key == source_key,
            )
        )
        if bridge is None:
            self.db.add(
                EconomicSocialAssociationSource(
                    association_id=association.id,
                    source_kind="legacy_association",
                    source_key=source_key,
                    legacy_association_id=legacy.id,
                )
            )
        digest = _semantic_hash(
            {
                "acknowledges_revision_id": revision.id,
                "legacy_association_id": legacy.id,
            }
        )
        existing = self.db.scalar(
            select(EconomicSocialAssociationRevision).where(
                EconomicSocialAssociationRevision.association_id == association.id,
                EconomicSocialAssociationRevision.reconciliation_hash == digest,
            )
        )
        if existing is not None:
            return existing
        return self._create_revision(
            association.id,
            state="accepted",
            live=revision.admission_state == "live",
            admission_state=revision.admission_state,
            mirror_state="acknowledged",
            reconciliation_hash=digest,
            decision_revision_id=revision.decision_revision_id,
            evidence_packet_id=revision.evidence_packet_id,
            projection_event_id=revision.projection_event_id,
            details={
                "acknowledges_revision_id": str(revision.id),
                "legacy_association_id": legacy.id,
            },
        )

    def pin_revision(self, revision_id: UUID) -> SocialAssociationRevisionRef:
        revision = self.db.get(EconomicSocialAssociationRevision, revision_id)
        if revision is None:
            raise KeyError(f"economic social revision {revision_id} not found")
        existing = self.db.scalar(
            select(SocialAssociationRevisionRef).where(
                SocialAssociationRevisionRef.association_id == revision.association_id,
                SocialAssociationRevisionRef.revision_number
                == revision.revision_number,
            )
        )
        if existing is not None:
            return existing
        ref = SocialAssociationRevisionRef(
            association_id=revision.association_id,
            revision_number=revision.revision_number,
            decision_revision_id=revision.decision_revision_id,
        )
        self.db.add(ref)
        self.db.flush()
        return ref

    def membership(self, revision_ref_id: UUID) -> EconomicSocialMembership:
        ref = self.db.get(SocialAssociationRevisionRef, revision_ref_id)
        if ref is None:
            raise KeyError(f"social association revision ref {revision_ref_id} not found")
        revision = self.db.scalar(
            select(EconomicSocialAssociationRevision).where(
                EconomicSocialAssociationRevision.association_id
                == ref.association_id,
                EconomicSocialAssociationRevision.revision_number
                == ref.revision_number,
            )
        )
        association = self.db.get(EconomicSocialAssociation, ref.association_id)
        if revision is None or association is None:
            raise ValueError("economic_social_revision_ref_invalid")
        return EconomicSocialMembership(
            association_id=association.id,
            association_revision_id=revision.id,
            revision_number=revision.revision_number,
            economic_theme_id=association.economic_theme_id,
            security_id=association.security_id,
            state=revision.state,
            live=revision.live,
            admission_state=revision.admission_state,
            mirror_state=revision.mirror_state,
        )

    def admit_saved_work(
        self,
        work_id: int,
        evidence: EvidenceAdmission,
        *,
        policy_admitted: bool = True,
        exploratory: bool = False,
        association_id: UUID | None = None,
    ) -> SocialEvidenceAdmissionResult:
        work = self.db.get(SocialExtractionWork, work_id)
        if work is None:
            raise KeyError(f"social work {work_id} not found")
        admitted: AdmissionResult = EconomicSourceAdmissionService(
            self.db
        ).admit_social_work(evidence)
        published = self.db.scalar(
            select(SocialRunWork.work_id)
            .join(SocialSignalRun, SocialSignalRun.id == SocialRunWork.run_id)
            .where(
                SocialRunWork.work_id == work_id,
                SocialSignalRun.mode == "live",
                SocialSignalRun.status == "published",
            )
            .limit(1)
        )
        live = bool(
            work.state == "succeeded"
            and published is not None
            and policy_admitted
            and not exploratory
            and admitted.precedence_state == "effective"
        )
        if association_id is not None:
            source_key = f"social_work:{work_id}:packet:{admitted.packet_id}"
            existing = self.db.scalar(
                select(EconomicSocialAssociationSource).where(
                    EconomicSocialAssociationSource.association_id == association_id,
                    EconomicSocialAssociationSource.source_kind == "social_work",
                    EconomicSocialAssociationSource.source_key == source_key,
                )
            )
            if existing is None:
                self.db.add(
                    EconomicSocialAssociationSource(
                        association_id=association_id,
                        source_kind="social_work",
                        source_key=source_key,
                        social_work_id=work_id,
                        evidence_packet_id=admitted.packet_id,
                    )
                )
                self.db.flush()
        return SocialEvidenceAdmissionResult(
            source_family_id=admitted.source_family_id,
            source_lineage_id=admitted.source_lineage_id,
            packet_id=admitted.packet_id,
            evidence_revision_ordinal=admitted.evidence_revision_ordinal,
            precedence_state=admitted.precedence_state,
            admission_state="live" if live else "review_only",
            live=live,
        )

    def current_live_memberships(
        self, economic_theme_id: UUID
    ) -> tuple[EconomicSocialMembership, ...]:
        memberships = []
        associations = self.db.scalars(
            select(EconomicSocialAssociation).where(
                EconomicSocialAssociation.economic_theme_id == economic_theme_id
            )
        ).all()
        for association in associations:
            revision = self.db.scalar(
                select(EconomicSocialAssociationRevision)
                .where(
                    EconomicSocialAssociationRevision.association_id
                    == association.id
                )
                .order_by(EconomicSocialAssociationRevision.revision_number.desc())
                .limit(1)
            )
            if revision is not None and revision.live:
                memberships.append(
                    EconomicSocialMembership(
                        association_id=association.id,
                        association_revision_id=revision.id,
                        revision_number=revision.revision_number,
                        economic_theme_id=association.economic_theme_id,
                        security_id=association.security_id,
                        state=revision.state,
                        live=revision.live,
                        admission_state=revision.admission_state,
                        mirror_state=revision.mirror_state,
                    )
                )
        return tuple(sorted(memberships, key=lambda item: item.security_id))

    def _create_decision(
        self,
        association_id: UUID,
        *,
        state: str,
        idempotency_key: str,
        actor: str,
        reason: str,
        source_payload: dict,
    ) -> EconomicSocialDecisionRevision:
        current = self.db.scalar(
            select(func.max(EconomicSocialDecisionRevision.revision_number)).where(
                EconomicSocialDecisionRevision.association_id == association_id
            )
        )
        decision = EconomicSocialDecisionRevision(
            association_id=association_id,
            revision_number=int(current or 0) + 1,
            state=state,
            idempotency_key=idempotency_key,
            actor=actor,
            reason=reason,
            source_payload=source_payload,
        )
        self.db.add(decision)
        self.db.flush()
        return decision

    def _create_revision(
        self,
        association_id: UUID,
        *,
        state: str,
        live: bool,
        admission_state: str,
        mirror_state: str,
        reconciliation_hash: str,
        decision_revision_id: UUID | None,
        details: dict,
        evidence_packet_id: UUID | None = None,
        projection_event_id: UUID | None = None,
    ) -> EconomicSocialAssociationRevision:
        current = self.db.scalar(
            select(func.max(EconomicSocialAssociationRevision.revision_number)).where(
                EconomicSocialAssociationRevision.association_id == association_id
            )
        )
        revision = EconomicSocialAssociationRevision(
            association_id=association_id,
            revision_number=int(current or 0) + 1,
            decision_revision_id=decision_revision_id,
            state=state,
            live=live,
            admission_state=admission_state,
            mirror_state=mirror_state,
            evidence_packet_id=evidence_packet_id,
            projection_event_id=projection_event_id,
            reconciliation_hash=reconciliation_hash,
            details=details,
        )
        self.db.add(revision)
        self.db.flush()
        return revision
