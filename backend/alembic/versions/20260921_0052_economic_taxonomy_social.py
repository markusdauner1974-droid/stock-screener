"""Add global Economic Taxonomy Social association history."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_0052"
down_revision = "20260921_0051"
branch_labels = None
depends_on = None


def _uuid_id():
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
        "economic_social_associations",
        _uuid_id(),
        sa.Column("economic_theme_id", sa.Uuid(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["economic_theme_id"], ["economic_themes.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["security_id"], ["stock_universe.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "economic_theme_id",
            "security_id",
            name="uq_economic_social_theme_security",
        ),
    )
    op.create_table(
        "economic_social_decision_revisions",
        _uuid_id(),
        sa.Column("association_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(240), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "state IN ('proposed','accepted','rejected','conflict_review_required')",
            name="ck_economic_social_decision_state",
        ),
        sa.ForeignKeyConstraint(
            ["association_id"],
            ["economic_social_associations.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "association_id",
            "revision_number",
            name="uq_economic_social_decision_revision",
        ),
        sa.UniqueConstraint(
            "association_id",
            "idempotency_key",
            name="uq_economic_social_decision_idempotency",
        ),
    )
    op.create_table(
        "economic_social_association_revisions",
        _uuid_id(),
        sa.Column("association_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("decision_revision_id", sa.Uuid()),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("live", sa.Boolean(), nullable=False),
        sa.Column("admission_state", sa.String(24), nullable=False),
        sa.Column("mirror_state", sa.String(24), nullable=False),
        sa.Column("evidence_packet_id", sa.Uuid()),
        sa.Column("projection_event_id", sa.Uuid()),
        sa.Column("reconciliation_hash", sa.String(128), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "state IN ('proposed','accepted','rejected','conflict_review_required','pending_legacy_mirror')",
            name="ck_economic_social_association_state",
        ),
        sa.CheckConstraint(
            "admission_state IN ('live','review_only')",
            name="ck_economic_social_admission_state",
        ),
        sa.CheckConstraint(
            "mirror_state IN ('not_required','pending','acknowledged')",
            name="ck_economic_social_mirror_state",
        ),
        sa.CheckConstraint(
            "NOT live OR (state = 'accepted' AND admission_state = 'live' AND mirror_state != 'pending')",
            name="ck_economic_social_live_state",
        ),
        sa.ForeignKeyConstraint(
            ["association_id"],
            ["economic_social_associations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_revision_id"],
            ["economic_social_decision_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_packet_id"],
            ["economic_evidence_packets.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["projection_event_id"],
            ["economic_taxonomy_projection_events.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "association_id",
            "revision_number",
            name="uq_economic_social_association_revision",
        ),
        sa.UniqueConstraint(
            "association_id",
            "reconciliation_hash",
            name="uq_economic_social_association_reconciliation",
        ),
    )
    op.create_table(
        "economic_social_association_sources",
        _uuid_id(),
        sa.Column("association_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("source_key", sa.String(500), nullable=False),
        sa.Column("legacy_association_id", sa.Integer()),
        sa.Column("social_work_id", sa.Integer()),
        sa.Column("evidence_packet_id", sa.Uuid()),
        _created_at(),
        sa.CheckConstraint(
            "source_kind IN ('legacy_association','social_work','economic_native')",
            name="ck_economic_social_source_kind",
        ),
        sa.ForeignKeyConstraint(
            ["association_id"],
            ["economic_social_associations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["legacy_association_id"],
            ["social_theme_associations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["social_work_id"],
            ["social_extraction_work.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_packet_id"],
            ["economic_evidence_packets.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "association_id",
            "source_kind",
            "source_key",
            name="uq_economic_social_association_source",
        ),
    )

    op.add_column(
        "social_llm_attempts",
        sa.Column("logical_operation_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "social_llm_attempts",
        sa.Column("operation_kind", sa.Text(), nullable=True),
    )
    op.add_column(
        "social_llm_attempts",
        sa.Column("attempt_number", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE social_llm_attempts "
            "SET logical_operation_key = idempotency_key, "
            "operation_kind = 'legacy_social_extraction', attempt_number = 1"
        )
    )
    with op.batch_alter_table("social_llm_attempts") as batch:
        batch.alter_column("logical_operation_key", nullable=False)
        batch.alter_column("operation_kind", nullable=False)
        batch.alter_column("attempt_number", nullable=False)
        batch.create_unique_constraint(
            "uq_social_llm_logical_attempt",
            ["logical_operation_key", "operation_kind", "attempt_number"],
        )
        batch.create_check_constraint("ck_social_attempt_number", "attempt_number >= 1")

    if op.get_bind().dialect.name == "postgresql":
        for table in (
            "economic_social_associations",
            "economic_social_decision_revisions",
            "economic_social_association_revisions",
            "economic_social_association_sources",
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
                )
            )


def downgrade():
    with op.batch_alter_table("social_llm_attempts") as batch:
        batch.drop_constraint("ck_social_attempt_number", type_="check")
        batch.drop_constraint("uq_social_llm_logical_attempt", type_="unique")
        batch.drop_column("attempt_number")
        batch.drop_column("operation_kind")
        batch.drop_column("logical_operation_key")
    op.drop_table("economic_social_association_sources")
    op.drop_table("economic_social_association_revisions")
    op.drop_table("economic_social_decision_revisions")
    op.drop_table("economic_social_associations")
