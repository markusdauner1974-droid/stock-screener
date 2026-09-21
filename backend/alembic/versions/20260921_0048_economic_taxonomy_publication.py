"""Add Economic Taxonomy publication generations and writer authority."""

import sqlalchemy as sa
from alembic import op


revision = "20260921_0048"
down_revision = "20260921_0047"
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
        "taxonomy_source_revision_log",
        _id(),
        sa.Column("producer_kind", sa.String(80), nullable=False),
        sa.Column("logical_source_key", sa.String(500), nullable=False),
        sa.Column("revision_kind", sa.String(80), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        _created_at("committed_at"),
        sa.UniqueConstraint(
            "producer_kind",
            "logical_source_key",
            "revision_kind",
            "revision_number",
            name="uq_taxonomy_source_revision_identity",
        ),
    )
    op.create_table(
        "economic_semantic_invalidation_revisions",
        _id(),
        sa.Column("revision_number", sa.Integer(), nullable=False, unique=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        _created_at(),
    )
    op.create_table(
        "economic_reader_capability_manifests",
        _id(),
        sa.Column("backend_contract", sa.Integer(), nullable=False),
        sa.Column("frontend_contract", sa.Integer(), nullable=False),
        sa.Column("migration_version", sa.String(80), nullable=False),
        sa.Column("consumer_test_hash", sa.String(128), nullable=False),
        sa.Column("verified_by", sa.String(200), nullable=False),
        _created_at("verified_at"),
        sa.UniqueConstraint(
            "backend_contract",
            "frontend_contract",
            "migration_version",
            "consumer_test_hash",
            name="uq_economic_reader_capability_manifest",
        ),
    )
    op.create_table(
        "economic_generation_input_manifests",
        _id(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expected_parent_generation_id", sa.Uuid()),
        sa.Column(
            "semantic_invalidation_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("committed_revision_tuples", sa.JSON(), nullable=False),
        sa.Column("selections", sa.JSON(), nullable=False),
        sa.Column("semantic_hash", sa.String(128)),
        sa.Column("artifact_integrity_hash", sa.String(128)),
        sa.Column("created_by", sa.String(200), nullable=False),
        _created_at(),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('unsealed','sealed')",
            name="ck_economic_generation_input_manifest_status",
        ),
    )
    op.create_table(
        "economic_reader_snapshot_bundles",
        _id(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "generation_input_manifest_id",
            sa.Uuid(),
            sa.ForeignKey("economic_generation_input_manifests.id"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("semantic_hash", sa.String(128)),
        sa.Column("artifact_integrity_hash", sa.String(128)),
        sa.Column("created_by", sa.String(200), nullable=False),
        _created_at(),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('unsealed','sealed')",
            name="ck_economic_reader_snapshot_bundle_status",
        ),
    )
    op.add_column(
        "economic_interpretation_sets",
        sa.Column("generation_input_manifest_id", sa.Uuid()),
    )
    op.create_foreign_key(
        "fk_economic_interpretation_manifest",
        "economic_interpretation_sets",
        "economic_generation_input_manifests",
        ["generation_input_manifest_id"],
        ["id"],
    )
    op.add_column(
        "economic_metrics_revisions",
        sa.Column("generation_input_manifest_id", sa.Uuid()),
    )
    op.create_foreign_key(
        "fk_economic_metrics_manifest",
        "economic_metrics_revisions",
        "economic_generation_input_manifests",
        ["generation_input_manifest_id"],
        ["id"],
    )
    op.create_table(
        "economic_serving_generations",
        _id(),
        sa.Column("expected_parent_generation_id", sa.Uuid()),
        sa.Column(
            "taxonomy_version_id",
            sa.Uuid(),
            sa.ForeignKey("economic_taxonomy_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "interpretation_set_id",
            sa.Uuid(),
            sa.ForeignKey("economic_interpretation_sets.id"),
            nullable=False,
        ),
        sa.Column(
            "metrics_revision_id",
            sa.Uuid(),
            sa.ForeignKey("economic_metrics_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "generation_input_manifest_id",
            sa.Uuid(),
            sa.ForeignKey("economic_generation_input_manifests.id"),
            nullable=False,
        ),
        sa.Column(
            "reader_snapshot_bundle_id",
            sa.Uuid(),
            sa.ForeignKey("economic_reader_snapshot_bundles.id"),
            nullable=False,
        ),
        sa.Column(
            "reader_capability_manifest_id",
            sa.Uuid(),
            sa.ForeignKey("economic_reader_capability_manifests.id"),
            nullable=False,
        ),
        sa.Column("semantic_hash", sa.String(128), nullable=False),
        sa.Column("artifact_integrity_hash", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["expected_parent_generation_id"],
            ["economic_serving_generations.id"],
            name="fk_economic_generation_expected_parent",
        ),
    )
    op.create_table(
        "economic_serving_generation_events",
        _id(),
        sa.Column(
            "serving_generation_id",
            sa.Uuid(),
            sa.ForeignKey("economic_serving_generations.id"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "event_type IN ('prepared','published','superseded','abandoned')",
            name="ck_economic_serving_generation_event_type",
        ),
        sa.UniqueConstraint(
            "serving_generation_id",
            "sequence_number",
            name="uq_economic_serving_generation_event_sequence",
        ),
    )
    op.create_table(
        "taxonomy_authority",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column(
            "processing_taxonomy_version_id",
            sa.Uuid(),
            sa.ForeignKey("economic_taxonomy_versions.id"),
        ),
        sa.Column("processing_head_revision", sa.Integer(), nullable=False),
        sa.Column(
            "serving_generation_id",
            sa.Uuid(),
            sa.ForeignKey("economic_serving_generations.id"),
        ),
        sa.Column("authority_epoch", sa.Integer(), nullable=False),
        sa.Column("writes_fenced", sa.Boolean(), nullable=False),
        sa.Column("semantic_invalidation_revision", sa.Integer(), nullable=False),
        sa.Column("cutover_catch_up_cursor", sa.JSON(), nullable=False),
        sa.Column("rollback_state", sa.String(40), nullable=False),
        sa.Column("rollback_reason", sa.Text()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_taxonomy_authority_singleton"),
        sa.CheckConstraint(
            "mode IN ('legacy','shadow','dual','economic')",
            name="ck_taxonomy_authority_mode",
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        _create_postgres_triggers()


def _create_postgres_triggers():
    immutable_tables = (
        "taxonomy_source_revision_log",
        "economic_semantic_invalidation_revisions",
        "economic_reader_capability_manifests",
        "economic_serving_generations",
        "economic_serving_generation_events",
    )
    for table in immutable_tables:
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_append_only "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
            )
        )
    for table in (
        "economic_generation_input_manifests",
        "economic_reader_snapshot_bundles",
    ):
        op.execute(
            sa.text(
                f"CREATE TRIGGER trg_{table}_seal_once "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_seal_once()"
            )
        )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION economic_generation_require_coherent_payload()
            RETURNS trigger AS $$
            DECLARE
              taxonomy_status text;
              interpretation_status text;
              interpretation_manifest uuid;
              metrics_status text;
              metrics_manifest uuid;
              manifest_status text;
              snapshot_status text;
              snapshot_manifest uuid;
            BEGIN
              SELECT status INTO taxonomy_status
                FROM economic_taxonomy_versions WHERE id = NEW.taxonomy_version_id;
              SELECT status, generation_input_manifest_id
                INTO interpretation_status, interpretation_manifest
                FROM economic_interpretation_sets WHERE id = NEW.interpretation_set_id;
              SELECT status, generation_input_manifest_id
                INTO metrics_status, metrics_manifest
                FROM economic_metrics_revisions WHERE id = NEW.metrics_revision_id;
              SELECT status INTO manifest_status
                FROM economic_generation_input_manifests
                WHERE id = NEW.generation_input_manifest_id;
              SELECT status, generation_input_manifest_id
                INTO snapshot_status, snapshot_manifest
                FROM economic_reader_snapshot_bundles
                WHERE id = NEW.reader_snapshot_bundle_id;
              IF taxonomy_status <> 'sealed'
                 OR interpretation_status <> 'sealed'
                 OR metrics_status <> 'sealed'
                 OR manifest_status <> 'sealed'
                 OR snapshot_status <> 'sealed' THEN
                RAISE EXCEPTION 'generation_payload_unsealed';
              END IF;
              IF interpretation_manifest IS DISTINCT FROM NEW.generation_input_manifest_id
                 OR metrics_manifest IS DISTINCT FROM NEW.generation_input_manifest_id
                 OR snapshot_manifest IS DISTINCT FROM NEW.generation_input_manifest_id THEN
                RAISE EXCEPTION 'manifest_mismatch';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_economic_generation_coherent_payload
            BEFORE INSERT ON economic_serving_generations
            FOR EACH ROW EXECUTE FUNCTION economic_generation_require_coherent_payload();
            """
        )
    )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS economic_generation_require_coherent_payload() CASCADE"
            )
        )
    op.drop_table("taxonomy_authority")
    op.drop_table("economic_serving_generation_events")
    op.drop_table("economic_serving_generations")
    op.drop_constraint(
        "fk_economic_metrics_manifest",
        "economic_metrics_revisions",
        type_="foreignkey",
    )
    op.drop_column("economic_metrics_revisions", "generation_input_manifest_id")
    op.drop_constraint(
        "fk_economic_interpretation_manifest",
        "economic_interpretation_sets",
        type_="foreignkey",
    )
    op.drop_column("economic_interpretation_sets", "generation_input_manifest_id")
    op.drop_table("economic_reader_snapshot_bundles")
    op.drop_table("economic_generation_input_manifests")
    op.drop_table("economic_reader_capability_manifests")
    op.drop_table("economic_semantic_invalidation_revisions")
    op.drop_table("taxonomy_source_revision_log")

