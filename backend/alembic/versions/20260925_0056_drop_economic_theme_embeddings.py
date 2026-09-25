"""Drop the never-populated Economic Theme embedding cache."""

import sqlalchemy as sa

from alembic import op

revision = "20260925_0056"
down_revision = "20260922_0055"
branch_labels = None
depends_on = None


def upgrade():
    # The append-only trigger created in 20260921_0047 is dropped with the table.
    op.drop_table("economic_theme_embeddings")


def downgrade():
    op.create_table(
        "economic_theme_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "economic_theme_id",
            sa.Uuid(),
            sa.ForeignKey("economic_themes.id"),
            nullable=False,
        ),
        sa.Column("taxonomy_semantic_hash", sa.String(128), nullable=False),
        sa.Column("source_text_hash", sa.String(128), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "economic_theme_id",
            "taxonomy_semantic_hash",
            "source_text_hash",
            "embedding_model",
            "model_version",
            name="uq_economic_theme_embedding_cache_key",
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_economic_theme_embeddings_append_only "
                "BEFORE UPDATE OR DELETE ON economic_theme_embeddings "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
            )
        )
