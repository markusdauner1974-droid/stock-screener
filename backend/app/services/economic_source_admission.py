"""Admit immutable, route-aware evidence for Economic Theme processing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.economic_taxonomy.contracts import (
    EvidenceChannel,
    EvidencePacketDescriptor,
    EvidencePrecedenceDecision,
    SourceLineageKey,
)
from app.domain.economic_taxonomy.policy import decide_evidence_precedence
from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.models.economic_taxonomy_runtime import (
    EvidencePacket,
    EvidencePrecedenceRevision,
    LensEligibilityRevision,
    SourceFamily,
    SourceLineage,
    TaxonomyAuthority,
)
from app.services.economic_taxonomy_fence import producer_write
from app.utils.file_hashing import canonical_json_sha256 as _hash


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ordered(values) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


@dataclass(frozen=True, slots=True)
class EvidenceAdmission:
    provider: str
    capture_route: str
    original_text: str
    preparation_version: str
    canonical_item_id: str | None = None
    canonical_source_family: str | None = None
    route_record_id: str | None = None
    translated_text: str | None = None
    translation_version: str | None = None
    attachment_hashes: tuple[str, ...] = ()
    extracted_text_hashes: tuple[str, ...] = ()
    grounding_snapshot: Mapping[str, Any] = field(default_factory=dict)
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    provider_revision_id: str | None = None
    provider_revision_order: int | None = None
    captured_at: datetime = field(default_factory=_utcnow)
    observed_at: datetime | None = None
    available_at: datetime = field(default_factory=_utcnow)
    evidence_channels: tuple[str, ...] = ()
    supersedes_packet_id: UUID | None = None
    equivalent_packet_id: UUID | None = None
    scope_suffix: str | None = None
    admission_policy_key: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.provider, "provider"),
            (self.capture_route, "capture_route"),
            (self.preparation_version, "preparation_version"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if self.canonical_source_family is None and not self.canonical_item_id:
            raise ValueError("canonical_item_id or canonical_source_family is required")
        SourceLineageKey(
            canonical_source_family=self.family_key,
            scope_suffix=self.scope_suffix,
            admission_policy_key=self.admission_policy_key,
        )
        allowed = {channel.value for channel in EvidenceChannel}
        unknown = set(self.evidence_channels) - allowed
        if unknown:
            raise ValueError(f"unknown evidence channels: {sorted(unknown)}")

    @property
    def family_key(self) -> str:
        if self.canonical_source_family:
            return self.canonical_source_family.strip()
        return f"{self.provider.strip().lower()}:post:{self.canonical_item_id}"


@dataclass(frozen=True, slots=True)
class AdmissionResult:
    source_family_id: UUID
    source_lineage_id: UUID
    packet_id: UUID
    effective_packet_id: UUID | None
    evidence_revision_ordinal: int
    precedence_state: str
    packet_hash: str
    evidence_content_fingerprint: str


@dataclass(frozen=True, slots=True)
class LensEligibilityResult:
    packet_id: UUID
    revision_number: int
    evidence_channels: tuple[str, ...]
    enqueued_request_id: None = None


class EconomicSourceAdmissionService:
    """Resolve source identity and preserve exact evidence packet history."""

    def __init__(self, session: Session):
        self.session = session

    def admit_content(self, evidence: EvidenceAdmission) -> AdmissionResult:
        return self.admit(evidence)

    def admit_social_work(self, evidence: EvidenceAdmission) -> AdmissionResult:
        return self.admit(evidence)

    def admit(self, evidence: EvidenceAdmission) -> AdmissionResult:
        expected_epoch = self._current_epoch()
        with producer_write(
            self.session,
            expected_epoch=expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ) as authority:
            return self._admit(
                evidence,
                authority_epoch=authority.authority_epoch,
            )

    def _admit(
        self,
        evidence: EvidenceAdmission,
        *,
        authority_epoch: int,
    ) -> AdmissionResult:
        family = self._get_or_create_family(evidence)
        lineage = self._get_or_create_lineage(family, evidence)
        self.session.execute(
            select(SourceLineage.id)
            .where(SourceLineage.id == lineage.id)
            .with_for_update()
        ).scalar_one()

        fingerprint = self._content_fingerprint(evidence)
        packet_hash = self._packet_hash(evidence, fingerprint)
        existing = self.session.execute(
            select(EvidencePacket).where(
                EvidencePacket.source_lineage_id == lineage.id,
                EvidencePacket.packet_hash == packet_hash,
            )
        ).scalar_one_or_none()
        if existing is not None:
            effective = self.effective_packet(lineage.id)
            if effective is not None and (
                existing.id == effective.id
                or existing.precedence_state == "equivalent"
            ):
                self._merge_equivalent_eligibility(
                    effective,
                    evidence.evidence_channels,
                    authority_epoch=authority_epoch,
                )
            return self._result(family, lineage, existing, effective)

        accepted = self.effective_packet(lineage.id)
        packet_id = uuid4()
        candidate = EvidencePacketDescriptor(
            packet_id=str(packet_id),
            evidence_content_fingerprint=fingerprint,
            provider_revision_id=evidence.provider_revision_id,
            provider_revision_order=evidence.provider_revision_order,
            supersedes_packet_id=(
                str(evidence.supersedes_packet_id)
                if evidence.supersedes_packet_id is not None
                else None
            ),
            equivalent_to_packet_id=(
                str(evidence.equivalent_packet_id)
                if evidence.equivalent_packet_id is not None
                else None
            ),
            captured_from=evidence.capture_route,
            attachment_hashes=frozenset(evidence.attachment_hashes),
        )
        if accepted is None and self._is_unordered_archive(evidence):
            decision = EvidencePrecedenceDecision.HOLD_REVIEW
        else:
            decision = decide_evidence_precedence(
                self._descriptor(accepted) if accepted is not None else None,
                candidate,
            )
        state = {
            EvidencePrecedenceDecision.ADVANCE: "effective",
            EvidencePrecedenceDecision.REUSE_EQUIVALENT: "equivalent",
            EvidencePrecedenceDecision.IGNORE_SUPERSEDED: "superseded",
            EvidencePrecedenceDecision.HOLD_REVIEW: "hold_review",
        }[decision]
        equivalent_id = evidence.equivalent_packet_id
        if decision is EvidencePrecedenceDecision.REUSE_EQUIVALENT and accepted:
            equivalent_id = accepted.id

        packet = EvidencePacket(
            id=packet_id,
            source_lineage_id=lineage.id,
            packet_hash=packet_hash,
            evidence_content_fingerprint=fingerprint,
            provider_revision_id=evidence.provider_revision_id,
            provider_revision_order=(
                str(evidence.provider_revision_order)
                if evidence.provider_revision_order is not None
                else None
            ),
            capture_route=evidence.capture_route,
            captured_at=evidence.captured_at,
            supersedes_evidence_packet_id=evidence.supersedes_packet_id,
            equivalent_evidence_packet_id=equivalent_id,
            precedence_state=state,
            original_text_ref=evidence.original_text,
            translated_text_ref=evidence.translated_text,
            translation_version=evidence.translation_version,
            attachment_hashes=list(_ordered(evidence.attachment_hashes)),
            extracted_text_hashes=list(_ordered(evidence.extracted_text_hashes)),
            grounding_snapshot=dict(evidence.grounding_snapshot),
            preparation_version=evidence.preparation_version,
            source_metadata={
                **dict(evidence.source_metadata),
                "capture_route": evidence.capture_route,
                "route_record_id": evidence.route_record_id,
            },
            observed_at=evidence.observed_at,
            available_at=evidence.available_at,
        )
        self.session.add(packet)
        self.session.flush()
        precedence_revision = self._next_precedence_revision(lineage.id)
        self.session.add(
            EvidencePrecedenceRevision(
                source_lineage_id=lineage.id,
                evidence_packet_id=packet.id,
                revision_number=precedence_revision,
                disposition=state,
                related_evidence_packet_id=(accepted.id if accepted else None),
                reason=decision.value,
            )
        )
        self.session.add(
            LensEligibilityRevision(
                source_lineage_id=lineage.id,
                evidence_packet_id=packet.id,
                revision_number=1,
                evidence_channels=list(_ordered(evidence.evidence_channels)),
                reason="admission",
            )
        )
        self.session.flush()
        effective = packet if state == "effective" else accepted
        if state == "equivalent" and effective is not None:
            self._merge_equivalent_eligibility(
                effective,
                evidence.evidence_channels,
                authority_epoch=authority_epoch,
            )
        return self._result(family, lineage, packet, effective)

    def _merge_equivalent_eligibility(
        self,
        effective: EvidencePacket,
        evidence_channels: tuple[str, ...],
        *,
        authority_epoch: int,
    ) -> None:
        latest = self.session.execute(
            select(LensEligibilityRevision)
            .where(LensEligibilityRevision.evidence_packet_id == effective.id)
            .order_by(LensEligibilityRevision.revision_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        merged = tuple(
            sorted(set(latest.evidence_channels if latest else ()) | set(evidence_channels))
        )
        if latest is not None and tuple(sorted(latest.evidence_channels)) == merged:
            return
        self._revise_lens_eligibility(
            effective.id,
            add=None,
            remove=None,
            evidence_channels=merged,
            reason="equivalent_evidence_admission",
            authority_epoch=authority_epoch,
        )

    def effective_packet(self, lineage_id: UUID) -> EvidencePacket | None:
        return self.session.execute(
            select(EvidencePacket)
            .join(
                EvidencePrecedenceRevision,
                EvidencePrecedenceRevision.evidence_packet_id == EvidencePacket.id,
            )
            .where(
                EvidencePrecedenceRevision.source_lineage_id == lineage_id,
                EvidencePrecedenceRevision.disposition == "effective",
            )
            .order_by(
                EvidencePrecedenceRevision.revision_number.desc(),
                EvidencePrecedenceRevision.created_at.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()

    def revise_lens_eligibility(
        self,
        packet_id: UUID,
        *,
        add: str | None = None,
        remove: str | None = None,
        evidence_channels: tuple[str, ...] | None = None,
        reason: str,
    ) -> LensEligibilityResult:
        expected_epoch = self._current_epoch()
        with producer_write(
            self.session,
            expected_epoch=expected_epoch,
            allowed_modes={"legacy", "shadow", "dual", "economic"},
        ) as authority:
            return self._revise_lens_eligibility(
                packet_id,
                add=add,
                remove=remove,
                evidence_channels=evidence_channels,
                reason=reason,
                authority_epoch=authority.authority_epoch,
            )

    def _revise_lens_eligibility(
        self,
        packet_id: UUID,
        *,
        add: str | None,
        remove: str | None,
        evidence_channels: tuple[str, ...] | None,
        reason: str,
        authority_epoch: int,
    ) -> LensEligibilityResult:
        packet = self.session.get(EvidencePacket, packet_id)
        if packet is None:
            raise KeyError(f"evidence packet {packet_id} not found")
        self.session.execute(
            select(SourceLineage.id)
            .where(SourceLineage.id == packet.source_lineage_id)
            .with_for_update()
        ).scalar_one()
        latest = self.session.execute(
            select(LensEligibilityRevision)
            .where(LensEligibilityRevision.evidence_packet_id == packet.id)
            .order_by(LensEligibilityRevision.revision_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        channels = set(latest.evidence_channels if latest else ())
        if evidence_channels is not None:
            channels = set(evidence_channels)
        if add is not None:
            channels.add(add)
        if remove is not None:
            channels.discard(remove)
        allowed = {channel.value for channel in EvidenceChannel}
        if channels - allowed:
            raise ValueError(f"unknown evidence channels: {sorted(channels - allowed)}")
        revision = LensEligibilityRevision(
            source_lineage_id=packet.source_lineage_id,
            evidence_packet_id=packet.id,
            revision_number=(latest.revision_number + 1 if latest else 1),
            evidence_channels=sorted(channels),
            reason=reason,
        )
        self.session.add(revision)
        self.session.flush()
        EconomicTaxonomyPublicationRepository(self.session).append_source_revision(
            producer_kind="evidence",
            logical_source_key=f"evidence_packet:{packet.id}",
            revision_kind="lens_eligibility",
            revision_number=revision.revision_number,
            content_hash=_hash(
                {
                    "evidence_packet_id": str(packet.id),
                    "revision_number": revision.revision_number,
                    "evidence_channels": list(revision.evidence_channels),
                    "reason": reason,
                }
            ),
            authority_epoch=authority_epoch,
        )
        return LensEligibilityResult(
            packet_id=packet.id,
            revision_number=revision.revision_number,
            evidence_channels=tuple(revision.evidence_channels),
        )

    def _current_epoch(self) -> int:
        authority = self.session.get(TaxonomyAuthority, 1)
        return authority.authority_epoch if authority is not None else 1

    def _get_or_create_family(self, evidence: EvidenceAdmission) -> SourceFamily:
        family = self.session.execute(
            select(SourceFamily).where(
                SourceFamily.canonical_source_key == evidence.family_key
            )
        ).scalar_one_or_none()
        if family is not None:
            return family
        try:
            with self.session.begin_nested():
                family = SourceFamily(
                    provider=evidence.provider.strip().lower(),
                    canonical_source_key=evidence.family_key,
                    canonical_item_id=evidence.canonical_item_id,
                )
                self.session.add(family)
                self.session.flush()
                return family
        except IntegrityError:
            return self.session.execute(
                select(SourceFamily).where(
                    SourceFamily.canonical_source_key == evidence.family_key
                )
            ).scalar_one()

    def _get_or_create_lineage(
        self, family: SourceFamily, evidence: EvidenceAdmission
    ) -> SourceLineage:
        suffix = evidence.scope_suffix or ""
        lineage = self.session.execute(
            select(SourceLineage).where(
                SourceLineage.source_family_id == family.id,
                SourceLineage.scope_suffix == suffix,
            )
        ).scalar_one_or_none()
        if lineage is not None:
            if lineage.admission_policy_key != evidence.admission_policy_key:
                raise ValueError("lineage admission policy does not match")
            return lineage
        try:
            with self.session.begin_nested():
                lineage = SourceLineage(
                    source_family_id=family.id,
                    scope_suffix=suffix,
                    admission_policy_key=evidence.admission_policy_key,
                )
                self.session.add(lineage)
                self.session.flush()
                return lineage
        except IntegrityError:
            return self.session.execute(
                select(SourceLineage).where(
                    SourceLineage.source_family_id == family.id,
                    SourceLineage.scope_suffix == suffix,
                )
            ).scalar_one()

    @staticmethod
    def _content_fingerprint(evidence: EvidenceAdmission) -> str:
        return _hash(
            {
                "original_text": evidence.original_text,
                "translated_text": evidence.translated_text,
                "translation_version": evidence.translation_version,
                "attachment_hashes": _ordered(evidence.attachment_hashes),
                "extracted_text_hashes": _ordered(evidence.extracted_text_hashes),
                "grounding_snapshot": dict(evidence.grounding_snapshot),
                "preparation_version": evidence.preparation_version,
            }
        )

    @staticmethod
    def _packet_hash(evidence: EvidenceAdmission, fingerprint: str) -> str:
        return _hash(
            {
                "evidence_content_fingerprint": fingerprint,
                "provider_revision_id": evidence.provider_revision_id,
                "provider_revision_order": evidence.provider_revision_order,
                "capture_route": evidence.capture_route,
                "route_record_id": evidence.route_record_id,
                "captured_at": evidence.captured_at,
                "observed_at": evidence.observed_at,
                "available_at": evidence.available_at,
                "source_metadata": dict(evidence.source_metadata),
                "supersedes_packet_id": evidence.supersedes_packet_id,
                "equivalent_packet_id": evidence.equivalent_packet_id,
            }
        )

    @staticmethod
    def _descriptor(packet: EvidencePacket) -> EvidencePacketDescriptor:
        provider_order = None
        if packet.provider_revision_order is not None:
            try:
                provider_order = int(packet.provider_revision_order)
            except (TypeError, ValueError):
                provider_order = None
        return EvidencePacketDescriptor(
            packet_id=str(packet.id),
            evidence_content_fingerprint=packet.evidence_content_fingerprint,
            provider_revision_id=packet.provider_revision_id,
            provider_revision_order=provider_order,
            supersedes_packet_id=(
                str(packet.supersedes_evidence_packet_id)
                if packet.supersedes_evidence_packet_id
                else None
            ),
            equivalent_to_packet_id=(
                str(packet.equivalent_evidence_packet_id)
                if packet.equivalent_evidence_packet_id
                else None
            ),
            captured_from=packet.capture_route,
            attachment_hashes=frozenset(packet.attachment_hashes or ()),
        )

    def _next_precedence_revision(self, lineage_id: UUID) -> int:
        current = self.session.scalar(
            select(func.max(EvidencePrecedenceRevision.revision_number)).where(
                EvidencePrecedenceRevision.source_lineage_id == lineage_id
            )
        )
        return int(current or 0) + 1

    @staticmethod
    def _is_unordered_archive(evidence: EvidenceAdmission) -> bool:
        return (
            evidence.provider_revision_id is None
            and evidence.provider_revision_order is None
            and (
                "archive" in evidence.capture_route.lower()
                or bool(evidence.source_metadata.get("archived"))
                or bool(evidence.source_metadata.get("partial_recapture"))
            )
        )

    @staticmethod
    def _result(
        family: SourceFamily,
        lineage: SourceLineage,
        packet: EvidencePacket,
        effective: EvidencePacket | None,
    ) -> AdmissionResult:
        return AdmissionResult(
            source_family_id=family.id,
            source_lineage_id=lineage.id,
            packet_id=packet.id,
            effective_packet_id=effective.id if effective else None,
            evidence_revision_ordinal=packet.evidence_revision_ordinal,
            precedence_state=packet.precedence_state,
            packet_hash=packet.packet_hash,
            evidence_content_fingerprint=packet.evidence_content_fingerprint,
        )
