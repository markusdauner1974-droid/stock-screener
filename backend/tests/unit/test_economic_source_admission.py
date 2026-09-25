from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.economic_taxonomy_runtime import (
    EvidencePacket,
    LensEligibilityRevision,
    ProcessingRequest,
    TaxonomySourceRevisionLog,
)
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


def _post(
    *,
    route: str = "legacy",
    text: str = "Memory demand is accelerating.",
    provider_revision_id: str | None = "rev-1",
    provider_revision_order: int | None = 1,
    attachment_hashes: tuple[str, ...] = ("attachment-1",),
    evidence_channels: tuple[str, ...] = ("narrative",),
    captured_at: datetime = NOW,
    supersedes_packet_id=None,
) -> EvidenceAdmission:
    return EvidenceAdmission(
        provider="x",
        canonical_item_id="post-42",
        route_record_id=f"{route}-row-42",
        capture_route=route,
        original_text=text,
        translated_text="Translated memory demand.",
        translation_version="translation-v1",
        attachment_hashes=attachment_hashes,
        extracted_text_hashes=("attachment-text-1",) if attachment_hashes else (),
        grounding_snapshot={"companies": [{"symbol": "MU", "security_id": 42}]},
        preparation_version="prep-v1",
        source_metadata={"author": "analyst"},
        provider_revision_id=provider_revision_id,
        provider_revision_order=provider_revision_order,
        captured_at=captured_at,
        observed_at=NOW,
        available_at=NOW,
        evidence_channels=evidence_channels,
        supersedes_packet_id=supersedes_packet_id,
    )


def test_same_provider_post_from_legacy_and_social_shares_family(db_session):
    admission = EconomicSourceAdmissionService(db_session)

    legacy = admission.admit_content(_post())
    social = admission.admit_social_work(_post(route="social"))

    assert legacy.source_family_id == social.source_family_id
    assert legacy.source_lineage_id == social.source_lineage_id
    assert social.precedence_state == "equivalent"
    assert social.effective_packet_id == legacy.effective_packet_id == legacy.packet_id
    assert social.packet_id != legacy.packet_id


def test_adding_lens_does_not_create_packet_or_work(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    admitted = admission.admit_content(_post())
    packet_count = db_session.scalar(select(func.count()).select_from(EvidencePacket))

    revised = admission.revise_lens_eligibility(
        admitted.packet_id,
        add="fundamental",
        reason="now eligible for fundamentals",
    )

    assert revised.packet_id == admitted.packet_id
    assert revised.evidence_channels == ("fundamental", "narrative")
    assert revised.enqueued_request_id is None
    assert (
        db_session.scalar(select(func.count()).select_from(EvidencePacket))
        == packet_count
    )
    assert db_session.scalar(select(func.count()).select_from(ProcessingRequest)) == 0
    assert (
        db_session.scalar(select(func.count()).select_from(LensEligibilityRevision))
        == 2
    )
    publication_revision = db_session.scalar(
        select(TaxonomySourceRevisionLog).where(
            TaxonomySourceRevisionLog.logical_source_key
            == f"evidence_packet:{admitted.packet_id}",
            TaxonomySourceRevisionLog.revision_kind == "lens_eligibility",
        )
    )
    assert publication_revision is not None
    assert publication_revision.revision_number == revised.revision_number


def test_readmitting_same_packet_merges_new_lens_without_new_packet(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    first = admission.admit_content(_post(evidence_channels=("technical",)))

    repeated = admission.admit_content(
        _post(evidence_channels=("technical", "fundamental"))
    )
    latest = db_session.scalar(
        select(LensEligibilityRevision)
        .where(LensEligibilityRevision.evidence_packet_id == first.packet_id)
        .order_by(LensEligibilityRevision.revision_number.desc())
        .limit(1)
    )

    assert repeated.packet_id == first.packet_id
    assert latest.evidence_channels == ["fundamental", "technical"]
    assert db_session.scalar(select(func.count()).select_from(EvidencePacket)) == 1


def test_packet_hash_excludes_lens_but_frozen_inputs_remain_reproducible(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    first = admission.admit_content(_post(evidence_channels=("technical",)))
    first_packet = db_session.get(EvidencePacket, first.packet_id)
    frozen_translation = first_packet.translated_text_ref
    frozen_grounding = dict(first_packet.grounding_snapshot)

    equivalent = admission.admit_social_work(
        _post(route="social", evidence_channels=("fundamental", "narrative"))
    )

    assert equivalent.evidence_content_fingerprint == first.evidence_content_fingerprint
    assert (
        db_session.get(EvidencePacket, first.packet_id).translated_text_ref
        == frozen_translation
    )
    assert (
        db_session.get(EvidencePacket, first.packet_id).grounding_snapshot
        == frozen_grounding
    )
    effective_eligibility = db_session.scalar(
        select(LensEligibilityRevision)
        .where(LensEligibilityRevision.evidence_packet_id == first.packet_id)
        .order_by(LensEligibilityRevision.revision_number.desc())
        .limit(1)
    )
    assert effective_eligibility.evidence_channels == [
        "fundamental",
        "narrative",
        "technical",
    ]


def test_delayed_packet_keeps_admission_order_without_claiming_freshness(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    old = admission.admit_content(_post(provider_revision_order=1))
    correction = admission.admit_content(
        _post(
            text="",
            provider_revision_id="rev-2",
            provider_revision_order=2,
            attachment_hashes=(),
            captured_at=NOW + timedelta(minutes=1),
        )
    )

    assert old.evidence_revision_ordinal < correction.evidence_revision_ordinal
    assert correction.precedence_state == "effective"
    assert admission.effective_packet(old.source_lineage_id).id == correction.packet_id


def test_first_admitted_late_archive_does_not_restore_corrected_empty(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    original = admission.admit_content(_post(provider_revision_order=1))
    corrected_empty = admission.admit_content(
        _post(
            text="",
            provider_revision_id="rev-2",
            provider_revision_order=2,
            attachment_hashes=(),
            supersedes_packet_id=original.packet_id,
        )
    )
    late = admission.admit_social_work(
        _post(
            route="social",
            text="Memory demand is accelerating.",
            provider_revision_id=None,
            provider_revision_order=None,
            attachment_hashes=(),
            captured_at=NOW + timedelta(days=1),
        )
    )

    assert late.evidence_revision_ordinal > corrected_empty.evidence_revision_ordinal
    assert late.precedence_state == "hold_review"
    assert (
        admission.effective_packet(corrected_empty.source_lineage_id).id
        == corrected_empty.packet_id
    )


def test_less_complete_recapture_does_not_withdraw_attachment_evidence(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    complete = admission.admit_content(_post())
    partial = admission.admit_content(
        _post(
            text="Same textual claim",
            provider_revision_id=None,
            provider_revision_order=None,
            attachment_hashes=(),
            captured_at=NOW + timedelta(hours=1),
        )
    )

    assert partial.precedence_state == "hold_review"
    assert (
        admission.effective_packet(complete.source_lineage_id).id == complete.packet_id
    )
