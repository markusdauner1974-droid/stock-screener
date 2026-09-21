"""Add stable Economic Theme identities and sealed semantic snapshots."""

import sqlalchemy as sa
from alembic import op


revision = "20260921_0046"
down_revision = "20260916_0045"
branch_labels = None
depends_on = None


def _timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def upgrade():
    op.create_table(
        "economic_taxonomy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("semantic_hash", sa.String(length=64), nullable=True),
        sa.Column("artifact_integrity_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        _timestamp_column("created_at"),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft','sealed')",
            name="ck_economic_taxonomy_version_status",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["economic_taxonomy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "economic_themes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("semantic_key", sa.Uuid(), nullable=False),
        sa.Column("identity_origin", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        _timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("semantic_key"),
    )
    op.create_table(
        "economic_theme_revisions",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("theme_id", sa.Uuid(), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=False),
        sa.Column("lifecycle", sa.String(length=24), nullable=False),
        sa.Column(
            "lifecycle_policy_version", sa.String(length=80), nullable=False
        ),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        sa.CheckConstraint(
            "lifecycle IN ('provisional','established','dormant','reactivated','retired')",
            name="ck_economic_theme_revision_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id"],
            ["economic_taxonomy_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["theme_id"], ["economic_themes.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("taxonomy_version_id", "theme_id"),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_theme_revision_logical_row",
        ),
    )
    op.create_table(
        "economic_theme_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("theme_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=240), nullable=False),
        sa.Column("normalized_alias", sa.String(length=240), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "theme_id"],
            [
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ],
            name="fk_economic_alias_same_snapshot_theme",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "theme_id",
            "normalized_alias",
            name="uq_economic_alias_per_theme_snapshot",
        ),
    )
    op.create_table(
        "economic_facet_dimensions",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("inclusion_semantics", sa.Text(), nullable=False),
        sa.Column("exclusion_semantics", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=40), nullable=False),
        sa.Column("cardinality", sa.String(length=24), nullable=False),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("normalization_policy", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        sa.CheckConstraint(
            "cardinality IN ('one','many')",
            name="ck_economic_facet_dimension_cardinality",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id"],
            ["economic_taxonomy_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("taxonomy_version_id", "key"),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_facet_dimension_logical_row",
        ),
    )
    op.create_table(
        "economic_facet_values",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("dimension_key", sa.String(length=80), nullable=False),
        sa.Column("normalized_value", sa.String(length=240), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("display_value", sa.String(length=240), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "dimension_key"],
            [
                "economic_facet_dimensions.taxonomy_version_id",
                "economic_facet_dimensions.key",
            ],
            name="fk_economic_facet_value_same_snapshot_dimension",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "taxonomy_version_id", "dimension_key", "normalized_value"
        ),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_facet_value_logical_row",
        ),
    )
    op.create_table(
        "economic_theme_facets",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("theme_id", sa.Uuid(), nullable=False),
        sa.Column("dimension_key", sa.String(length=80), nullable=False),
        sa.Column("normalized_value", sa.String(length=240), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "theme_id"],
            [
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ],
            name="fk_economic_theme_facet_same_snapshot_theme",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "dimension_key", "normalized_value"],
            [
                "economic_facet_values.taxonomy_version_id",
                "economic_facet_values.dimension_key",
                "economic_facet_values.normalized_value",
            ],
            name="fk_economic_theme_facet_same_snapshot_value",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "taxonomy_version_id",
            "theme_id",
            "dimension_key",
            "normalized_value",
        ),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_theme_facet_logical_row",
        ),
    )
    op.create_table(
        "economic_theme_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_theme_id", sa.Uuid(), nullable=False),
        sa.Column("target_theme_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("direction", sa.String(length=24), nullable=False),
        sa.Column(
            "discriminator", sa.String(length=240), nullable=False, server_default=""
        ),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        sa.CheckConstraint(
            "kind IN ('specialization','equivalent','distinct')",
            name="ck_economic_relationship_kind",
        ),
        sa.CheckConstraint(
            "source_theme_id <> target_theme_id",
            name="ck_economic_relationship_distinct_endpoints",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "source_theme_id"],
            [
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ],
            name="fk_economic_relationship_same_snapshot_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "target_theme_id"],
            [
                "economic_theme_revisions.taxonomy_version_id",
                "economic_theme_revisions.theme_id",
            ],
            name="fk_economic_relationship_same_snapshot_target",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "source_theme_id",
            "target_theme_id",
            "kind",
            "direction",
            "discriminator",
            name="uq_economic_relationship_canonical",
        ),
    )
    op.create_table(
        "economic_taxonomy_policies",
        sa.Column("taxonomy_version_id", sa.Uuid(), nullable=False),
        sa.Column("policy_kind", sa.String(length=80), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("logical_row_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        _timestamp_column("created_at"),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id"],
            ["economic_taxonomy_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("taxonomy_version_id", "policy_kind"),
        sa.UniqueConstraint(
            "taxonomy_version_id",
            "logical_row_id",
            name="uq_economic_taxonomy_policy_logical_row",
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        _create_postgres_triggers()


def _create_postgres_triggers():
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION economic_taxonomy_reject_sealed_version_mutation()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' AND OLD.status = 'sealed' THEN
                RAISE EXCEPTION 'sealed_snapshot_immutable';
              END IF;
              IF TG_OP = 'UPDATE' THEN
                IF OLD.id IS DISTINCT FROM NEW.id THEN
                  RAISE EXCEPTION 'taxonomy_version_identity_immutable';
                END IF;
                IF OLD.status = 'sealed' THEN
                  RAISE EXCEPTION 'sealed_snapshot_immutable';
                END IF;
              END IF;
              RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION economic_taxonomy_reject_theme_identity_mutation()
            RETURNS trigger AS $$
            BEGIN
              IF OLD.id IS DISTINCT FROM NEW.id OR OLD.semantic_key IS DISTINCT FROM NEW.semantic_key THEN
                RAISE EXCEPTION 'theme_semantic_key_immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION economic_taxonomy_reject_sealed_owned_mutation()
            RETURNS trigger AS $$
            DECLARE
              target_version uuid;
              target_status text;
            BEGIN
              IF TG_OP = 'UPDATE' AND NEW.taxonomy_version_id IS DISTINCT FROM OLD.taxonomy_version_id THEN
                RAISE EXCEPTION 'version_owned_row_move';
              END IF;
              target_version := CASE WHEN TG_OP = 'DELETE' THEN OLD.taxonomy_version_id ELSE NEW.taxonomy_version_id END;
              SELECT status INTO target_status
                FROM economic_taxonomy_versions
                WHERE id = target_version
                FOR KEY SHARE;
              IF target_status = 'sealed' THEN
                RAISE EXCEPTION 'sealed_snapshot_immutable';
              END IF;
              RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_economic_taxonomy_version_immutable
            BEFORE UPDATE OR DELETE ON economic_taxonomy_versions
            FOR EACH ROW EXECUTE FUNCTION economic_taxonomy_reject_sealed_version_mutation()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_economic_theme_identity_immutable
            BEFORE UPDATE ON economic_themes
            FOR EACH ROW EXECUTE FUNCTION economic_taxonomy_reject_theme_identity_mutation()
            """
        )
    )
    for table_name in (
        "economic_theme_revisions",
        "economic_theme_aliases",
        "economic_facet_dimensions",
        "economic_facet_values",
        "economic_theme_facets",
        "economic_theme_relationships",
        "economic_taxonomy_policies",
    ):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_immutable
                BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION economic_taxonomy_reject_sealed_owned_mutation()
                """
            )
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for table_name in (
            "economic_theme_revisions",
            "economic_theme_aliases",
            "economic_facet_dimensions",
            "economic_facet_values",
            "economic_theme_facets",
            "economic_theme_relationships",
            "economic_taxonomy_policies",
        ):
            op.execute(
                sa.text(
                    f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}"
                )
            )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_economic_theme_identity_immutable ON economic_themes"
            )
        )
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS trg_economic_taxonomy_version_immutable ON economic_taxonomy_versions"
            )
        )
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS economic_taxonomy_reject_sealed_owned_mutation()"
            )
        )
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS economic_taxonomy_reject_theme_identity_mutation()"
            )
        )
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS economic_taxonomy_reject_sealed_version_mutation()"
            )
        )

    op.drop_table("economic_taxonomy_policies")
    op.drop_table("economic_theme_relationships")
    op.drop_table("economic_theme_facets")
    op.drop_table("economic_facet_values")
    op.drop_table("economic_facet_dimensions")
    op.drop_table("economic_theme_aliases")
    op.drop_table("economic_theme_revisions")
    op.drop_table("economic_themes")
    op.drop_table("economic_taxonomy_versions")
