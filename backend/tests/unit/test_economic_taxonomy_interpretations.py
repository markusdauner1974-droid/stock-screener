from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.database import SessionLocal
from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    ClaimReviewArtifact,
    ClassificationAttempt,
    ClassificationAttemptEvent,
    EvidencePrecedenceRevision,
    ExtractionArtifact,
    GenerationInputManifest,
    InterpretationSelection,
    LensEligibilityRevision,
    TaxonomyAuthority,
    ThemeObservation,
)
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_interpretations import (
    EconomicTaxonomyInterpretationService,
    InvalidInterpretation,
    create_interpretation_override,
)
from app.services.economic_taxonomy_seed import seed_initial_dimensions
from sqlalchemy import func, select

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


def _fixture(db_session):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:author", reason="interpretation fixture")
    seed_initial_dimensions(repo, draft.id, actor="test:author")
    theme = repo.create_theme(
        draft.id,
        display_name="Memory",
        definition="Memory semiconductor exposure.",
        mechanism="Memory supply and demand",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
        actor="test:author",
    )
    sealed = repo.seal_draft(draft.id)
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_taxonomy_version_id=sealed.id,
            processing_head_revision=1,
            authority_epoch=1,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()
    return sealed, theme


def _admit(
    db_session,
    *,
    item="post-1",
    text="Memory demand rose.",
    provider_order=1,
    route="legacy",
    attachments=(),
    supersedes=None,
    source_metadata=None,
):
    return EconomicSourceAdmissionService(db_session).admit_content(
        EvidenceAdmission(
            provider="x",
            canonical_item_id=item,
            capture_route=route,
            original_text=text,
            preparation_version="prep-v1",
            provider_revision_id=(
                f"rev-{provider_order}" if provider_order is not None else None
            ),
            provider_revision_order=provider_order,
            attachment_hashes=attachments,
            extracted_text_hashes=("attachment-text",) if attachments else (),
            source_metadata=source_metadata or {},
            supersedes_packet_id=supersedes,
            captured_at=NOW,
            observed_at=NOW,
            available_at=NOW,
            evidence_channels=("narrative",),
        )
    )


def _attempt(
    db_session, *, admitted, taxonomy_id, theme_id, status="completed", empty=False
):
    work = EconomicTaxonomyWorkRepository(db_session)
    request = work.enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="bundle-v1",
        available_at=NOW,
    )
    extraction = ExtractionArtifact(
        evidence_packet_id=admitted.packet_id,
        extraction_policy_version="extract-v1",
        result_status="successful_empty" if empty else "accepted_candidates",
        result_payload={
            "status": "successful_empty" if empty else "accepted_candidates"
        },
        provider_response_hash="extract-hash",
    )
    db_session.add(extraction)
    db_session.flush()
    review = ClaimReviewArtifact(
        extraction_artifact_id=extraction.id,
        claim_review_policy_version="review-v1",
        facet_catalog_semantic_hash="facet-v1",
        result_status="successful_empty" if empty else "accepted_candidates",
        result_payload={
            "status": "successful_empty" if empty else "accepted_candidates",
            "accepted": [],
            "held": [],
        },
        provider_response_hash="review-hash",
    )
    db_session.add(review)
    db_session.flush()
    attempt = ClassificationAttempt(
        processing_request_id=request.id,
        claim_review_artifact_id=review.id,
        input_taxonomy_version_id=taxonomy_id,
        resolver_policy_version="resolver-v1",
        naming_policy_version="naming-v1",
        derivation_policy_version="derive-v1",
        result_status=status,
        result_payload={"status": "successful_empty" if empty else "classified"},
    )
    db_session.add(attempt)
    db_session.flush()
    db_session.add(
        ClassificationAttemptEvent(
            classification_attempt_id=attempt.id,
            sequence_number=1,
            event_type="completed" if status == "completed" else "failed",
            event_payload={},
        )
    )
    if status == "completed" and not empty:
        db_session.add(
            ClaimAssignment(
                classification_attempt_id=attempt.id,
                claim_fingerprint=f"claim-{attempt.id}",
                economic_theme_id=theme_id,
                exposure_support="direct",
                claim_payload={"securities": [], "signals": []},
                provenance={},
            )
        )
    db_session.commit()
    return attempt


def _entry(db_session, admitted, attempt_id, *, override_id=None):
    precedence = db_session.scalar(
        select(EvidencePrecedenceRevision)
        .where(
            EvidencePrecedenceRevision.source_lineage_id == admitted.source_lineage_id
        )
        .order_by(EvidencePrecedenceRevision.revision_number.desc())
        .limit(1)
    )
    eligibility = db_session.scalar(
        select(LensEligibilityRevision).where(
            LensEligibilityRevision.evidence_packet_id == admitted.packet_id
        )
    )
    return {
        "lineage": str(admitted.source_lineage_id),
        "evidence_packet_id": str(admitted.packet_id),
        "selected_attempt_id": str(attempt_id) if attempt_id else None,
        "eligibility_revision": eligibility.revision_number,
        "evidence_precedence_revision": precedence.revision_number,
        "interpretation_override_revision_id": (
            str(override_id) if override_id else None
        ),
        "constituent_decision_revision": None,
        "social_association_revision": None,
        "social_decision_revision": None,
        "development_revision": None,
        "mapping_revision": 1,
        "metrics_policy_revision": 1,
        "compatibility_projection_revision": 1,
    }


def _manifest(db_session, *entries):
    manifest = GenerationInputManifest(
        status="unsealed",
        expected_parent_generation_id=None,
        semantic_invalidation_revision=0,
        committed_revision_tuples=[],
        selections=list(entries),
        created_by="test:publisher",
    )
    db_session.add(manifest)
    db_session.flush()
    manifest.seal(
        semantic_hash=f"manifest-{manifest.id}", artifact_integrity_hash="artifact"
    )
    db_session.commit()
    return manifest


def _service():
    return EconomicTaxonomyInterpretationService(SessionLocal)


def _set_observation_count(interpretation_set_id):
    with SessionLocal() as session:
        return session.scalar(
            select(func.count())
            .select_from(ThemeObservation)
            .join(
                ClaimAssignment,
                ClaimAssignment.id == ThemeObservation.claim_assignment_id,
            )
            .join(
                InterpretationSelection,
                InterpretationSelection.selected_classification_attempt_id
                == ClaimAssignment.classification_attempt_id,
            )
            .where(
                InterpretationSelection.interpretation_set_id == interpretation_set_id
            )
        )


def test_corrected_to_empty_removes_current_facts_but_preserves_old_set(db_session):
    taxonomy, theme = _fixture(db_session)
    old_packet = _admit(db_session)
    old_attempt = _attempt(
        db_session,
        admitted=old_packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
    )
    old_manifest = _manifest(db_session, _entry(db_session, old_packet, old_attempt.id))

    empty_packet = _admit(
        db_session,
        text="",
        provider_order=2,
        route="social",
        supersedes=old_packet.packet_id,
    )
    empty_attempt = _attempt(
        db_session,
        admitted=empty_packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
        empty=True,
    )
    new_manifest = _manifest(
        db_session, _entry(db_session, empty_packet, empty_attempt.id)
    )
    first = _service().build_interpretation_set(old_manifest.id)
    second = _service().build_interpretation_set(new_manifest.id)

    assert _set_observation_count(first.id) == 1
    assert _set_observation_count(second.id) == 0


def test_failed_attempt_cannot_replace_selected_attempt(db_session):
    taxonomy, theme = _fixture(db_session)
    packet = _admit(db_session)
    failed = _attempt(
        db_session,
        admitted=packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
        status="failed",
    )
    manifest = _manifest(db_session, _entry(db_session, packet, failed.id))

    with pytest.raises(InvalidInterpretation, match="attempt_not_completed"):
        _service().build_interpretation_set(manifest.id)


def test_delayed_older_provider_revision_cannot_replace_newer(db_session):
    taxonomy, theme = _fixture(db_session)
    current_packet = _admit(db_session, provider_order=5)
    current = _attempt(
        db_session,
        admitted=current_packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
        empty=True,
    )
    delayed_packet = _admit(
        db_session,
        text="Old memory story.",
        provider_order=4,
        route="archive",
    )
    delayed = _attempt(
        db_session,
        admitted=delayed_packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
    )

    selected = _service().choose_default(current_packet.source_lineage_id)

    assert selected.id == current.id
    assert selected.id != delayed.id


def test_late_archive_and_partial_recapture_cannot_displace_effective_packet(
    db_session,
):
    taxonomy, theme = _fixture(db_session)
    original = _admit(db_session, attachments=("attachment-1",))
    accepted = _attempt(
        db_session,
        admitted=original,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
    )
    partial = _admit(
        db_session,
        text="Partial text only.",
        provider_order=None,
        route="archive",
        attachments=(),
        source_metadata={"archived": True},
    )
    _attempt(
        db_session,
        admitted=partial,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
        empty=True,
    )

    selected = _service().choose_default(original.source_lineage_id)

    assert partial.precedence_state == "hold_review"
    assert selected.id == accepted.id


def test_authenticated_override_can_pin_older_completed_interpretation(db_session):
    taxonomy, theme = _fixture(db_session)
    older_packet = _admit(db_session, provider_order=1)
    older = _attempt(
        db_session,
        admitted=older_packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
    )
    newer_packet = _admit(
        db_session,
        text="Corrected memory story.",
        provider_order=2,
        supersedes=older_packet.packet_id,
    )
    _attempt(
        db_session,
        admitted=newer_packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
        empty=True,
    )
    principal = AdminPrincipal(
        subject="admin:reviewer",
        auth_method="admin_api_key",
        roles=frozenset({"taxonomy:review"}),
    )
    override = create_interpretation_override(
        db_session,
        source_lineage_id=older_packet.source_lineage_id,
        selected_attempt_id=older.id,
        reason="Reviewed source correction",
        principal=principal,
    )
    db_session.commit()
    manifest = _manifest(
        db_session,
        _entry(db_session, older_packet, older.id, override_id=override.id),
    )

    built = _service().build_interpretation_set(manifest.id)

    with SessionLocal() as session:
        selection = session.scalar(
            select(InterpretationSelection).where(
                InterpretationSelection.interpretation_set_id == built.id
            )
        )
        assert selection.selected_classification_attempt_id == older.id
        assert selection.interpretation_override_revision_id == override.id


def test_same_manifest_is_idempotent(db_session):
    taxonomy, theme = _fixture(db_session)
    packet = _admit(db_session)
    attempt = _attempt(
        db_session,
        admitted=packet,
        taxonomy_id=taxonomy.id,
        theme_id=theme.id,
    )
    manifest = _manifest(db_session, _entry(db_session, packet, attempt.id))

    first = _service().build_interpretation_set(manifest.id)
    second = _service().build_interpretation_set(manifest.id)

    assert first.id == second.id
    with SessionLocal() as session:
        assert (
            session.scalar(select(func.count()).select_from(InterpretationSelection))
            == 1
        )
