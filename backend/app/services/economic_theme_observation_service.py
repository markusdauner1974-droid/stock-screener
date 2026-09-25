"""Assignment-derived Economic Theme facts and generation-scoped reads."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.economic_taxonomy import EconomicThemeRelationship
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    ClassificationAttempt,
    ClassificationAttemptEvent,
    EvidencePacket,
    GenerationInputManifest,
    InterpretationSelection,
    LensEligibilityRevision,
    ProcessingRequest,
    ServingGeneration,
    SourceLineage,
    ThemeConstituentExposure,
    ThemeObservation,
    ThemeSignalObservation,
)


class FactMaterializationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    primary_observations: int
    derived_observations: int
    constituent_exposures: int
    signal_observations: int


@dataclass(frozen=True, slots=True)
class ObservationFact:
    observation_id: UUID
    claim_assignment_id: UUID
    economic_theme_id: UUID
    observation_kind: str
    evidence_channel: str
    source_family_id: UUID
    available_at: datetime
    payload: dict[str, Any]


def eligibility_channels_by_attempt(
    session,
    *,
    interpretation_set_id: UUID,
    manifest_id: UUID,
) -> dict[UUID, frozenset[str]]:
    """Resolve the exact lens eligibility pinned for each selected attempt."""

    manifest = session.get(GenerationInputManifest, manifest_id)
    if manifest is None:
        raise FactMaterializationError("generation_manifest_missing")
    revision_by_lineage = {
        str(item.get("lineage")): item.get("eligibility_revision")
        for item in manifest.selections or []
        if item.get("lineage") is not None
        and item.get("eligibility_revision") is not None
    }
    selections = session.scalars(
        select(InterpretationSelection).where(
            InterpretationSelection.interpretation_set_id == interpretation_set_id
        )
    ).all()
    channels_by_attempt: dict[UUID, frozenset[str]] = {}
    for selection in selections:
        revision_number = revision_by_lineage.get(str(selection.source_lineage_id))
        if revision_number is None:
            raise FactMaterializationError("eligibility_revision_not_pinned")
        eligibility = session.scalar(
            select(LensEligibilityRevision).where(
                LensEligibilityRevision.source_lineage_id
                == selection.source_lineage_id,
                LensEligibilityRevision.evidence_packet_id
                == selection.evidence_packet_id,
                LensEligibilityRevision.revision_number == int(revision_number),
            )
        )
        if eligibility is None:
            raise FactMaterializationError("eligibility_revision_not_pinned")
        channels_by_attempt[selection.selected_classification_attempt_id] = frozenset(
            eligibility.evidence_channels
        )
    return channels_by_attempt


def observation_rows_for_interpretation(
    session,
    *,
    interpretation_set_id: UUID,
    manifest_id: UUID,
) -> list[tuple[ThemeObservation, ClaimAssignment]]:
    """Return selected observation rows allowed by the manifest's lens revision."""

    channels_by_attempt = eligibility_channels_by_attempt(
        session,
        interpretation_set_id=interpretation_set_id,
        manifest_id=manifest_id,
    )
    rows = session.execute(
        select(ThemeObservation, ClaimAssignment)
        .join(
            ClaimAssignment,
            ClaimAssignment.id == ThemeObservation.claim_assignment_id,
        )
        .join(
            InterpretationSelection,
            InterpretationSelection.selected_classification_attempt_id
            == ClaimAssignment.classification_attempt_id,
        )
        .where(InterpretationSelection.interpretation_set_id == interpretation_set_id)
        .order_by(ThemeObservation.created_at, ThemeObservation.id)
    ).all()
    return [
        (observation, assignment)
        for observation, assignment in rows
        if observation.evidence_channel
        in channels_by_attempt.get(
            assignment.classification_attempt_id, frozenset()
        )
    ]


def signal_rows_for_interpretation(
    session,
    *,
    interpretation_set_id: UUID,
    manifest_id: UUID,
) -> list[tuple[ThemeSignalObservation, ClaimAssignment]]:
    """Return selected technical signals allowed by pinned lens eligibility."""

    channels_by_attempt = eligibility_channels_by_attempt(
        session,
        interpretation_set_id=interpretation_set_id,
        manifest_id=manifest_id,
    )
    rows = session.execute(
        select(ThemeSignalObservation, ClaimAssignment)
        .join(
            ClaimAssignment,
            ClaimAssignment.id == ThemeSignalObservation.claim_assignment_id,
        )
        .join(
            InterpretationSelection,
            InterpretationSelection.selected_classification_attempt_id
            == ClaimAssignment.classification_attempt_id,
        )
        .where(InterpretationSelection.interpretation_set_id == interpretation_set_id)
        .order_by(ThemeSignalObservation.created_at, ThemeSignalObservation.id)
    ).all()
    return [
        (signal, assignment)
        for signal, assignment in rows
        if "technical"
        in channels_by_attempt.get(
            assignment.classification_attempt_id, frozenset()
        )
    ]


def _as_datetime(value: Any, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _attempt_context(session: Session, attempt_id: UUID):
    attempt = session.get(ClassificationAttempt, attempt_id)
    if attempt is None:
        raise KeyError(f"classification attempt {attempt_id} not found")
    completed = session.scalar(
        select(ClassificationAttemptEvent.id).where(
            ClassificationAttemptEvent.classification_attempt_id == attempt.id,
            ClassificationAttemptEvent.event_type == "completed",
        )
    )
    if attempt.result_status != "completed" or completed is None:
        raise FactMaterializationError("attempt_not_completed")
    request = session.get(ProcessingRequest, attempt.processing_request_id)
    packet = (
        session.get(EvidencePacket, request.evidence_packet_id) if request else None
    )
    lineage = session.get(SourceLineage, packet.source_lineage_id) if packet else None
    if request is None or packet is None or lineage is None:
        raise FactMaterializationError("attempt_evidence_missing")
    return attempt, packet, lineage


def _observation_payload(
    *,
    assignment: ClaimAssignment,
    target_theme_ids: list[UUID],
    packet: EvidencePacket,
    source_family_id: UUID,
    direct_root: bool,
) -> dict[str, Any]:
    payload = {
        "economic_theme_ids": [str(value) for value in target_theme_ids],
        "root_claim_id": assignment.claim_fingerprint,
        "source_family_id": str(source_family_id),
        "source_lineage_id": str(packet.source_lineage_id),
        "evidence_packet_id": str(packet.id),
        "direct_root": direct_root,
        "available_at": _as_datetime(
            packet.available_at, fallback=datetime.now(timezone.utc)
        ).isoformat(),
    }
    if len(target_theme_ids) == 1:
        payload["economic_theme_id"] = str(target_theme_ids[0])
    return payload


def _get_or_create_observation(
    session: Session,
    *,
    assignment: ClaimAssignment,
    observation_kind: str,
    evidence_channel: str,
    derivation_policy_version: str,
    observed_at: datetime | None,
    available_at: datetime,
    payload: dict[str, Any],
) -> ThemeObservation:
    existing = session.execute(
        select(ThemeObservation).where(
            ThemeObservation.claim_assignment_id == assignment.id,
            ThemeObservation.observation_kind == observation_kind,
            ThemeObservation.evidence_channel == evidence_channel,
            ThemeObservation.derivation_policy_version == derivation_policy_version,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.payload != payload:
            raise FactMaterializationError("observation_idempotency_conflict")
        return existing
    row = ThemeObservation(
        claim_assignment_id=assignment.id,
        observation_kind=observation_kind,
        evidence_channel=evidence_channel,
        derivation_policy_version=derivation_policy_version,
        observed_at=observed_at,
        available_at=available_at,
        payload=payload,
    )
    session.add(row)
    session.flush()
    return row


def materialize_assignment_facts(
    session: Session,
    *,
    classification_attempt_id: UUID,
    evidence_channels: Iterable[str],
    taxonomy_version_id: UUID | None = None,
    detector_policy_version: str = "signals-v1",
) -> MaterializationResult:
    """Idempotently derive immutable observations, constituents, and signals."""

    attempt, packet, lineage = _attempt_context(session, classification_attempt_id)
    version_id = (
        taxonomy_version_id
        or attempt.output_taxonomy_version_id
        or attempt.input_taxonomy_version_id
    )
    channels = tuple(sorted({str(value) for value in evidence_channels if value}))
    assignments = session.scalars(
        select(ClaimAssignment).where(
            ClaimAssignment.classification_attempt_id == attempt.id
        )
    ).all()
    relationships = session.scalars(
        select(EconomicThemeRelationship).where(
            EconomicThemeRelationship.taxonomy_version_id == version_id
        )
    ).all()
    available_at = _as_datetime(
        packet.available_at, fallback=datetime.now(timezone.utc)
    )

    for assignment in assignments:
        parent_ids = sorted(
            {
                row.target_theme_id
                for row in relationships
                if row.kind == "specialization"
                and row.source_theme_id == assignment.economic_theme_id
            },
            key=str,
        )
        related_ids = sorted(
            {
                (
                    row.target_theme_id
                    if row.source_theme_id == assignment.economic_theme_id
                    else row.source_theme_id
                )
                for row in relationships
                if row.discriminator == "related"
                and assignment.economic_theme_id
                in {row.source_theme_id, row.target_theme_id}
            },
            key=str,
        )
        for channel in channels:
            _get_or_create_observation(
                session,
                assignment=assignment,
                observation_kind="primary",
                evidence_channel=channel,
                derivation_policy_version=attempt.derivation_policy_version,
                observed_at=packet.observed_at,
                available_at=available_at,
                payload=_observation_payload(
                    assignment=assignment,
                    target_theme_ids=[assignment.economic_theme_id],
                    packet=packet,
                    source_family_id=lineage.source_family_id,
                    direct_root=True,
                ),
            )
            for observation_kind, targets in (
                ("derived_parent", parent_ids),
                ("derived_related", related_ids),
            ):
                if targets:
                    _get_or_create_observation(
                        session,
                        assignment=assignment,
                        observation_kind=observation_kind,
                        evidence_channel=channel,
                        derivation_policy_version=attempt.derivation_policy_version,
                        observed_at=packet.observed_at,
                        available_at=available_at,
                        payload=_observation_payload(
                            assignment=assignment,
                            target_theme_ids=targets,
                            packet=packet,
                            source_family_id=lineage.source_family_id,
                            direct_root=False,
                        ),
                    )
        _materialize_constituents(
            session,
            assignment=assignment,
            source_family_id=lineage.source_family_id,
            source_lineage_id=packet.source_lineage_id,
            derivation_policy_version=attempt.derivation_policy_version,
        )
        _materialize_signals(
            session,
            assignment=assignment,
            packet=packet,
            source_family_id=lineage.source_family_id,
            detector_policy_version=detector_policy_version,
        )

    primary = session.scalars(
        select(ThemeObservation).where(
            ThemeObservation.claim_assignment_id.in_(
                [assignment.id for assignment in assignments]
            ),
            ThemeObservation.observation_kind == "primary",
        )
    ).all()
    derived = session.scalars(
        select(ThemeObservation).where(
            ThemeObservation.claim_assignment_id.in_(
                [assignment.id for assignment in assignments]
            ),
            ThemeObservation.observation_kind != "primary",
        )
    ).all()
    constituents = session.scalars(
        select(ThemeConstituentExposure).where(
            ThemeConstituentExposure.claim_assignment_id.in_(
                [assignment.id for assignment in assignments]
            )
        )
    ).all()
    signals = session.scalars(
        select(ThemeSignalObservation).where(
            ThemeSignalObservation.claim_assignment_id.in_(
                [assignment.id for assignment in assignments]
            )
        )
    ).all()
    return MaterializationResult(
        primary_observations=len(primary),
        derived_observations=len(derived),
        constituent_exposures=len(constituents),
        signal_observations=len(signals),
    )


def _materialize_constituents(
    session,
    *,
    assignment,
    source_family_id,
    source_lineage_id,
    derivation_policy_version,
):
    for source in assignment.claim_payload.get("securities") or []:
        if not isinstance(source, Mapping):
            continue
        security_id = source.get("security_id")
        if not isinstance(security_id, int) or isinstance(security_id, bool):
            continue
        exposure_kind = str(source.get("role") or "constituent")
        existing = session.execute(
            select(ThemeConstituentExposure).where(
                ThemeConstituentExposure.claim_assignment_id == assignment.id,
                ThemeConstituentExposure.security_id == security_id,
                ThemeConstituentExposure.exposure_kind == exposure_kind,
                ThemeConstituentExposure.derivation_policy_version
                == derivation_policy_version,
            )
        ).scalar_one_or_none()
        payload = {
            "economic_theme_id": str(assignment.economic_theme_id),
            "source_family_id": str(source_family_id),
            "source_lineage_id": str(source_lineage_id),
            "directness": source.get("directness"),
            "rationale": source.get("rationale"),
        }
        if existing is not None:
            if existing.payload != payload:
                raise FactMaterializationError("constituent_idempotency_conflict")
            continue
        confidence = source.get("confidence")
        session.add(
            ThemeConstituentExposure(
                claim_assignment_id=assignment.id,
                security_id=security_id,
                exposure_kind=exposure_kind,
                exposure_strength=(
                    float(confidence) if confidence is not None else None
                ),
                derivation_policy_version=derivation_policy_version,
                payload=payload,
            )
        )
    session.flush()


def _materialize_signals(
    session,
    *,
    assignment,
    packet,
    source_family_id,
    detector_policy_version,
):
    for source in assignment.claim_payload.get("signals") or []:
        if not isinstance(source, Mapping):
            continue
        signal_kind = str(source.get("signal_kind") or "").strip()
        if not signal_kind:
            continue
        security_id = source.get("security_id")
        if isinstance(security_id, bool) or (
            security_id is not None and not isinstance(security_id, int)
        ):
            continue
        policy = str(source.get("detector_policy_version") or detector_policy_version)
        existing = session.execute(
            select(ThemeSignalObservation).where(
                ThemeSignalObservation.claim_assignment_id == assignment.id,
                ThemeSignalObservation.security_id == security_id,
                ThemeSignalObservation.signal_kind == signal_kind,
                ThemeSignalObservation.signal_policy_version == policy,
            )
        ).scalar_one_or_none()
        payload = {
            "economic_theme_id": str(assignment.economic_theme_id),
            "source_family_id": str(source_family_id),
            "source_lineage_id": str(packet.source_lineage_id),
            "evidence_packet_id": str(packet.id),
            "effective_at": _as_datetime(
                source.get("effective_at"), fallback=packet.available_at
            ).isoformat(),
            "normalized_payload": dict(source.get("normalized_payload") or {}),
        }
        if existing is not None:
            if existing.payload != payload:
                raise FactMaterializationError("signal_idempotency_conflict")
            continue
        session.add(
            ThemeSignalObservation(
                claim_assignment_id=assignment.id,
                security_id=security_id,
                signal_kind=signal_kind,
                signal_policy_version=policy,
                observed_at=_as_datetime(
                    source.get("detected_at"),
                    fallback=packet.observed_at or packet.available_at,
                ),
                available_at=_as_datetime(
                    source.get("available_at"), fallback=packet.available_at
                ),
                payload=payload,
            )
        )
    session.flush()


class EconomicThemeObservationService:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def observations_for_generation(self, generation_id: UUID) -> list[ObservationFact]:
        with self.session_factory() as session:
            generation = session.get(ServingGeneration, generation_id)
            if generation is None:
                raise KeyError(f"serving generation {generation_id} not found")
            return self._observations_for_set(
                session,
                generation.interpretation_set_id,
                generation.generation_input_manifest_id,
            )

    @staticmethod
    def _observations_for_set(session, interpretation_set_id, manifest_id):
        facts: list[ObservationFact] = []
        for observation, assignment in observation_rows_for_interpretation(
            session,
            interpretation_set_id=interpretation_set_id,
            manifest_id=manifest_id,
        ):
            target_ids = observation.payload.get("economic_theme_ids") or [
                str(assignment.economic_theme_id)
            ]
            for target_id in target_ids:
                facts.append(
                    ObservationFact(
                        observation_id=observation.id,
                        claim_assignment_id=assignment.id,
                        economic_theme_id=UUID(str(target_id)),
                        observation_kind=observation.observation_kind,
                        evidence_channel=observation.evidence_channel,
                        source_family_id=UUID(observation.payload["source_family_id"]),
                        available_at=_as_datetime(
                            observation.available_at,
                            fallback=datetime.now(timezone.utc),
                        ),
                        payload=dict(observation.payload),
                    )
                )
        return facts
