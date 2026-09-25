"""Add reader snapshot payloads and reviewed migration state."""

import sqlalchemy as sa

from alembic import op

revision = "20260921_0054"
down_revision = "20260921_0053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "taxonomy_migration_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("dataset_manifest", sa.JSON(), nullable=False),
        sa.Column("source_hashes", sa.JSON(), nullable=False),
        sa.Column("taxonomy_semantic_hash", sa.String(128), nullable=False),
        sa.Column(
            "taxonomy_artifact_integrity_hash", sa.String(128), nullable=False
        ),
        sa.Column("policy_bundle", sa.JSON(), nullable=False),
        sa.Column("policy_bundle_hash", sa.String(128), nullable=False),
        sa.Column("migration_policy_version", sa.String(120), nullable=False),
        sa.Column("input_semantic_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("artifact_integrity_hash", sa.String(128)),
        sa.Column("identity_count", sa.Integer(), nullable=False),
        sa.Column(
            "reviewed_identity_count_cache",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "coverage_complete_cache",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('unsealed','sealed')",
            name="ck_taxonomy_migration_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id"],
            ["economic_taxonomy_versions.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "taxonomy_migration_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_theme_cluster_id", sa.Integer(), nullable=False),
        sa.Column("review_revision", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=False),
        sa.Column("destination_theme_ids", sa.JSON(), nullable=False),
        sa.Column("allocations", sa.JSON(), nullable=False),
        sa.Column("reviewer_subject", sa.String(200), nullable=False),
        sa.Column("reviewer_auth_method", sa.String(120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("semantic_hash", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "disposition IN ('mapped','split_required','merged_equivalent',"
            "'not_a_theme','deferred')",
            name="ck_taxonomy_migration_review_disposition",
        ),
        sa.ForeignKeyConstraint(
            ["migration_run_id"], ["taxonomy_migration_runs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "migration_run_id",
            "legacy_theme_cluster_id",
            "review_revision",
            name="uq_taxonomy_migration_review_revision",
        ),
    )
    op.create_table(
        "taxonomy_migration_progress_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("actor_auth_method", sa.String(120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('started','progress','paused','failed','reviewed',"
            "'replayed','completed')",
            name="ck_taxonomy_migration_progress_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["migration_run_id"], ["taxonomy_migration_runs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "migration_run_id",
            "sequence_number",
            name="uq_taxonomy_migration_progress_event_sequence",
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION economic_migration_run_guard()
                RETURNS trigger AS $$
                BEGIN
                  IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'migration_run_inputs_immutable';
                  END IF;
                  IF OLD.status = 'sealed' THEN
                    IF (to_jsonb(NEW) - ARRAY['reviewed_identity_count_cache','coverage_complete_cache']::text[])
                       IS DISTINCT FROM
                       (to_jsonb(OLD) - ARRAY['reviewed_identity_count_cache','coverage_complete_cache']::text[]) THEN
                      RAISE EXCEPTION 'migration_run_inputs_immutable';
                    END IF;
                    RETURN NEW;
                  END IF;
                  IF NEW.status <> 'sealed'
                     OR NEW.artifact_integrity_hash IS NULL
                     OR NEW.sealed_at IS NULL
                     OR (to_jsonb(NEW) - ARRAY['status','artifact_integrity_hash','sealed_at']::text[])
                        IS DISTINCT FROM
                        (to_jsonb(OLD) - ARRAY['status','artifact_integrity_hash','sealed_at']::text[]) THEN
                    RAISE EXCEPTION 'migration_run_inputs_immutable';
                  END IF;
                  RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_taxonomy_migration_run_guard "
                "BEFORE UPDATE OR DELETE ON taxonomy_migration_runs "
                "FOR EACH ROW EXECUTE FUNCTION economic_migration_run_guard()"
            )
        )
        for table_name in (
            "taxonomy_migration_reviews",
            "taxonomy_migration_progress_events",
        ):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table_name}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table_name} "
                    "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
                )
            )
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
    op.drop_table("taxonomy_migration_progress_events")
    op.drop_table("taxonomy_migration_reviews")
    op.drop_table("taxonomy_migration_runs")
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION IF EXISTS economic_migration_run_guard()"))
