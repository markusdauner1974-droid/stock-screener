"""Add canonical Commitments of Traders history and publication state."""

import sqlalchemy as sa
from alembic import op


revision = "20260916_0045"
down_revision = "20260912_0044"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cot_instruments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("cftc_code", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("category_order", sa.Integer(), nullable=False),
        sa.Column("instrument_order", sa.Integer(), nullable=False),
        sa.Column("report_family", sa.String(length=48), nullable=False),
        sa.Column("focal_participant", sa.String(length=40), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("registry_version", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cftc_code"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "cot_import_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("origin", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_report_date", sa.Date(), nullable=True),
        sa.Column("observed_report_date", sa.Date(), nullable=True),
        sa.Column(
            "expected_instrument_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "observed_instrument_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("coverage_json", sa.JSON(), nullable=True),
        sa.Column("diagnostics_json", sa.JSON(), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.Column("registry_version", sa.String(length=64), nullable=False),
        sa.Column("calculation_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cot_import_runs_status",
        "cot_import_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_cot_import_runs_observed_report_date",
        "cot_import_runs",
        ["observed_report_date"],
        unique=False,
    )
    op.create_table(
        "cot_weekly_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("participant", sa.String(length=40), nullable=False),
        sa.Column("long", sa.BigInteger(), nullable=False),
        sa.Column("short", sa.BigInteger(), nullable=False),
        sa.Column("spreading", sa.BigInteger(), nullable=False),
        sa.Column("open_interest", sa.BigInteger(), nullable=False),
        sa.Column("net", sa.BigInteger(), nullable=False),
        sa.Column("delta_long", sa.BigInteger(), nullable=True),
        sa.Column("delta_short", sa.BigInteger(), nullable=True),
        sa.Column("delta_net", sa.BigInteger(), nullable=True),
        sa.Column("net_pct_open_interest", sa.Float(), nullable=True),
        sa.Column("percentile_3y", sa.Float(), nullable=True),
        sa.Column("percentile_status", sa.String(length=32), nullable=False),
        sa.Column("source_dataset_id", sa.String(length=16), nullable=False),
        sa.Column("source_row_id", sa.String(length=160), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("import_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["cot_import_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["cot_instruments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id",
            "report_date",
            "participant",
            name="uq_cot_weekly_position",
        ),
    )
    op.create_index(
        "ix_cot_weekly_instrument_date",
        "cot_weekly_positions",
        ["instrument_id", "report_date"],
        unique=False,
    )
    op.create_table(
        "cot_publication_pointers",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["cot_import_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("cot_publication_pointers")
    op.drop_index(
        "ix_cot_weekly_instrument_date",
        table_name="cot_weekly_positions",
    )
    op.drop_table("cot_weekly_positions")
    op.drop_index(
        "ix_cot_import_runs_observed_report_date",
        table_name="cot_import_runs",
    )
    op.drop_index("ix_cot_import_runs_status", table_name="cot_import_runs")
    op.drop_table("cot_instruments")
    op.drop_table("cot_import_runs")
