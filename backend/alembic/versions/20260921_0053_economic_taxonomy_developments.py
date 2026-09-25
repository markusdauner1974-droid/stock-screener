"""Add narrative provenance and canonical Economic Theme developments."""

from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260921_0053"
down_revision = "20260921_0052"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    migration_run_id = uuid4()

    with op.batch_alter_table("theme_development_events") as batch:
        batch.add_column(sa.Column("canonical_event_key", sa.String(64)))
        batch.add_column(sa.Column("development_identity", sa.Uuid()))

    events = sa.table(
        "theme_development_events",
        sa.column("id", sa.Integer()),
        sa.column("pipeline", sa.String(20)),
        sa.column("event_key", sa.String(64)),
        sa.column("canonical_event_key", sa.String(64)),
        sa.column("development_identity", sa.Uuid()),
    )
    rows = connection.execute(
        sa.select(events.c.id, events.c.pipeline, events.c.event_key).order_by(
            events.c.event_key, events.c.id
        )
    ).all()
    canonical_by_key = {}
    for row in rows:
        canonical_by_key.setdefault(row.event_key, row.id)
    identity_by_event = {
        event_id: uuid4() for event_id in canonical_by_key.values()
    }
    for event_key, event_id in canonical_by_key.items():
        connection.execute(
            events.update()
            .where(events.c.id == event_id)
            .values(
                canonical_event_key=event_key,
                development_identity=identity_by_event[event_id],
            )
        )

    with op.batch_alter_table("theme_development_events") as batch:
        batch.create_unique_constraint(
            "uq_theme_development_canonical_event_key", ["canonical_event_key"]
        )
        batch.create_unique_constraint(
            "uq_theme_development_identity", ["development_identity"]
        )

    with op.batch_alter_table("theme_development_observations") as batch:
        batch.add_column(sa.Column("analysis_channel", sa.String(20)))
        batch.add_column(sa.Column("development_support", sa.String(20)))
        batch.add_column(sa.Column("source_family_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_theme_development_observation_source_family",
            "economic_source_families",
            ["source_family_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.execute(
        sa.text(
            "UPDATE theme_development_observations "
            "SET analysis_channel = pipeline, development_support = 'present'"
        )
    )
    with op.batch_alter_table("theme_development_observations") as batch:
        batch.alter_column("analysis_channel", nullable=False)
        batch.alter_column("development_support", nullable=False)
        batch.create_check_constraint(
            "ck_theme_development_analysis_channel",
            "analysis_channel IN ('technical','fundamental','narrative')",
        )
        batch.create_check_constraint(
            "ck_theme_development_support",
            "development_support IN ('present','absent','unresolved')",
        )

    op.create_table(
        "legacy_development_event_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("old_event_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("canonical_event_id", sa.Integer(), nullable=False),
        sa.Column("old_pipeline", sa.String(20), nullable=False),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["old_event_id"],
            ["theme_development_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_event_id"],
            ["theme_development_events.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_legacy_development_event_mappings_canonical_event_id",
        "legacy_development_event_mappings",
        ["canonical_event_id"],
    )
    op.create_index(
        "ix_legacy_development_event_mappings_migration_run_id",
        "legacy_development_event_mappings",
        ["migration_run_id"],
    )
    mappings = sa.table(
        "legacy_development_event_mappings",
        sa.column("id", sa.Uuid()),
        sa.column("old_event_id", sa.Integer()),
        sa.column("canonical_event_id", sa.Integer()),
        sa.column("old_pipeline", sa.String(20)),
        sa.column("migration_run_id", sa.Uuid()),
    )
    for row in rows:
        connection.execute(
            mappings.insert().values(
                id=uuid4(),
                old_event_id=row.id,
                canonical_event_id=canonical_by_key[row.event_key],
                old_pipeline=row.pipeline,
                migration_run_id=migration_run_id,
            )
        )

    op.create_table(
        "economic_theme_developments",
        sa.Column("observation_id", sa.Integer(), primary_key=True),
        sa.Column("economic_theme_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "link_origin",
            sa.String(32),
            nullable=False,
            server_default="economic_native",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "link_origin IN ('economic_native','legacy_mapping','compatibility')",
            name="ck_economic_theme_development_origin",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["theme_development_observations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["economic_theme_id"],
            ["economic_themes.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_economic_theme_developments_economic_theme_id",
        "economic_theme_developments",
        ["economic_theme_id"],
    )

    observations = sa.table(
        "theme_development_observations",
        sa.column("id", sa.Integer()),
        sa.column("event_id", sa.Integer()),
        sa.column("revision", sa.String(64)),
        sa.column("analysis_channel", sa.String(20)),
        sa.column("development_support", sa.String(20)),
        sa.column("superseded", sa.Boolean()),
    )
    selections = sa.table(
        "economic_development_selection_revisions",
        sa.column("id", sa.Uuid()),
        sa.column("development_identity", sa.Uuid()),
        sa.column("revision_number", sa.Integer()),
        sa.column("selected", sa.Boolean()),
        sa.column("payload", sa.JSON()),
    )
    for event_key, canonical_event_id in canonical_by_key.items():
        family_ids = [row.id for row in rows if row.event_key == event_key]
        current = connection.execute(
            sa.select(
                observations.c.id,
                observations.c.revision,
                observations.c.analysis_channel,
                observations.c.development_support,
            )
            .where(
                observations.c.event_id.in_(family_ids),
                observations.c.superseded.is_(False),
            )
            .order_by(observations.c.id)
        ).all()
        present_ids = [
            row.id for row in current if row.development_support == "present"
        ]
        connection.execute(
            selections.insert().values(
                id=uuid4(),
                development_identity=identity_by_event[canonical_event_id],
                revision_number=1,
                selected=bool(present_ids),
                payload={
                    "canonical_event_id": canonical_event_id,
                    "observation_ids": present_ids,
                    "observations": [
                        {
                            "id": row.id,
                            "analysis_channel": row.analysis_channel,
                            "development_support": row.development_support,
                            "revision": row.revision,
                        }
                        for row in current
                    ],
                },
            )
        )

    if connection.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE TRIGGER trg_legacy_development_event_mappings_append_only "
                "BEFORE UPDATE OR DELETE ON legacy_development_event_mappings "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
            )
        )


def downgrade():
    connection = op.get_bind()
    events = sa.table(
        "theme_development_events",
        sa.column("development_identity", sa.Uuid()),
    )
    selections = sa.table(
        "economic_development_selection_revisions",
        sa.column("development_identity", sa.Uuid()),
    )
    identities = tuple(
        connection.execute(
            sa.select(events.c.development_identity).where(
                events.c.development_identity.is_not(None)
            )
        ).scalars()
    )
    if connection.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS "
                "trg_economic_development_selection_revisions_append_only "
                "ON economic_development_selection_revisions"
            )
        )
    if identities:
        connection.execute(
            selections.delete().where(
                selections.c.development_identity.in_(identities)
            )
        )
    if connection.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE TRIGGER "
                "trg_economic_development_selection_revisions_append_only "
                "BEFORE UPDATE OR DELETE ON "
                "economic_development_selection_revisions "
                "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
            )
        )
    op.drop_table("economic_theme_developments")
    op.drop_table("legacy_development_event_mappings")
    with op.batch_alter_table("theme_development_observations") as batch:
        batch.drop_constraint(
            "ck_theme_development_support", type_="check"
        )
        batch.drop_constraint(
            "ck_theme_development_analysis_channel", type_="check"
        )
        batch.drop_constraint(
            "fk_theme_development_observation_source_family", type_="foreignkey"
        )
        batch.drop_column("source_family_id")
        batch.drop_column("development_support")
        batch.drop_column("analysis_channel")
    with op.batch_alter_table("theme_development_events") as batch:
        batch.drop_constraint("uq_theme_development_identity", type_="unique")
        batch.drop_constraint(
            "uq_theme_development_canonical_event_key", type_="unique"
        )
        batch.drop_column("development_identity")
        batch.drop_column("canonical_event_key")
