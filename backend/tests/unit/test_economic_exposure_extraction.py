from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from app.database import SessionLocal
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy_runtime import (
    DimensionProposal,
    ProviderAttempt,
    TaxonomyAuthority,
)
from app.services.economic_exposure_extraction import (
    EconomicExposureExtractor,
    EvidenceSchemaError,
    RetryableProviderError,
    RetryableProviderFailure,
)
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_seed import INITIAL_DIMENSIONS
from sqlalchemy import select

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


class FakeProvider:
    def __init__(self, *effects):
        self.effects = list(effects)
        self.call_count = 0

    def extract(self, *, evidence, policy_version):
        self.call_count += 1
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


class FakeReservation:
    def __init__(self):
        self.state = "reserved"

    def mark_dispatched(self):
        self.state = "dispatched"

    def release_pre_dispatch(self):
        self.state = "released"

    def reconcile(self, *, actual_cost, provider_request_id):
        self.actual_cost = actual_cost
        self.provider_request_id = provider_request_id
        self.state = "uncertain" if actual_cost is None else "reconciled"


class FakeReservations:
    def __init__(self):
        self.reservations = []

    @property
    def reservation_count(self):
        return len(self.reservations)

    def reserve(self, *, attempt_key, logical_request_id, operation_kind):
        reservation = FakeReservation()
        reservation.attempt_key = attempt_key
        reservation.logical_request_id = logical_request_id
        reservation.operation_kind = operation_kind
        self.reservations.append(reservation)
        return reservation


def _candidate(
    name="Memory",
    *,
    facets=None,
    spans=None,
    relationship_evidence=None,
    exposure_support="direct",
    development_support="present",
):
    return {
        "candidate_key": name.casefold().replace(" ", "-"),
        "display_name": name,
        "raw_facets": facets or {"industry": "Memory"},
        "mechanism": "Demand changes industry economics.",
        "evidence_spans": spans or ["Memory pricing rose."],
        "relationship_evidence": relationship_evidence or [],
        "exposure_support": exposure_support,
        "development_support": development_support,
        "securities": [{"security_id": 42, "symbol": "MU"}],
    }


def _payload(*candidates, status="accepted_candidates"):
    return {
        "status": status,
        "candidates": list(candidates),
        "provider_request_id": "provider-1",
        "actual_cost": Decimal("0.01"),
    }


def _request(db_session, *, text="Memory pricing rose."):
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_head_revision=1,
            authority_epoch=1,
            writes_fenced=False,
            rollback_state="ready",
        )
    )
    db_session.flush()
    admitted = EconomicSourceAdmissionService(db_session).admit_content(
        EvidenceAdmission(
            provider="x",
            canonical_item_id="extraction-post",
            capture_route="legacy",
            original_text=text,
            preparation_version="prep-v1",
            captured_at=NOW,
            available_at=NOW,
            evidence_channels=("narrative",),
        )
    )
    request = EconomicTaxonomyWorkRepository(db_session).enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="bundle-v1",
        available_at=NOW,
    )
    db_session.commit()
    return request


def _extractor(provider, reservations=None):
    return EconomicExposureExtractor(
        SessionLocal,
        provider=provider,
        extraction_policy_version="extract-v1",
        approved_dimensions=INITIAL_DIMENSIONS,
        reservations=reservations,
    )


def test_ai_and_memory_cooccurrence_without_link_is_not_ai_memory(db_session):
    request = _request(
        db_session,
        text="AI spending rose. Memory pricing rose independently.",
    )
    provider = FakeProvider(
        _payload(
            _candidate(
                "AI Memory",
                facets={"end_market": "AI", "industry": "Memory"},
                spans=["AI spending rose.", "Memory pricing rose independently."],
            )
        )
    )

    result = _extractor(provider).extract(request)

    assert result.result_status == "review_required"
    assert "AI Memory" not in result.result_payload["accepted_names"]
    assert (
        "compound_relationship_evidence_required"
        in result.result_payload["candidates"][0]["review_reasons"]
    )


def test_compound_relationship_quote_must_come_from_frozen_packet(db_session):
    request = _request(
        db_session,
        text="AI spending rose. Memory pricing rose independently.",
    )
    provider = FakeProvider(
        _payload(
            _candidate(
                "AI Memory",
                facets={"end_market": "AI", "industry": "Memory"},
                spans=["AI spending rose.", "Memory pricing rose independently."],
                relationship_evidence=["AI directly increased memory demand."],
            )
        )
    )

    result = _extractor(provider).extract(request)

    assert result.result_status == "review_required"
    assert (
        "relationship_evidence_not_in_packet"
        in result.result_payload["candidates"][0]["review_reasons"]
    )


def test_unknown_dimension_is_review_required_not_parse_failure(db_session):
    request = _request(db_session)
    provider = FakeProvider(
        _payload(_candidate("Edge AI", facets={"deployment_model": "edge"}))
    )

    result = _extractor(provider).extract(request)

    assert result.result_status == "review_required"
    assert result.result_payload["candidates"][0]["raw_facets"] == {
        "deployment_model": "edge"
    }
    with SessionLocal() as session:
        proposal = session.scalar(select(DimensionProposal))
        assert proposal.dimension_key == "deployment_model"


def test_successful_empty_is_distinct_from_failure(db_session):
    request = _request(db_session, text="No investable exposure.")
    provider = FakeProvider(_payload(status="successful_empty"))

    result = _extractor(provider).extract(request)

    assert result.result_status == "successful_empty"
    assert result.result_payload["candidates"] == []


def test_retryable_failure_then_success_preserves_attempts_and_reuses_success(
    db_session,
):
    request = _request(db_session)
    provider = FakeProvider(
        RetryableProviderError(
            "temporary failure",
            provider_request_id="r1",
            actual_cost=Decimal(0),
        ),
        _payload(_candidate()),
    )
    reservations = FakeReservations()
    extractor = _extractor(provider, reservations)

    with pytest.raises(RetryableProviderFailure):
        extractor.extract(request)
    succeeded = extractor.extract(request)
    repeated = extractor.extract(request)

    with SessionLocal() as session:
        attempts = session.scalars(
            select(ProviderAttempt).order_by(ProviderAttempt.attempt_number)
        ).all()
        assert [attempt.outcome for attempt in attempts] == [
            "retryable_failure",
            "success",
        ]
    assert succeeded.id == repeated.id
    assert provider.call_count == 2
    assert reservations.reservation_count == 2


def test_uncertain_timeout_differs_from_known_pre_dispatch_failure(db_session):
    request = _request(db_session)
    extractor = _extractor(FakeProvider(_payload(_candidate())))

    uncertain = extractor.record_timeout(request.id, provider_dispatch_confirmed=True)
    pre_dispatch = extractor.record_failure(
        request.id, provider_dispatch_confirmed=False
    )

    assert uncertain.attempt.state == "uncertain"
    assert uncertain.retry_allowed is False
    assert pre_dispatch.attempt.state == "released"
    assert pre_dispatch.retry_allowed is True


def test_exposure_and_development_support_use_distinct_enums(db_session):
    request = _request(db_session)
    provider = FakeProvider(
        _payload(
            _candidate(
                exposure_support="direct",
                development_support="absent",
            )
        )
    )
    accepted = _extractor(provider).extract(request)
    assert accepted.result_status == "accepted_candidates"
    assert accepted.result_payload["candidates"][0]["development_support"] == "absent"


def test_absent_is_not_an_exposure_support_state(db_session):
    request = _request(db_session)
    provider = FakeProvider(_payload(_candidate(exposure_support="absent")))

    with pytest.raises(EvidenceSchemaError, match="invalid_exposure_support"):
        _extractor(provider).extract(request)
