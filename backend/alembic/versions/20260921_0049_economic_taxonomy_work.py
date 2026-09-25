"""Admit frozen evidence and lease Economic Taxonomy work."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_0049"
down_revision = "20260921_0048"
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
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Task 2 treated the identity-only request as immutable. Task 5 makes
        # its lease fields explicitly operational while all semantic work and
        # provider outcomes remain append-only child events.
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS "
                "trg_economic_processing_requests_append_only "
                "ON economic_processing_requests"
            )
        )

    with op.batch_alter_table("economic_processing_requests") as batch:
        batch.add_column(
            sa.Column("status", sa.String(32), nullable=False, server_default="pending")
        )
        batch.add_column(
            sa.Column(
                "available_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.add_column(sa.Column("lease_token", sa.Uuid()))
        batch.add_column(sa.Column("lease_owner", sa.String(200)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("observed_processing_head_revision", sa.Integer()))
        batch.add_column(sa.Column("observed_authority_epoch", sa.Integer()))
        batch.add_column(sa.Column("completion_code", sa.String(80)))
        batch.add_column(sa.Column("result_payload", sa.JSON()))
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            )
        )
        batch.create_check_constraint(
            "ck_economic_processing_request_status",
            "status IN ('pending','leased','retryable','completed','terminal_failure')",
        )
        batch.create_check_constraint(
            "ck_economic_processing_request_lease_shape",
            "(status = 'leased' AND lease_token IS NOT NULL "
            "AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'leased' AND lease_token IS NULL "
            "AND lease_owner IS NULL AND lease_expires_at IS NULL)",
        )
        batch.create_index(
            "ix_economic_processing_request_claim",
            ["status", "available_at", "lease_expires_at"],
        )

    op.create_table(
        "economic_processing_request_events",
        _id(),
        sa.Column(
            "processing_request_id",
            sa.Uuid(),
            sa.ForeignKey("economic_processing_requests.id"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "processing_request_id",
            "sequence_number",
            name="uq_economic_processing_request_event_sequence",
        ),
    )
    op.create_table(
        "economic_provider_attempts",
        _id(),
        sa.Column(
            "logical_request_id",
            sa.Uuid(),
            sa.ForeignKey("economic_processing_requests.id"),
            nullable=False,
        ),
        sa.Column("operation_kind", sa.String(80), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("dispatch_id", sa.String(200), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "logical_request_id",
            "operation_kind",
            "attempt_number",
            name="uq_economic_provider_attempt_number",
        ),
        sa.UniqueConstraint(
            "logical_request_id",
            "operation_kind",
            "dispatch_id",
            name="uq_economic_provider_attempt_dispatch",
        ),
    )
    op.create_table(
        "economic_provider_attempt_events",
        _id(),
        sa.Column(
            "provider_attempt_id",
            sa.Uuid(),
            sa.ForeignKey("economic_provider_attempts.id"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("result_artifact_id", sa.Uuid()),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "outcome IN ('success','retryable_failure','uncertain','terminal_failure')",
            name="ck_economic_provider_attempt_event_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'success' AND result_artifact_id IS NOT NULL) OR "
            "(outcome <> 'success' AND result_artifact_id IS NULL)",
            name="ck_economic_provider_attempt_result_shape",
        ),
        sa.UniqueConstraint(
            "provider_attempt_id",
            "sequence_number",
            name="uq_economic_provider_attempt_event_sequence",
        ),
    )
    op.create_table(
        "economic_exposure_candidates",
        _id(),
        sa.Column(
            "processing_request_id",
            sa.Uuid(),
            sa.ForeignKey("economic_processing_requests.id"),
            nullable=False,
        ),
        sa.Column("candidate_key", sa.String(160), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "processing_request_id",
            "candidate_key",
            name="uq_economic_exposure_candidate_key",
        ),
    )
    op.create_table(
        "economic_dimension_proposals",
        _id(),
        sa.Column(
            "processing_request_id",
            sa.Uuid(),
            sa.ForeignKey("economic_processing_requests.id"),
            nullable=False,
        ),
        sa.Column("dimension_key", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "processing_request_id",
            "dimension_key",
            name="uq_economic_dimension_proposal_key",
        ),
    )
    op.create_table(
        "economic_naming_proposals",
        _id(),
        sa.Column(
            "processing_request_id",
            sa.Uuid(),
            sa.ForeignKey("economic_processing_requests.id"),
            nullable=False,
        ),
        sa.Column("proposal_key", sa.String(160), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "processing_request_id",
            "proposal_key",
            name="uq_economic_naming_proposal_key",
        ),
    )

    if bind.dialect.name == "postgresql":
        for table in (
            "economic_processing_request_events",
            "economic_provider_attempts",
            "economic_provider_attempt_events",
            "economic_exposure_candidates",
            "economic_dimension_proposals",
            "economic_naming_proposals",
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
                )
            )


def downgrade():
    bind = op.get_bind()
    for table in (
        "economic_naming_proposals",
        "economic_dimension_proposals",
        "economic_exposure_candidates",
        "economic_provider_attempt_events",
        "economic_provider_attempts",
        "economic_processing_request_events",
    ):
        op.drop_table(table)

    with op.batch_alter_table("economic_processing_requests") as batch:
        batch.drop_index("ix_economic_processing_request_claim")
        batch.drop_constraint(
            "ck_economic_processing_request_lease_shape", type_="check"
        )
        batch.drop_constraint("ck_economic_processing_request_status", type_="check")
        for column in (
            "updated_at",
            "result_payload",
            "completion_code",
            "observed_authority_epoch",
            "observed_processing_head_revision",
            "lease_expires_at",
            "lease_owner",
            "lease_token",
            "available_at",
            "status",
        ):
            batch.drop_column(column)

    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_economic_processing_requests_append_only "
                "BEFORE UPDATE OR DELETE ON economic_processing_requests "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
            )
        )
