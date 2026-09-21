from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.domain.economic_taxonomy.contracts import AdminPrincipal
from app.infra.db.repositories.economic_taxonomy_repo import EconomicTaxonomyRepository
from app.models.economic_taxonomy import (
    LegacyClaimAllocation,
    LegacyDestinationMapping,
    LegacyIdentityDisposition,
)
from app.models.economic_taxonomy_runtime import (
    ImmutableRuntimePayload,
    TaxonomyAuthority,
    TaxonomyMigrationProgressEvent,
    TaxonomyMigrationReview,
    TaxonomySourceRevisionLog,
)
from app.models.theme import ThemeCluster, ThemeMention
from app.services.economic_taxonomy_migration import (
    EconomicTaxonomyMigrationService,
    MigrationReviewForbidden,
)


@pytest.fixture
def reviewer():
    return AdminPrincipal(
        subject="admin:migration-reviewer",
        auth_method="admin_api_key",
        roles=frozenset({"taxonomy:review"}),
    )


@pytest.fixture
def migration_setup(db_session, reviewer):
    repository = EconomicTaxonomyRepository(db_session)
    taxonomy = repository.create_draft(
        actor=reviewer.subject,
        reason="migration target",
    )
    petroleum = repository.create_theme(
        taxonomy.id,
        display_name="Petroleum Refining",
        definition="Petroleum refining economics.",
        mechanism="Crude inputs become fuels and products.",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
        actor=reviewer.subject,
    )
    metals = repository.create_theme(
        taxonomy.id,
        display_name="Metals Refining",
        definition="Metals refining economics.",
        mechanism="Ore and concentrates become refined metals.",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
        actor=reviewer.subject,
    )
    memory = repository.create_theme(
        taxonomy.id,
        display_name="AI Memory",
        definition="Memory demand serving AI workloads.",
        mechanism="AI infrastructure increases memory intensity.",
        lifecycle="established",
        lifecycle_policy_version="lifecycle-v1",
        actor=reviewer.subject,
    )
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="shadow",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=1,
            authority_epoch=7,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            cutover_catch_up_cursor=[],
            rollback_state="ready",
        )
    )
    db_session.flush()
    service = EconomicTaxonomyMigrationService(
        db_session,
        principal=reviewer,
        expected_epoch=7,
    )
    return service, taxonomy, petroleum, metals, memory


def _dataset(taxonomy_id, identities):
    return {
        "taxonomy_version_id": str(taxonomy_id),
        "migration_policy_version": "legacy-to-economic-v1",
        "policy_bundle": {
            "resolver": "resolver-v1",
            "naming": "naming-v1",
            "allocation": "allocation-v1",
        },
        "legacy_identities": identities,
    }


def _identity(cluster_id, claims):
    return {
        "legacy_theme_cluster_id": cluster_id,
        "source_hash": f"legacy-theme:{cluster_id}:sha256",
        "current_claims": [
            {"allocation_kind": "mention", "allocation_key": claim}
            for claim in claims
        ],
    }


def test_complete_coverage_means_disposition_plus_split_allocations(
    db_session, migration_setup
):
    migration, taxonomy, petroleum, metals, _memory = migration_setup
    run = migration.build_migration(
        _dataset(taxonomy.id, [_identity(42, ["mention:100", "mention:101"])])
    )

    assert run.status == "sealed"
    assert run.coverage_complete is False

    migration.review_split(
        run.id,
        42,
        destination_theme_ids=(petroleum.id, metals.id),
        allocations=(
            {
                "allocation_kind": "mention",
                "allocation_key": "mention:100",
                "destination_theme_id": str(petroleum.id),
            },
        ),
        reason="First reviewed allocation batch.",
    )
    assert migration.get(run.id).coverage_complete is False

    migration.review_split(
        run.id,
        42,
        destination_theme_ids=(petroleum.id, metals.id),
        allocations=(
            {
                "allocation_kind": "mention",
                "allocation_key": "mention:101",
                "destination_theme_id": str(metals.id),
            },
        ),
        reason="Final reviewed allocation batch.",
    )

    assert migration.get(run.id).coverage_complete is True
    assert db_session.scalar(
        select(LegacyIdentityDisposition).where(
            LegacyIdentityDisposition.taxonomy_version_id == taxonomy.id,
            LegacyIdentityDisposition.legacy_theme_cluster_id == 42,
        )
    ).disposition == "split_required"
    assert len(
        db_session.scalars(
            select(LegacyDestinationMapping).where(
                LegacyDestinationMapping.taxonomy_version_id == taxonomy.id,
                LegacyDestinationMapping.legacy_theme_cluster_id == 42,
            )
        ).all()
    ) == 2
    completed = db_session.scalar(
        select(TaxonomyMigrationProgressEvent).where(
            TaxonomyMigrationProgressEvent.migration_run_id == run.id,
            TaxonomyMigrationProgressEvent.event_type == "completed",
        )
    )
    assert len(completed.event_payload["output_taxonomy_semantic_hash"]) == 64
    latest_review = db_session.scalar(
        select(TaxonomyMigrationReview)
        .where(
            TaxonomyMigrationReview.migration_run_id == run.id,
            TaxonomyMigrationReview.legacy_theme_cluster_id == 42,
        )
        .order_by(TaxonomyMigrationReview.review_revision.desc())
        .limit(1)
    )
    assert len(latest_review.allocations) == 2
    assert len(
        db_session.scalars(
            select(LegacyClaimAllocation).where(
                LegacyClaimAllocation.taxonomy_version_id == taxonomy.id,
                LegacyClaimAllocation.legacy_theme_cluster_id == 42,
            )
        ).all()
    ) == 2


def test_many_to_one_reviews_reuse_one_global_identity(migration_setup):
    migration, taxonomy, _petroleum, _metals, memory = migration_setup
    run = migration.build_migration(
        _dataset(taxonomy.id, [_identity(10, []), _identity(11, [])])
    )

    for cluster_id in (10, 11):
        migration.review_disposition(
            run.id,
            cluster_id,
            disposition="merged_equivalent",
            destination_theme_ids=(memory.id,),
            reason="Equivalent legacy pipeline identities.",
        )

    assert migration.get(run.id).coverage_complete is True
    assert {
        row.destination_theme_id
        for row in migration.session.scalars(
            select(LegacyDestinationMapping).where(
                LegacyDestinationMapping.taxonomy_version_id == taxonomy.id
            )
        )
    } == {memory.id}


def test_capture_legacy_dataset_hashes_theme_and_current_claims(migration_setup):
    migration, taxonomy, _petroleum, _metals, _memory = migration_setup
    cluster = ThemeCluster(
        name="Legacy Refining",
        canonical_key="legacy-refining",
        display_name="Legacy Refining",
        pipeline="fundamental",
        lifecycle_state="active",
    )
    migration.session.add(cluster)
    migration.session.flush()
    mention = ThemeMention(
        content_item_id=123,
        source_type="news",
        raw_theme="Refining",
        canonical_theme="Refining",
        theme_cluster_id=cluster.id,
        pipeline="fundamental",
    )
    migration.session.add(mention)
    migration.session.flush()

    dataset = migration.capture_legacy_dataset(
        taxonomy_version_id=taxonomy.id,
        migration_policy_version="legacy-to-economic-v1",
        policy_bundle={"resolver": "resolver-v1"},
    )

    identity = dataset["legacy_identities"][0]
    assert identity["legacy_theme_cluster_id"] == cluster.id
    assert len(identity["source_hash"]) == 64
    assert identity["current_claims"] == [
        {
            "allocation_kind": "mention",
            "allocation_key": f"theme_mention:{mention.id}",
        }
    ]


def test_reviewed_exclusion_completes_identity_without_destination(migration_setup):
    migration, taxonomy, _petroleum, _metals, _memory = migration_setup
    run = migration.build_migration(_dataset(taxonomy.id, [_identity(7, [])]))

    migration.review_disposition(
        run.id,
        7,
        disposition="not_a_theme",
        reason="The legacy row is a company name, not an economic exposure.",
    )

    assert migration.get(run.id).coverage_complete is True
    review = migration.session.scalar(
        select(TaxonomyMigrationReview).where(
            TaxonomyMigrationReview.migration_run_id == run.id
        )
    )
    assert review.reviewer_subject == "admin:migration-reviewer"
    assert review.reason.startswith("The legacy row")


def test_max_source_id_is_not_used_as_replay_barrier(
    migration_setup,
):
    migration, taxonomy, _petroleum, _metals, _memory = migration_setup
    run = migration.build_migration(_dataset(taxonomy.id, [_identity(9, [])]))
    migration.review_disposition(
        run.id,
        9,
        disposition="not_a_theme",
        reason="Reviewed exclusion.",
    )
    migration.session.add_all(
        [
            TaxonomySourceRevisionLog(
                id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
                producer_kind="content",
                logical_source_key="source:later-id",
                revision_kind="evidence",
                revision_number=1,
                content_hash="hash-a",
                authority_epoch=7,
            ),
            TaxonomySourceRevisionLog(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                producer_kind="content",
                logical_source_key="source:late-commit",
                revision_kind="evidence",
                revision_number=2,
                content_hash="hash-b",
                authority_epoch=7,
            ),
        ]
    )
    migration.session.flush()

    manifest = migration.replay_manifest(run.id)
    rows = migration.session.scalars(select(TaxonomySourceRevisionLog)).all()
    expected = tuple(
        sorted(
            (
                row.producer_kind,
                row.logical_source_key,
                row.revision_kind,
                row.revision_number,
                row.content_hash,
                str(row.id),
            )
            for row in rows
        )
    )

    assert manifest.entries == expected
    assert not hasattr(manifest, "max_source_id")
    assert not hasattr(manifest, "high_watermark")

    migration.session.add(
        TaxonomySourceRevisionLog(
            producer_kind="social",
            logical_source_key="association:late",
            revision_kind="decision",
            revision_number=1,
            content_hash="hash-late",
            authority_epoch=7,
        )
    )
    migration.session.flush()
    later_manifest = migration.replay_manifest(run.id)
    replay_rows = migration.session.scalars(
        select(TaxonomySourceRevisionLog).where(
            TaxonomySourceRevisionLog.producer_kind == "migration",
            TaxonomySourceRevisionLog.logical_source_key
            == f"migration_run:{run.id}",
            TaxonomySourceRevisionLog.revision_kind == "migration_replay",
        )
    ).all()
    assert later_manifest.semantic_hash != manifest.semantic_hash
    assert {row.revision_number for row in replay_rows} == {1, 2}


def test_migration_inputs_and_progress_events_are_immutable(
    db_session, migration_setup
):
    migration, taxonomy, _petroleum, _metals, _memory = migration_setup
    run = migration.build_migration(_dataset(taxonomy.id, [_identity(5, [])]))
    event = db_session.scalar(
        select(TaxonomyMigrationProgressEvent).where(
            TaxonomyMigrationProgressEvent.migration_run_id == run.id
        )
    )
    event_id = event.id
    db_session.commit()

    run.dataset_manifest = {"changed": True}
    with pytest.raises(ImmutableRuntimePayload, match="migration_run_inputs_immutable"):
        db_session.flush()
    db_session.rollback()

    event = db_session.get(TaxonomyMigrationProgressEvent, event_id)
    event.reason = "changed"
    with pytest.raises(ImmutableRuntimePayload, match="runtime_payload_immutable"):
        db_session.flush()


def test_untrusted_reviewer_is_rejected_before_state_is_written(db_session, reviewer):
    principal = AdminPrincipal(
        subject="user:viewer",
        auth_method="session",
        roles=frozenset(),
    )
    service = EconomicTaxonomyMigrationService(
        db_session,
        principal=principal,
        expected_epoch=1,
    )

    with pytest.raises(MigrationReviewForbidden):
        service.build_migration(
            _dataset(
                UUID("00000000-0000-0000-0000-000000000001"),
                [_identity(1, [])],
            )
        )

    assert db_session.scalar(select(TaxonomyMigrationProgressEvent)) is None
