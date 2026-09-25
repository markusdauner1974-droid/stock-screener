"""Add ordered Economic Taxonomy compatibility outbox delivery."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_0051"
down_revision = "20260921_0050"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _created_at(name="created_at"):
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade():
    op.create_table(
        "economic_taxonomy_projection_events",
        _id(),
        sa.Column("serving_generation_id", sa.Uuid()),
        sa.Column("source_lineage", sa.String(500), nullable=False),
        sa.Column("projection_revision", sa.Integer(), nullable=False),
        sa.Column("projection_kind", sa.String(80), nullable=False),
        sa.Column("projection_version", sa.Integer(), nullable=False),
        sa.Column("target_representation", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(128), nullable=False),
        sa.Column("origin_representation", sa.String(80), nullable=False),
        sa.Column(
            "delivery_scope",
            sa.String(24),
            nullable=False,
            server_default="candidate",
        ),
        sa.Column("staged_epoch", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "projection_revision > 0 AND projection_version > 0",
            name="ck_economic_projection_positive_revisions",
        ),
        sa.CheckConstraint(
            "delivery_scope IN ('shadow','candidate')",
            name="ck_economic_projection_delivery_scope",
        ),
        sa.ForeignKeyConstraint(
            ["serving_generation_id"], ["economic_serving_generations.id"]
        ),
        sa.UniqueConstraint(
            "source_lineage",
            "projection_revision",
            "projection_kind",
            "projection_version",
            "target_representation",
            name="uq_economic_projection_logical_event",
        ),
    )
    op.create_index(
        "ix_economic_projection_generation_scope",
        "economic_taxonomy_projection_events",
        ["serving_generation_id", "delivery_scope"],
    )
    op.create_table(
        "economic_taxonomy_projection_delivery_attempts",
        _id(),
        sa.Column("projection_event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("claimed_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=False, unique=True),
        sa.Column("lease_owner", sa.String(200), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["projection_event_id"], ["economic_taxonomy_projection_events.id"]
        ),
        sa.UniqueConstraint(
            "projection_event_id",
            "attempt_number",
            name="uq_economic_projection_delivery_attempt_number",
        ),
    )
    op.create_table(
        "economic_taxonomy_projection_delivery_events",
        _id(),
        sa.Column("delivery_attempt_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("details", sa.JSON(), nullable=False),
        _created_at("completed_at"),
        sa.CheckConstraint(
            "outcome IN ('success','stale_noop','retryable_failure','terminal_failure')",
            name="ck_economic_projection_delivery_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_attempt_id"],
            ["economic_taxonomy_projection_delivery_attempts.id"],
        ),
    )
    op.create_table(
        "economic_taxonomy_projection_checkpoints",
        sa.Column("target_representation", sa.String(80), nullable=False),
        sa.Column("source_lineage", sa.String(500), nullable=False),
        sa.Column("projection_kind", sa.String(80), nullable=False),
        sa.Column("last_applied_revision", sa.Integer(), nullable=False),
        sa.Column("projection_event_id", sa.Uuid()),
        sa.Column("origin_representation", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at("updated_at"),
        sa.ForeignKeyConstraint(
            ["projection_event_id"], ["economic_taxonomy_projection_events.id"]
        ),
        sa.PrimaryKeyConstraint(
            "target_representation", "source_lineage", "projection_kind"
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "economic_taxonomy_projection_events",
            "economic_taxonomy_projection_delivery_attempts",
            "economic_taxonomy_projection_delivery_events",
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
                )
            )


def downgrade():
    op.drop_table("economic_taxonomy_projection_checkpoints")
    op.drop_table("economic_taxonomy_projection_delivery_events")
    op.drop_table("economic_taxonomy_projection_delivery_attempts")
    op.drop_index(
        "ix_economic_projection_generation_scope",
        table_name="economic_taxonomy_projection_events",
    )
    op.drop_table("economic_taxonomy_projection_events")
