from __future__ import annotations

from sqlalchemy import select

from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
    GraphInvariantViolation,
    ImmutableSnapshot,
)
from app.models.economic_taxonomy import (
    EconomicThemeRevision,
    LegacyClaimAllocation,
    LegacyDestinationMapping,
    LegacyIdentityDisposition,
)


def _draft_with_destinations(db_session):
    repo = EconomicTaxonomyRepository(db_session)
    draft = repo.create_draft(actor="test:reviewer", reason="mapping fixture")
    petroleum = repo.create_theme(
        draft.id,
        display_name="Petroleum Refining",
        definition="Refining crude oil into petroleum products.",
        mechanism="Petroleum refining margins",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
    )
    metals = repo.create_theme(
        draft.id,
        display_name="Metals Refining",
        definition="Refining mined ore into industrial metals.",
        mechanism="Metals refining margins",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
    )
    return repo, draft, petroleum, metals


def test_refining_split_allocates_each_claim_and_clones_complete_mapping(db_session):
    repo, draft, petroleum, metals = _draft_with_destinations(db_session)
    repo.set_legacy_disposition(
        draft.id, 42, disposition="split_required", actor="test:reviewer"
    )
    repo.add_legacy_destination(draft.id, 42, petroleum.id, actor="test:reviewer")
    repo.add_legacy_destination(draft.id, 42, metals.id, actor="test:reviewer")
    repo.allocate_legacy_claim(
        draft.id,
        42,
        allocation_kind="claim",
        allocation_key="petroleum-claim",
        destination_theme_id=petroleum.id,
        actor="test:reviewer",
    )
    repo.allocate_legacy_claim(
        draft.id,
        42,
        allocation_kind="claim",
        allocation_key="metals-claim",
        destination_theme_id=metals.id,
        actor="test:reviewer",
    )
    sealed = repo.seal_draft(draft.id)
    original_hash = sealed.semantic_hash

    assert db_session.query(LegacyDestinationMapping).filter_by(
        taxonomy_version_id=sealed.id, legacy_theme_cluster_id=42
    ).count() == 2
    assert db_session.query(LegacyClaimAllocation).filter_by(
        taxonomy_version_id=sealed.id, legacy_theme_cluster_id=42
    ).count() == 2

    clone = repo.clone_draft(
        sealed.id, actor="test:reviewer", reason="copy complete mapping"
    )

    assert repo.semantic_hash(clone.id) == original_hash
    snapshot = repo.load_snapshot(clone.id)
    assert len(snapshot["legacy_dispositions"]) == 1
    assert len(snapshot["legacy_destinations"]) == 2
    assert len(snapshot["legacy_claim_allocations"]) == 2


def test_not_a_theme_disposition_has_no_destination(db_session):
    repo, draft, _petroleum, _metals = _draft_with_destinations(db_session)
    repo.set_legacy_disposition(
        draft.id, 77, disposition="not_a_theme", actor="test:reviewer"
    )
    repo.allocate_legacy_claim(
        draft.id,
        77,
        allocation_kind="source_association",
        allocation_key="legacy-source:77",
        reviewed_exclusion="not_a_theme",
        actor="test:reviewer",
    )
    repo.seal_draft(draft.id)

    disposition = db_session.get(LegacyIdentityDisposition, (draft.id, 77))
    destinations = db_session.scalars(
        select(LegacyDestinationMapping).where(
            LegacyDestinationMapping.taxonomy_version_id == draft.id,
            LegacyDestinationMapping.legacy_theme_cluster_id == 77,
        )
    ).all()

    assert disposition.disposition == "not_a_theme"
    assert destinations == []


def test_redirect_conflicts_with_distinct_assertion(db_session):
    repo, draft, petroleum, metals = _draft_with_destinations(db_session)
    repo.add_relationship(
        draft.id,
        source_theme_id=petroleum.id,
        target_theme_id=metals.id,
        kind="distinct",
        direction="symmetric",
        discriminator="different feedstock",
    )
    repo.add_theme_redirect(
        draft.id,
        source_theme_id=petroleum.id,
        target_theme_id=metals.id,
        actor="test:reviewer",
        reason="reviewed merge",
    )

    with __import__("pytest").raises(
        GraphInvariantViolation, match="contradictory_relationship_assertion"
    ):
        repo.seal_draft(draft.id)


def test_split_must_allocate_every_declared_claim(db_session):
    repo, draft, petroleum, _metals = _draft_with_destinations(db_session)
    repo.set_legacy_disposition(
        draft.id, 91, disposition="split_required", actor="test:reviewer"
    )
    repo.add_legacy_destination(draft.id, 91, petroleum.id, actor="test:reviewer")

    with __import__("pytest").raises(ValueError, match="split_requires_allocations"):
        repo.seal_draft(draft.id)


def test_mapping_destination_must_exist_in_same_snapshot(db_session):
    repo, first, petroleum, _metals = _draft_with_destinations(db_session)
    second = repo.create_draft(actor="test:reviewer", reason="other snapshot")
    repo.set_legacy_disposition(
        second.id, 42, disposition="mapped", actor="test:reviewer"
    )

    with __import__("pytest").raises(ValueError, match="same_snapshot_reference"):
        repo.add_legacy_destination(
            second.id, 42, petroleum.id, actor="test:reviewer"
        )

    assert db_session.scalar(
        select(EconomicThemeRevision).where(
            EconomicThemeRevision.taxonomy_version_id == first.id,
            EconomicThemeRevision.theme_id == petroleum.id,
        )
    ) is not None


def test_sealed_mapping_rows_are_immutable(db_session):
    repo, draft, petroleum, _metals = _draft_with_destinations(db_session)
    disposition = repo.set_legacy_disposition(
        draft.id, 42, disposition="mapped", actor="test:reviewer"
    )
    repo.add_legacy_destination(draft.id, 42, petroleum.id, actor="test:reviewer")
    repo.seal_draft(draft.id)
    db_session.commit()

    disposition.disposition = "deferred"
    with __import__("pytest").raises(
        ImmutableSnapshot, match="sealed_snapshot_immutable"
    ):
        db_session.flush()
