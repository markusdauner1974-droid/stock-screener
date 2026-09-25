from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy_runtime import (
    DimensionProposal,
    EconomicExposureCandidate,
    NamingProposal,
    ProcessingRequestEvent,
    ProviderAttempt,
    ProviderAttemptEvent,
    TaxonomyAuthority,
)
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_fence import StaleAuthorityEpoch

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


def _request(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_head_revision=4,
            authority_epoch=7,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.flush()
    admitted = EconomicSourceAdmissionService(db_session).admit_content(
        EvidenceAdmission(
            provider="x",
            canonical_item_id="post-work",
            capture_route="legacy",
            original_text="Memory demand is accelerating.",
            preparation_version="prep-v1",
            captured_at=NOW,
            available_at=NOW,
        )
    )
    return EconomicTaxonomyWorkRepository(db_session).enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="bundle-v1",
        available_at=NOW,
    )


def test_enqueue_is_idempotent_and_claim_pins_head_and_epoch(db_session):
    request = _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)
    duplicate = repo.enqueue_request(
        source_lineage_id=request.source_lineage_id,
        evidence_packet_id=request.evidence_packet_id,
        policy_bundle_version=request.policy_bundle_version,
    )

    claimed = repo.claim_next(worker_id="worker-1", now=NOW)

    assert duplicate.id == request.id
    assert claimed.id == request.id
    assert claimed.lease_token is not None
    assert claimed.observed_processing_head_revision == 4
    assert claimed.observed_authority_epoch == 7
    assert claimed.status == "leased"


def test_retryable_provider_work_gets_new_attempt_identity(db_session):
    request = _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)

    first = repo.begin_provider_attempt(
        request.id, operation="extract", dispatch_id="dispatch-1"
    )
    repo.fail_attempt(first.id, outcome="retryable_failure")
    second = repo.begin_provider_attempt(
        request.id, operation="extract", dispatch_id="dispatch-2"
    )

    assert second.logical_request_id == first.logical_request_id
    assert second.attempt_number == first.attempt_number + 1
    assert first.outcome == "retryable_failure"


def test_same_provider_dispatch_is_idempotent(db_session):
    request = _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)

    first = repo.begin_provider_attempt(
        request.id, operation="review", dispatch_id="stable-dispatch"
    )
    repeated = repo.begin_provider_attempt(
        request.id, operation="review", dispatch_id="stable-dispatch"
    )

    assert repeated.id == first.id
    assert db_session.scalar(select(func.count()).select_from(ProviderAttempt)) == 1


def test_provider_attempt_result_is_an_append_only_event(db_session):
    request = _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)
    attempt = repo.begin_provider_attempt(
        request.id, operation="extract", dispatch_id="dispatch-1"
    )

    failed = repo.fail_attempt(attempt.id, outcome="retryable_failure")

    assert attempt.outcome == "retryable_failure"
    assert failed.provider_attempt_id == attempt.id
    assert (
        db_session.scalar(select(func.count()).select_from(ProviderAttemptEvent)) == 1
    )


def test_database_rejects_success_without_result_artifact(db_session):
    request = _request(db_session)
    attempt = EconomicTaxonomyWorkRepository(db_session).begin_provider_attempt(
        request.id, operation="extract", dispatch_id="dispatch-1"
    )
    db_session.add(
        ProviderAttemptEvent(
            provider_attempt_id=attempt.id,
            sequence_number=1,
            outcome="success",
            result_artifact_id=None,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_database_rejects_lease_without_token_owner_and_expiry(db_session):
    request = _request(db_session)
    request.status = "leased"

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_stale_processing_head_requeues_same_stable_request(db_session):
    _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)
    claimed = repo.claim_next(worker_id="worker-1", now=NOW)
    classification_attempt_id = uuid4()
    authority = db_session.get(TaxonomyAuthority, 1)
    authority.processing_head_revision = 5
    db_session.flush()

    result = repo.complete(
        claimed.id,
        lease_token=claimed.lease_token,
        result_payload={"candidate_count": 1},
        classification_attempt_id=classification_attempt_id,
    )

    assert result.status == "pending"
    assert result.completion_code == "stale_processing_head"
    assert result.observed_processing_head_revision == 5
    assert result.lease_token is None
    event = db_session.execute(
        select(ProcessingRequestEvent)
        .where(ProcessingRequestEvent.processing_request_id == claimed.id)
        .order_by(ProcessingRequestEvent.sequence_number.desc())
        .limit(1)
    ).scalar_one()
    assert event.event_payload["superseded_attempt_id"] == str(
        classification_attempt_id
    )


def test_completion_rejects_stale_authority_epoch(db_session):
    request = _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)
    claimed = repo.claim_next(worker_id="worker-1", now=NOW)
    db_session.get(TaxonomyAuthority, 1).authority_epoch = 8
    db_session.flush()

    with pytest.raises(StaleAuthorityEpoch):
        repo.complete(
            request.id,
            lease_token=claimed.lease_token,
            result_payload={},
        )


def test_candidates_and_proposals_are_durable_request_children(db_session):
    request = _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)

    candidate = repo.record_candidate(
        request.id, candidate_key="claim-1", payload={"mechanism": "memory pricing"}
    )
    dimension = repo.record_dimension_proposal(
        request.id, dimension_key="workload", payload={"value": "AI training"}
    )
    naming = repo.record_naming_proposal(
        request.id, proposal_key="ai-memory", payload={"display_name": "AI Memory"}
    )

    assert (
        candidate.id is not None and dimension.id is not None and naming.id is not None
    )
    assert (
        db_session.scalar(select(func.count()).select_from(EconomicExposureCandidate))
        == 1
    )
    assert db_session.scalar(select(func.count()).select_from(DimensionProposal)) == 1
    assert db_session.scalar(select(func.count()).select_from(NamingProposal)) == 1


def test_idempotency_key_cannot_silently_replace_candidate_payload(db_session):
    request = _request(db_session)
    repo = EconomicTaxonomyWorkRepository(db_session)
    repo.record_candidate(
        request.id, candidate_key="claim-1", payload={"claim": "old"}
    )

    with pytest.raises(ValueError, match="idempotency key payload conflict"):
        repo.record_candidate(
            request.id,
            candidate_key="claim-1",
            payload={"claim": "different"},
        )
