from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.economic_taxonomy_runtime import (
    EvidencePacket,
    LensEligibilityRevision,
    ProcessingRequest,
    TaxonomySourceRevisionLog,
)
from app.services.economic_source_admission import (
    CONTENT_INGESTION_ROUTE,
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


def test_content_recapture_of_admitted_text_reuses_the_packet(db_session):
    # Ingestion re-polls the same item with a new capture time each run.
    admission = EconomicSourceAdmissionService(db_session)
    unordered = {"provider_revision_id": None, "provider_revision_order": None}
    first = admission.admit_content(_post(**unordered))

    recapture = admission.admit_content(
        _post(captured_at=NOW + timedelta(hours=1), **unordered)
    )

    assert recapture.packet_id == first.packet_id
    assert db_session.scalar(select(func.count()).select_from(EvidencePacket)) == 1


def test_capture_matching_only_a_held_packet_still_reaches_precedence(db_session):
    # A late archive is held when it is the first packet; a normal capture of
    # the same text must still become effective instead of reusing it.
    admission = EconomicSourceAdmissionService(db_session)
    unordered = {"provider_revision_id": None, "provider_revision_order": None}
    archived = admission.admit_content(_post(route="archive", **unordered))
    assert archived.precedence_state == "hold_review"

    captured = admission.admit_content(_post(**unordered))

    assert captured.packet_id != archived.packet_id
    assert captured.precedence_state == "effective"


def test_recapture_reuses_the_effective_packet_not_a_held_archive(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    unordered = {"provider_revision_id": None, "provider_revision_order": None}
    admission.admit_content(_post(route="archive", **unordered))
    captured = admission.admit_content(_post(**unordered))

    recapture = admission.admit_content(
        _post(captured_at=NOW + timedelta(hours=1), **unordered)
    )

    assert recapture.packet_id == captured.packet_id
    assert recapture.precedence_state == "effective"


def test_recapture_does_not_reuse_a_packet_no_longer_in_force(db_session):
    # A was effective, then B advanced; an unordered capture of A is a possible
    # reversion and must reach precedence, not reuse A's stale packet.
    admission = EconomicSourceAdmissionService(db_session)
    first = admission.admit_content(_post(provider_revision_order=1))
    advanced = admission.admit_content(
        _post(text="Memory demand is slowing.", provider_revision_id="rev-2",
              provider_revision_order=2)
    )

    recapture = admission.admit_content(
        _post(provider_revision_id=None, provider_revision_order=None,
              captured_at=NOW + timedelta(hours=1))
    )

    assert recapture.packet_id != first.packet_id
    assert recapture.precedence_state == "hold_review"
    assert admission.effective_packet(first.source_lineage_id).id == advanced.packet_id


def test_ordered_reversion_to_earlier_text_is_admitted_not_collapsed(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    first = admission.admit_content(_post(provider_revision_order=1))
    admission.admit_content(
        _post(text="Memory demand is slowing.", provider_revision_id="rev-2",
              provider_revision_order=2)
    )

    reverted = admission.admit_content(
        _post(provider_revision_id="rev-3", provider_revision_order=3)
    )

    assert reverted.packet_id != first.packet_id
    assert reverted.precedence_state == "effective"
    assert admission.effective_packet(first.source_lineage_id).id == reverted.packet_id


def _x_capture(route: str, text: str, record: str) -> EvidenceAdmission:
    # Legacy X content and Social prepare the same post differently, so their
    # content fingerprints never match (#500).
    return EvidenceAdmission(
        provider="x",
        canonical_source_family="x:post:123",
        capture_route=route,
        route_record_id=record,
        original_text=text,
        preparation_version=f"{route}-v1",
        captured_at=NOW,
        observed_at=NOW,
        available_at=NOW,
        evidence_channels=("narrative",),
    )


def test_social_supersedes_a_content_ingestion_packet_for_the_same_post(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    content = admission.admit_content(_x_capture(CONTENT_INGESTION_ROUTE, "Memory demand.", "7:3"))

    social = admission.admit_social_work(_x_capture("social", "Memory demand.", "work-9"))
    again = admission.admit_social_work(_x_capture("social", "Memory demand.", "work-9"))

    assert social.source_lineage_id == content.source_lineage_id
    assert social.precedence_state == "effective"
    assert db_session.get(EvidencePacket, social.packet_id).supersedes_evidence_packet_id == content.packet_id
    assert again.packet_id == social.packet_id
    assert db_session.scalar(select(func.count()).select_from(EvidencePacket)) == 2


def test_social_recapture_after_superseding_content_is_equivalent(db_session):
    # New Social metadata (e.g. a membership decision) still needs its own
    # equivalent packet once Social has taken over from legacy X content.
    admission = EconomicSourceAdmissionService(db_session)
    admission.admit_content(_x_capture(CONTENT_INGESTION_ROUTE, "Memory demand.", "7:3"))
    social = admission.admit_social_work(_x_capture("social", "Memory demand.", "work-9"))

    recapture = admission.admit_social_work(
        replace(_x_capture("social", "Memory demand.", "work-9"),
                source_metadata={"social_memberships": ["rejected"]})
    )

    assert recapture.packet_id != social.packet_id
    assert recapture.precedence_state == "equivalent"
    assert db_session.get(EvidencePacket, recapture.packet_id).supersedes_evidence_packet_id is None


def _lens(db_session, packet_id):
    latest = db_session.scalars(
        select(LensEligibilityRevision)
        .where(LensEligibilityRevision.evidence_packet_id == packet_id)
        .order_by(LensEligibilityRevision.revision_number.desc())
    ).first()
    return set(latest.evidence_channels)


def test_social_supersession_keeps_the_legacy_x_lens(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    admission.admit_content(replace(
        _x_capture(CONTENT_INGESTION_ROUTE, "Memory demand.", "7:3"),
        evidence_channels=("technical",),
    ))

    social = admission.admit_social_work(_x_capture("social", "Memory demand.", "work-9"))

    assert _lens(db_session, social.packet_id) == {"narrative", "technical"}


def test_legacy_x_lens_reaches_social_packet_admitted_first(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    social = admission.admit_social_work(_x_capture("social", "Memory demand.", "work-9"))

    admission.admit_content(replace(
        _x_capture(CONTENT_INGESTION_ROUTE, "Memory demand.", "7:3"),
        evidence_channels=("technical",),
    ))

    assert _lens(db_session, social.packet_id) == {"narrative", "technical"}


def test_pipeline_added_to_a_legacy_x_source_reaches_the_social_packet(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    admission.admit_content(_x_capture(CONTENT_INGESTION_ROUTE, "Memory demand.", "7:3"))
    social = admission.admit_social_work(_x_capture("social", "Memory demand.", "work-9"))

    added = admission.add_observation_channels(
        family_key="x:post:123", capture_route=CONTENT_INGESTION_ROUTE,
        route_record_id="7:3", channels={"fundamental"}, reason="source_pipeline_added",
    )

    assert added is True
    assert "fundamental" in _lens(db_session, social.packet_id)


def test_content_capture_after_social_is_held_once(db_session):
    admission = EconomicSourceAdmissionService(db_session)
    social = admission.admit_social_work(_x_capture("social", "Memory demand.", "work-9"))

    held = admission.admit_content(_x_capture(CONTENT_INGESTION_ROUTE, "Memory demand.", "7:3"))
    repoll = admission.admit_content(_x_capture(CONTENT_INGESTION_ROUTE, "Memory demand.", "7:3"))

    assert held.precedence_state == "hold_review"
    assert repoll.packet_id == held.packet_id
    assert admission.effective_packet(social.source_lineage_id).id == social.packet_id


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
