"""Add generation-scoped reader snapshot payloads and pointers."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_0054"
down_revision = "20260921_0053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "economic_reader_snapshot_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reader_snapshot_bundle_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_kind", sa.String(80), nullable=False),
        sa.Column("resource_key", sa.String(500), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["reader_snapshot_bundle_id"],
            ["economic_reader_snapshot_bundles.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "reader_snapshot_bundle_id",
            "snapshot_kind",
            "resource_key",
            name="uq_economic_reader_snapshot_entry",
        ),
    )
    op.create_table(
        "economic_reader_snapshot_pointers",
        sa.Column("reader_key", sa.String(120), primary_key=True),
        sa.Column("serving_generation_id", sa.Uuid()),
        sa.Column("reader_snapshot_bundle_id", sa.Uuid()),
        sa.Column("authority_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(serving_generation_id IS NULL AND reader_snapshot_bundle_id IS NULL) "
            "OR (serving_generation_id IS NOT NULL AND reader_snapshot_bundle_id IS NOT NULL)",
            name="ck_economic_reader_snapshot_pointer_complete",
        ),
        sa.ForeignKeyConstraint(
            ["serving_generation_id"], ["economic_serving_generations.id"]
        ),
        sa.ForeignKeyConstraint(
            ["reader_snapshot_bundle_id"],
            ["economic_reader_snapshot_bundles.id"],
        ),
    )
    pointers = sa.table(
        "economic_reader_snapshot_pointers",
        sa.column("reader_key", sa.String(120)),
        sa.column("authority_epoch", sa.Integer()),
    )
    op.bulk_insert(
        pointers,
        [
            {"reader_key": "economic_themes", "authority_epoch": 0},
            {"reader_key": "economic_taxonomy", "authority_epoch": 0},
        ],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION economic_runtime_guard_snapshot_child()
                RETURNS trigger AS $$
                DECLARE
                  bundle_id uuid;
                BEGIN
                  bundle_id := CASE WHEN TG_OP = 'DELETE'
                                    THEN OLD.reader_snapshot_bundle_id
                                    ELSE NEW.reader_snapshot_bundle_id END;
                  IF EXISTS (
                    SELECT 1 FROM economic_reader_snapshot_bundles
                    WHERE id = bundle_id AND status = 'sealed'
                    FOR KEY SHARE
                  ) THEN
                    RAISE EXCEPTION 'sealed_payload_immutable';
                  END IF;
                  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_economic_reader_snapshot_entry_parent_open "
                "BEFORE INSERT OR UPDATE OR DELETE "
                "ON economic_reader_snapshot_entries "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_guard_snapshot_child()"
            )
        )


def downgrade():
    op.drop_table("economic_reader_snapshot_pointers")
    op.drop_table("economic_reader_snapshot_entries")
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text("DROP FUNCTION IF EXISTS economic_runtime_guard_snapshot_child()")
        )
