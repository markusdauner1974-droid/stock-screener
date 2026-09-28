"""Add workload_fences for commit-time fencing of Redis workload leases."""

import sqlalchemy as sa

from alembic import op

revision = "20260928_0061"
down_revision = "20260926_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workload_fences",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workload_fences")
