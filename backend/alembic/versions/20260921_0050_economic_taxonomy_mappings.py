"""Add cardinality-safe taxonomy mappings and reviewed operations."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_0050"
down_revision = "20260921_0049"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _created_at():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade():
    op.create_table(
        "economic_legacy_identity_dispositions",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_theme_cluster_id", sa.Integer(), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("review_comment", sa.Text()),
        _created_at(),
        sa.CheckConstraint(
            "disposition IN ('mapped','split_required','merged_equivalent',"
            "'not_a_theme','deferred')",
            name="ck_economic_legacy_identity_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id"],
            ["economic_taxonomy_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("taxonomy_version_id", "legacy_theme_cluster_id"),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_legacy_disposition_logical_row",
        ),
    )
    op.create_table(
        "economic_legacy_destination_mappings",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_theme_cluster_id", sa.Integer(), nullable=False),
        sa.Column("destination_theme_id", sa.Uuid(), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("review_comment", sa.Text()),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "legacy_theme_cluster_id"],
            [
                "economic_legacy_identity_dispositions.taxonomy_version_id",
                "economic_legacy_identity_dispositions.legacy_theme_cluster_id",
            ],
            name="fk_economic_legacy_destination_disposition",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "destination_theme_id"],
            [
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ],
            name="fk_economic_legacy_destination_same_snapshot_theme",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "taxonomy_version_id",
            "legacy_theme_cluster_id",
            "destination_theme_id",
        ),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_legacy_destination_logical_row",
        ),
    )
    op.create_table(
        "economic_legacy_claim_allocations",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_theme_cluster_id", sa.Integer(), nullable=False),
        sa.Column("allocation_kind", sa.String(40), nullable=False),
        sa.Column("allocation_key", sa.String(500), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("destination_theme_id", sa.Uuid()),
        sa.Column("reviewed_exclusion", sa.String(80)),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("review_comment", sa.Text()),
        _created_at(),
        sa.CheckConstraint(
            "(destination_theme_id IS NOT NULL AND reviewed_exclusion IS NULL) OR "
            "(destination_theme_id IS NULL AND reviewed_exclusion IS NOT NULL)",
            name="ck_economic_legacy_allocation_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "legacy_theme_cluster_id"],
            [
                "economic_legacy_identity_dispositions.taxonomy_version_id",
                "economic_legacy_identity_dispositions.legacy_theme_cluster_id",
            ],
            name="fk_economic_legacy_allocation_disposition",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "taxonomy_version_id",
                "legacy_theme_cluster_id",
                "destination_theme_id",
            ],
            [
                "economic_legacy_destination_mappings.taxonomy_version_id",
                "economic_legacy_destination_mappings.legacy_theme_cluster_id",
                "economic_legacy_destination_mappings.destination_theme_id",
            ],
            name="fk_economic_legacy_allocation_destination",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "taxonomy_version_id",
            "legacy_theme_cluster_id",
            "allocation_kind",
            "allocation_key",
        ),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_legacy_allocation_logical_row",
        ),
    )
    op.create_table(
        "economic_theme_redirects",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_theme_id", sa.Uuid(), nullable=False),
        sa.Column("target_theme_id", sa.Uuid(), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("review_comment", sa.Text()),
        _created_at(),
        sa.CheckConstraint(
            "source_theme_id <> target_theme_id",
            name="ck_economic_redirect_distinct_endpoints",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "source_theme_id"],
            [
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ],
            name="fk_economic_redirect_same_snapshot_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "target_theme_id"],
            [
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ],
            name="fk_economic_redirect_same_snapshot_target",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("taxonomy_version_id", "source_theme_id"),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_redirect_logical_row",
        ),
    )

    op.create_table(
        "economic_taxonomy_operation_requests",
        _id(),
        sa.Column("operation_kind", sa.String(80), nullable=False),
        sa.Column("base_taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("auth_method", sa.String(80), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["base_taxonomy_version_id"], ["economic_taxonomy_versions.id"]
        ),
    )
    op.create_table(
        "economic_taxonomy_operation_previews",
        _id(),
        sa.Column("operation_request_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("candidate_taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("preview_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("before_semantic_hash", sa.String(128), nullable=False),
        sa.Column("before_artifact_integrity_hash", sa.String(128), nullable=False),
        sa.Column("after_semantic_hash", sa.String(128), nullable=False),
        sa.Column("after_artifact_integrity_hash", sa.String(128), nullable=False),
        sa.Column("affected_identities", sa.JSON(), nullable=False),
        sa.Column("assignments", sa.JSON(), nullable=False),
        sa.Column("mappings", sa.JSON(), nullable=False),
        sa.Column("compatibility_intents", sa.JSON(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column(
            "incompatible_with_prepared_generation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["operation_request_id"], ["economic_taxonomy_operation_requests.id"]
        ),
        sa.ForeignKeyConstraint(
            ["candidate_taxonomy_version_id"], ["economic_taxonomy_versions.id"]
        ),
    )
    op.create_table(
        "economic_taxonomy_operation_events",
        _id(),
        sa.Column("operation_request_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "event_type IN ('previewed','reviewed','applied','failed')",
            name="ck_economic_taxonomy_operation_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["operation_request_id"], ["economic_taxonomy_operation_requests.id"]
        ),
        sa.UniqueConstraint(
            "operation_request_id",
            "sequence_number",
            name="uq_economic_taxonomy_operation_event_sequence",
        ),
    )
    for table_name, identity_name, constraint_name in (
        (
            "economic_taxonomy_proposal_events",
            "proposal_identity",
            "uq_economic_taxonomy_proposal_event_sequence",
        ),
        (
            "economic_taxonomy_override_events",
            "override_identity",
            "uq_economic_taxonomy_override_event_sequence",
        ),
    ):
        op.create_table(
            table_name,
            _id(),
            sa.Column(identity_name, sa.Uuid(), nullable=False),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("actor_subject", sa.String(200), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("event_payload", sa.JSON(), nullable=False),
            _created_at(),
            sa.UniqueConstraint(
                identity_name, "sequence_number", name=constraint_name
            ),
        )

    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "economic_legacy_identity_dispositions",
            "economic_legacy_destination_mappings",
            "economic_legacy_claim_allocations",
            "economic_theme_redirects",
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_immutable "
                    f"BEFORE INSERT OR UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION "
                    "economic_taxonomy_reject_sealed_owned_mutation()"
                )
            )
        for table in (
            "economic_taxonomy_operation_requests",
            "economic_taxonomy_operation_previews",
            "economic_taxonomy_operation_events",
            "economic_taxonomy_proposal_events",
            "economic_taxonomy_override_events",
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
                )
            )


def downgrade():
    for table in (
        "economic_taxonomy_override_events",
        "economic_taxonomy_proposal_events",
        "economic_taxonomy_operation_events",
        "economic_taxonomy_operation_previews",
        "economic_taxonomy_operation_requests",
        "economic_theme_redirects",
        "economic_legacy_claim_allocations",
        "economic_legacy_destination_mappings",
        "economic_legacy_identity_dispositions",
    ):
        op.drop_table(table)
