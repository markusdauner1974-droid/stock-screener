from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app.database import SessionLocal
from app.infra.db.models.social_analysis import (
    EconomicSocialAssociation,
    EconomicSocialAssociationRevision,
    EconomicSocialAssociationSource,
    SocialExtractionWork,
)
from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy import (
    EconomicTheme,
    EconomicThemeAlias,
    EconomicThemeFacet,
    TaxonomyVersion,
)
from app.models.economic_taxonomy_runtime import (
    ClaimAssignment,
    ClaimReviewArtifact,
    ClassificationAttempt,
    ClassificationAttemptEvent,
    ExtractionArtifact,
    ProviderAttempt,
    ProviderAttemptEvent,
    TaxonomyAuthority,
    TaxonomySourceRevisionLog,
)
from app.models.stock_universe import StockUniverse
from app.models.theme import ContentItem
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_processor import (
    EconomicTaxonomyProcessor,
    ProviderResultUnavailable,
)
from app.services.economic_taxonomy_seed import seed_initial_dimensions
from sqlalchemy import func, select

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


class CrashAfterCommit:
    def __init__(self):
        self.raised = False

    def after(self, point: str):
        if point == "processing_head_commit" and not self.raised:
            self.raised = True
            raise RuntimeError("injected crash")


class AdvanceHeadAfterResolution:
    def __init__(self):
        self.advanced = False

    def after(self, point: str):
        if point != "resolution_complete" or self.advanced:
            return
        self.advanced = True
        with SessionLocal.begin() as session:
            authority = session.get(TaxonomyAuthority, 1)
            repo = EconomicTaxonomyRepository(session)
            draft = repo.clone_draft(
                authority.processing_taxonomy_version_id,
                actor="test:concurrent-writer",
                reason="advance while resolution is in flight",
            )
            memory_theme_id = session.scalar(
                select(EconomicTheme.id).order_by(EconomicTheme.created_at)
            )
            repo.add_alias(
                draft.id,
                memory_theme_id,
                "DRAM",
                actor="test:concurrent-writer",
            )
            sealed = repo.seal_draft(draft.id)
            authority.processing_taxonomy_version_id = sealed.id
            authority.processing_head_revision += 1


def _seed_head(db_session, *, with_memory: bool):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:author", reason="processor fixture")
    seed_initial_dimensions(repo, draft.id, actor="test:author")
    memory = None
    if with_memory:
        memory = repo.create_theme(
            draft.id,
            display_name="Memory",
            definition="Memory semiconductor exposure.",
            mechanism="Memory supply and demand",
            lifecycle="established",
            lifecycle_policy_version="lifecycle-v1",
            actor="test:author",
        )
        repo.assign_facet(
            draft.id,
            memory.id,
            "industry",
            "memory_semiconductors",
            actor="test:author",
        )
    sealed = repo.seal_draft(draft.id)
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_taxonomy_version_id=sealed.id,
            processing_head_revision=10,
            authority_epoch=3,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.commit()
    return sealed, memory


def _leased_request(db_session, *, item: str):
    admitted = EconomicSourceAdmissionService(db_session).admit_content(
        EvidenceAdmission(
            provider="x",
            canonical_item_id=item,
            capture_route="legacy",
            original_text="HBM demand rose.",
            preparation_version="prep-v1",
            captured_at=NOW,
            available_at=NOW,
        )
    )
    work = EconomicTaxonomyWorkRepository(db_session)
    work.enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="bundle-v1",
        available_at=NOW,
    )
    db_session.commit()
    leased = work.claim_next(worker_id=f"worker:{item}", now=NOW)
    db_session.commit()
    return leased


def _reviewed(
    db_session,
    request,
    candidate=None,
    *,
    candidates=None,
    status="accepted_candidates",
):
    accepted = (
        list(candidates)
        if candidates is not None
        else ([] if candidate is None else [candidate])
    )
    authority = db_session.get(TaxonomyAuthority, 1)
    facet_hash = EconomicTaxonomyRepository(db_session).facet_catalog_semantic_hash(
        authority.processing_taxonomy_version_id
    )
    extraction = ExtractionArtifact(
        evidence_packet_id=request.evidence_packet_id,
        extraction_policy_version="extract-v1",
        result_status=status,
        result_payload={"status": status, "candidates": accepted},
        provider_response_hash="extract-hash",
    )
    db_session.add(extraction)
    db_session.flush()
    review = ClaimReviewArtifact(
        extraction_artifact_id=extraction.id,
        claim_review_policy_version="review-v1",
        facet_catalog_semantic_hash=facet_hash,
        result_status=status,
        result_payload={"status": status, "accepted": accepted, "held": []},
        provider_response_hash="review-hash",
    )
    db_session.add(review)
    db_session.commit()
    return review


def _candidate(name="HBM", facets=None):
    return {
        "candidate_key": name.casefold().replace(" ", "-"),
        "display_name": name,
        "raw_facets": facets or {"product": "HBM"},
        "mechanism": "Demand changes memory economics.",
        "evidence_spans": ["HBM demand rose."],
        "relationship_evidence": [],
        "exposure_support": "direct",
        "development_support": "present",
        "candidate_kind": "economic_exposure",
        "securities": [],
        "unknown_dimensions": [],
        "review_reasons": [],
    }


def _processor(*, fault=None):
    return EconomicTaxonomyProcessor(
        SessionLocal,
        resolver_policy_version="resolver-v1",
        naming_policy_version="naming-v1",
        derivation_policy_version="derive-v1",
        lifecycle_policy_version="lifecycle-v1",
        fault_injector=fault,
    )


def test_retry_after_processing_head_commit_reuses_identity(db_session):
    _seed_head(db_session, with_memory=False)
    request = _leased_request(db_session, item="crash-post")
    _reviewed(db_session, request, _candidate())
    fault = CrashAfterCommit()
    processor = _processor(fault=fault)

    with pytest.raises(RuntimeError, match="injected crash"):
        processor.process(request.id, request.lease_token)
    retried = processor.process(request.id, request.lease_token)

    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(EconomicTheme)) == 1
        assert (
            session.scalar(select(func.count()).select_from(ClassificationAttempt)) == 1
        )
        assert session.scalar(select(func.count()).select_from(ClaimAssignment)) == 1
        assert (
            session.scalar(select(func.count()).select_from(TaxonomySourceRevisionLog))
            == 1
        )
    assert retried.created_identity_count == 0
    assert retried.classification_attempt_count == 1
    assert retried.reused is True


def test_existing_identity_observation_does_not_advance_head(db_session):
    original, memory = _seed_head(db_session, with_memory=True)
    request = _leased_request(db_session, item="memory-post")
    _reviewed(db_session, request, _candidate("Memory", {"industry": "Memory"}))

    result = _processor().process(request.id, request.lease_token)

    with SessionLocal() as session:
        authority = session.get(TaxonomyAuthority, 1)
        assignment = session.scalar(select(ClaimAssignment))
        assert authority.processing_head_revision == 10
        assert authority.processing_taxonomy_version_id == original.id
        assert assignment.economic_theme_id == memory.id
    assert result.output_taxonomy_version_id is None
    assert result.created_identity_count == 0


def test_stale_head_attempt_is_retained_and_artifacts_are_reused(db_session):
    _seed_head(db_session, with_memory=True)
    request = _leased_request(db_session, item="stale-post")
    review = _reviewed(
        db_session,
        request,
        _candidate("Memory", {"industry": "Memory"}),
    )

    result = _processor(fault=AdvanceHeadAfterResolution()).process(
        request.id, request.lease_token
    )

    with SessionLocal() as session:
        attempts = session.scalars(
            select(ClassificationAttempt).order_by(ClassificationAttempt.created_at)
        ).all()
        assert [row.result_status for row in attempts] == [
            "superseded_before_acceptance",
            "completed",
        ]
        assert {row.claim_review_artifact_id for row in attempts} == {review.id}
        assert len({row.input_taxonomy_version_id for row in attempts}) == 2
        assert session.get(TaxonomyAuthority, 1).processing_head_revision == 11
    assert result.classification_attempt_count == 2
    assert result.output_taxonomy_version_id is None


def test_head_advanced_after_claim_reconstructs_the_observed_input(db_session):
    _seed_head(db_session, with_memory=True)
    request = _leased_request(db_session, item="pre-advanced-post")
    review = _reviewed(
        db_session,
        request,
        _candidate("Memory", {"industry": "Memory"}),
    )
    AdvanceHeadAfterResolution().after("resolution_complete")

    result = _processor().process(request.id, request.lease_token)

    with SessionLocal() as session:
        attempts = session.scalars(
            select(ClassificationAttempt).order_by(ClassificationAttempt.created_at)
        ).all()
        assert [row.result_status for row in attempts] == [
            "superseded_before_acceptance",
            "completed",
        ]
        assert {row.claim_review_artifact_id for row in attempts} == {review.id}
        assert len({row.input_taxonomy_version_id for row in attempts}) == 2
    assert result.classification_attempt_count == 2


def test_supported_alias_and_facet_change_publish_without_new_identity(db_session):
    _seed_head(db_session, with_memory=True)
    request = _leased_request(db_session, item="semantic-enrichment-post")
    _reviewed(
        db_session,
        request,
        _candidate("DRAM", {"industry": "Memory", "geography": "US"}),
    )

    result = _processor().process(request.id, request.lease_token)

    with SessionLocal() as session:
        authority = session.get(TaxonomyAuthority, 1)
        aliases = session.scalars(
            select(EconomicThemeAlias.alias).where(
                EconomicThemeAlias.taxonomy_version_id
                == authority.processing_taxonomy_version_id
            )
        ).all()
        facets = session.execute(
            select(
                EconomicThemeFacet.dimension_key,
                EconomicThemeFacet.normalized_value,
            ).where(
                EconomicThemeFacet.taxonomy_version_id
                == authority.processing_taxonomy_version_id
            )
        ).all()
        assert authority.processing_head_revision == 11
        assert aliases == ["DRAM"]
        assert ("geography", "us") in facets
        assert session.scalar(select(func.count()).select_from(EconomicTheme)) == 1
    assert result.output_taxonomy_version_id is not None
    assert result.created_identity_count == 0


def test_multiple_new_themes_from_one_source_publish_one_version(db_session):
    _seed_head(db_session, with_memory=False)
    request = _leased_request(db_session, item="multi-post")
    _reviewed(
        db_session,
        request,
        candidates=[
            _candidate(),
            _candidate("Artificial Intelligence", {"technology": "AI"}),
        ],
    )

    result = _processor().process(request.id, request.lease_token)

    with SessionLocal() as session:
        authority = session.get(TaxonomyAuthority, 1)
        assert authority.processing_head_revision == 11
        assert session.scalar(select(func.count()).select_from(TaxonomyVersion)) == 2
        assert session.scalar(select(func.count()).select_from(EconomicTheme)) == 2
        assert session.scalar(select(func.count()).select_from(ClaimAssignment)) == 2
    assert result.output_taxonomy_version_id is not None
    assert result.created_identity_count == 2


def test_uncertain_provider_attempt_without_artifact_cannot_classify(db_session):
    _seed_head(db_session, with_memory=False)
    request = _leased_request(db_session, item="uncertain-post")
    attempt = ProviderAttempt(
        logical_request_id=request.id,
        operation_kind="extract",
        attempt_number=1,
        dispatch_id="dispatch-1",
    )
    db_session.add(attempt)
    db_session.flush()
    db_session.add(
        ProviderAttemptEvent(
            provider_attempt_id=attempt.id,
            sequence_number=1,
            outcome="uncertain",
            event_payload={},
        )
    )
    db_session.commit()

    with pytest.raises(ProviderResultUnavailable):
        _processor().process(request.id, request.lease_token)

    assert (
        db_session.scalar(select(func.count()).select_from(ClassificationAttempt)) == 0
    )


def test_successful_empty_completes_without_assignment_or_head_change(db_session):
    original, _memory = _seed_head(db_session, with_memory=False)
    request = _leased_request(db_session, item="empty-post")
    _reviewed(db_session, request, status="successful_empty")

    result = _processor().process(request.id, request.lease_token)

    with SessionLocal() as session:
        authority = session.get(TaxonomyAuthority, 1)
        event_types = session.scalars(
            select(ClassificationAttemptEvent.event_type).order_by(
                ClassificationAttemptEvent.sequence_number
            )
        ).all()
        assert authority.processing_taxonomy_version_id == original.id
        assert authority.processing_head_revision == 10
        assert session.scalar(select(func.count()).select_from(ClaimAssignment)) == 0
        assert event_types == ["started", "completed"]
    assert result.output_taxonomy_version_id is None


def test_economic_mode_social_assignment_creates_global_membership(db_session):
    _seed_head(db_session, with_memory=True)
    authority = db_session.get(TaxonomyAuthority, 1)
    authority.mode = "economic"
    security = StockUniverse(symbol="MU", market="US", is_active=True)
    item = ContentItem(
        source_type="twitter",
        external_id="economic-social-post",
        content="Memory pricing rose.",
        published_at=NOW,
    )
    db_session.add_all([security, item])
    db_session.flush()
    work = SocialExtractionWork(
        content_item_id=item.id,
        input_hash="economic-social-input",
        prompt_version="social-v1",
        schema_version="social-v1",
        selected_model="synthetic/model",
        input_snapshot_json={},
        result_json={"status": "accepted_candidates"},
        state="succeeded",
    )
    db_session.add(work)
    db_session.flush()
    admitted = EconomicSourceAdmissionService(db_session).admit_social_work(
        EvidenceAdmission(
            provider="x",
            canonical_item_id="economic-social-post",
            capture_route="social",
            original_text="Memory pricing rose.",
            preparation_version="social-prep-v1",
            captured_at=NOW,
            available_at=NOW,
            evidence_channels=("narrative",),
            source_metadata={
                "social_work_id": work.id,
                "social_memberships": [
                    {
                        "theme_key": "memory",
                        "security_id": security.id,
                        "state": "accepted",
                    }
                ],
            },
        )
    )
    request = EconomicTaxonomyWorkRepository(db_session).enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="bundle-v1",
        available_at=NOW,
    )
    db_session.commit()
    request = EconomicTaxonomyWorkRepository(db_session).claim_next(
        worker_id="worker:economic-social", now=NOW
    )
    db_session.commit()
    candidate = _candidate("Memory", {"industry": "Memory"})
    candidate["securities"] = [{"security_id": security.id, "symbol": "MU"}]
    _reviewed(db_session, request, candidate)
    lease_token = request.lease_token

    processor = _processor()
    processor.process(request.id, lease_token)
    assert processor.process(request.id, lease_token).reused is True

    with SessionLocal() as session:
        association = session.scalar(select(EconomicSocialAssociation))
        revision = session.scalar(select(EconomicSocialAssociationRevision))
        source = session.scalar(select(EconomicSocialAssociationSource))
        assert association.security_id == security.id
        assert revision.state == "pending_legacy_mirror"
        assert revision.live is False
        assert revision.evidence_packet_id == admitted.packet_id
        assert source.social_work_id == work.id
        assert source.evidence_packet_id == admitted.packet_id
        assert session.scalar(
            select(func.count()).select_from(EconomicSocialAssociationRevision)
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(TaxonomySourceRevisionLog)
            .where(TaxonomySourceRevisionLog.producer_kind == "economic_social")
        ) == 1
