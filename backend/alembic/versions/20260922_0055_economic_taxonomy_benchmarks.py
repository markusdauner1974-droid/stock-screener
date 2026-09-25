"""Add durable Economic Taxonomy benchmark results."""

import sqlalchemy as sa

from alembic import op

revision = "20260922_0055"
down_revision = "20260921_0054"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "economic_taxonomy_benchmark_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("taxonomy_semantic_hash", sa.String(128), nullable=False),
        sa.Column("policy_bundle", sa.String(160), nullable=False),
        sa.Column("fixture_version", sa.Integer(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("report_hash", sa.String(128), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("verified_by", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "passed", name="ck_economic_taxonomy_benchmark_passed"
        ),
        sa.UniqueConstraint(
            "taxonomy_semantic_hash",
            "policy_bundle",
            "report_hash",
            name="uq_economic_taxonomy_benchmark_result",
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_economic_taxonomy_benchmark_results_append_only "
                "BEFORE UPDATE OR DELETE ON economic_taxonomy_benchmark_results "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
            )
        )


def downgrade():
    op.drop_table("economic_taxonomy_benchmark_results")
