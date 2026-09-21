from __future__ import annotations

from datetime import datetime, timezone

from app.database import SessionLocal
from app.infra.db.repositories.economic_taxonomy_work_repo import (
    EconomicTaxonomyWorkRepository,
)
from app.models.economic_taxonomy_runtime import TaxonomyAuthority
from app.services.economic_exposure_claim_review import EconomicExposureClaimReviewer
from app.services.economic_exposure_extraction import EconomicExposureExtractor
from app.services.economic_source_admission import (
    EconomicSourceAdmissionService,
    EvidenceAdmission,
)
from app.services.economic_taxonomy_seed import INITIAL_DIMENSIONS

NOW = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


class Provider:
    def __init__(self, extraction, *reviews):
        self.extraction = extraction
        self.reviews = list(reviews)
        self.extract_count = 0
        self.review_count = 0

    def extract(self, *, evidence, policy_version):
        self.extract_count += 1
        return self.extraction

    def review(self, *, extraction, policy_version, facet_catalog_semantic_hash):
        self.review_count += 1
        return (
            self.reviews.pop(0)
            if self.reviews
            else {
                "decisions": [
                    {"candidate_key": row["candidate_key"], "decision": "accepted"}
                    for row in extraction["candidates"]
                ],
                "provider_request_id": f"review-{self.review_count}",
                "actual_cost": "0.01",
            }
        )


def _candidate(
    *,
    key="memory",
    name="Memory",
    facets=None,
    candidate_kind="economic_exposure",
    securities=None,
):
    return {
        "candidate_key": key,
        "display_name": name,
        "raw_facets": facets or {"industry": "Memory"},
        "mechanism": "Demand changes industry economics.",
        "evidence_spans": ["Memory pricing rose."],
        "relationship_evidence": [],
        "exposure_support": "direct",
        "development_support": "present",
        "candidate_kind": candidate_kind,
        "securities": (
            [{"security_id": 42, "symbol": "MU"}] if securities is None else securities
        ),
    }


def _provider_payload(candidate):
    return {
        "status": "accepted_candidates",
        "candidates": [candidate],
        "provider_request_id": "extract-1",
        "actual_cost": "0.01",
    }


def _extraction(db_session, provider):
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
            canonical_item_id="review-post",
            capture_route="legacy",
            original_text="Memory pricing rose.",
            preparation_version="prep-v1",
            grounding_snapshot={
                "companies": [{"security_id": 42, "symbol": "MU"}]
            },
            captured_at=NOW,
            available_at=NOW,
        )
    )
    request = EconomicTaxonomyWorkRepository(db_session).enqueue_request(
        source_lineage_id=admitted.source_lineage_id,
        evidence_packet_id=admitted.packet_id,
        policy_bundle_version="bundle-v1",
        available_at=NOW,
    )
    db_session.commit()
    extraction = EconomicExposureExtractor(
        SessionLocal,
        provider=provider,
        extraction_policy_version="extract-v1",
        approved_dimensions=INITIAL_DIMENSIONS,
    ).extract(request)
    return request, extraction


def _reviewer(provider):
    return EconomicExposureClaimReviewer(
        SessionLocal,
        provider=provider,
        claim_review_policy_version="review-v1",
        approved_dimensions=INITIAL_DIMENSIONS,
    )


def test_dimension_definition_change_invalidates_claim_review_artifact(db_session):
    provider = Provider(_provider_payload(_candidate()))
    _request, extraction = _extraction(db_session, provider)
    reviewer = _reviewer(provider)

    first = reviewer.review(extraction, facet_hash="catalog-definition-v1")
    second = reviewer.review(extraction, facet_hash="catalog-definition-v2")

    assert first.id != second.id
    assert provider.review_count == 2


def test_exact_review_key_reuses_artifact_without_provider_call(db_session):
    provider = Provider(_provider_payload(_candidate()))
    _request, extraction = _extraction(db_session, provider)
    reviewer = _reviewer(provider)

    first = reviewer.review(extraction, facet_hash="catalog-v1")
    second = reviewer.review(extraction, facet_hash="catalog-v1")

    assert first.id == second.id
    assert provider.review_count == 1


def test_taxonomy_head_only_change_reuses_both_artifacts(db_session):
    provider = Provider(_provider_payload(_candidate()))
    request, extraction = _extraction(db_session, provider)
    reviewer = _reviewer(provider)
    first = reviewer.review(extraction, facet_hash="catalog-v1")
    with SessionLocal.begin() as session:
        session.get(TaxonomyAuthority, 1).processing_head_revision = 2

    extracted_again = EconomicExposureExtractor(
        SessionLocal,
        provider=provider,
        extraction_policy_version="extract-v1",
        approved_dimensions=INITIAL_DIMENSIONS,
    ).extract(request)
    reviewed_again = reviewer.review(extracted_again, facet_hash="catalog-v1")

    assert extracted_again.id == extraction.id
    assert reviewed_again.id == first.id
    assert provider.extract_count == 1
    assert provider.review_count == 1


def test_technical_setup_is_held_as_not_an_economic_theme(db_session):
    provider = Provider(
        _provider_payload(
            _candidate(
                key="vcp",
                name="VCP Breakout",
                facets={"industry": "Memory"},
                candidate_kind="technical_setup",
            )
        )
    )
    _request, extraction = _extraction(db_session, provider)

    result = _reviewer(provider).review(extraction, facet_hash="catalog-v1")

    assert result.result_status == "review_required"
    assert result.result_payload["held"][0]["reason"] == "technical_setup_not_theme"
    assert provider.review_count == 0


def test_technical_name_is_held_even_when_provider_mislabels_kind(db_session):
    provider = Provider(
        _provider_payload(
            _candidate(
                key="vcp",
                name="VCP Breakout",
                facets={"industry": "Memory"},
                candidate_kind="economic_exposure",
            )
        )
    )
    _request, extraction = _extraction(db_session, provider)

    result = _reviewer(provider).review(extraction, facet_hash="catalog-v1")

    assert result.result_status == "review_required"
    assert result.result_payload["held"][0]["reason"] == "technical_setup_not_theme"
    assert provider.review_count == 0


def test_narrowest_specificity_must_be_supported(db_session):
    provider = Provider(
        _provider_payload(
            _candidate(
                key="ai-hbm",
                name="AI HBM",
                facets={"end_market": "AI", "industry": "Memory"},
            )
        )
    )
    _request, extraction = _extraction(db_session, provider)

    result = _reviewer(provider).review(extraction, facet_hash="catalog-v1")

    assert result.result_status == "review_required"
    assert result.result_payload["held"][0]["reason"] == "unsupported_specificity"


def test_ungrounded_security_is_held(db_session):
    provider = Provider(_provider_payload(_candidate(securities=[{"symbol": "MU"}])))
    _request, extraction = _extraction(db_session, provider)

    result = _reviewer(provider).review(extraction, facet_hash="catalog-v1")

    assert result.result_status == "review_required"
    assert result.result_payload["held"][0]["reason"] == "security_grounding_required"


def test_security_id_outside_frozen_grounding_is_held(db_session):
    provider = Provider(
        _provider_payload(
            _candidate(securities=[{"security_id": 99, "symbol": "UNGROUNDED"}])
        )
    )
    _request, extraction = _extraction(db_session, provider)

    result = _reviewer(provider).review(extraction, facet_hash="catalog-v1")

    assert result.result_status == "review_required"
    assert result.result_payload["held"][0]["reason"] == "security_grounding_required"


def test_provider_response_hash_is_retained(db_session):
    provider = Provider(_provider_payload(_candidate()))
    _request, extraction = _extraction(db_session, provider)

    result = _reviewer(provider).review(extraction, facet_hash="catalog-v1")

    assert extraction.provider_response_hash
    assert result.provider_response_hash
    assert result.result_status == "accepted_candidates"
