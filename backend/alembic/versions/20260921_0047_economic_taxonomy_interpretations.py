"""Persist immutable Economic Theme evidence and interpretation history."""

import sqlalchemy as sa
from alembic import op


revision = "20260921_0047"
down_revision = "20260921_0046"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _created_at():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


def _fk(name, target, *, nullable=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), nullable=nullable)


def _schema():
    """Return a migration-local schema, insulated from future ORM changes."""

    metadata = sa.MetaData()
    # External tables are declarations only and are deliberately not returned.
    sa.Table("economic_taxonomy_versions", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("economic_themes", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("stock_universe", metadata, sa.Column("id", sa.Integer(), primary_key=True))

    family = sa.Table(
        "economic_source_families",
        metadata,
        _id(),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("canonical_source_key", sa.String(500), nullable=False, unique=True),
        sa.Column("canonical_item_id", sa.String(240)),
        _created_at(),
    )
    lineage = sa.Table(
        "economic_source_lineages",
        metadata,
        _id(),
        _fk("source_family_id", "economic_source_families.id"),
        sa.Column("scope_suffix", sa.String(240), nullable=False, server_default=""),
        sa.Column("admission_policy_key", sa.String(120)),
        _created_at(),
        sa.UniqueConstraint(
            "source_family_id", "scope_suffix", name="uq_economic_source_lineage_scope"
        ),
        sa.CheckConstraint(
            "scope_suffix = '' OR admission_policy_key IS NOT NULL",
            name="ck_economic_source_lineage_scoped_policy",
        ),
    )
    packet = sa.Table(
        "economic_evidence_packets",
        metadata,
        _id(),
        _fk("source_lineage_id", "economic_source_lineages.id"),
        sa.Column("evidence_revision_ordinal", sa.Integer(), nullable=False),
        sa.Column("packet_hash", sa.String(128), nullable=False),
        sa.Column("evidence_content_fingerprint", sa.String(128), nullable=False),
        sa.Column("provider_revision_id", sa.String(240)),
        sa.Column("provider_revision_order", sa.String(240)),
        sa.Column("capture_route", sa.String(80), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        _fk("supersedes_evidence_packet_id", "economic_evidence_packets.id", nullable=True),
        _fk("equivalent_evidence_packet_id", "economic_evidence_packets.id", nullable=True),
        sa.Column("precedence_state", sa.String(32), nullable=False),
        sa.Column("original_text_ref", sa.Text(), nullable=False),
        sa.Column("translated_text_ref", sa.Text()),
        sa.Column("translation_version", sa.String(120)),
        sa.Column("attachment_hashes", sa.JSON(), nullable=False),
        sa.Column("extracted_text_hashes", sa.JSON(), nullable=False),
        sa.Column("grounding_snapshot", sa.JSON(), nullable=False),
        sa.Column("preparation_version", sa.String(120), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "source_lineage_id",
            "evidence_revision_ordinal",
            name="uq_economic_evidence_lineage_ordinal",
        ),
        sa.UniqueConstraint(
            "source_lineage_id", "packet_hash", name="uq_economic_evidence_packet_hash"
        ),
        sa.CheckConstraint(
            "precedence_state IN ('effective','superseded','equivalent','hold_review')",
            name="ck_economic_evidence_precedence_state",
        ),
    )
    precedence = sa.Table(
        "economic_evidence_precedence_revisions",
        metadata,
        _id(),
        _fk("source_lineage_id", "economic_source_lineages.id"),
        _fk("evidence_packet_id", "economic_evidence_packets.id"),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        _fk("related_evidence_packet_id", "economic_evidence_packets.id", nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "source_lineage_id",
            "evidence_packet_id",
            "revision_number",
            name="uq_economic_evidence_precedence_revision",
        ),
    )
    lens = sa.Table(
        "economic_lens_eligibility_revisions",
        metadata,
        _id(),
        _fk("source_lineage_id", "economic_source_lineages.id"),
        _fk("evidence_packet_id", "economic_evidence_packets.id"),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("evidence_channels", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "source_lineage_id",
            "evidence_packet_id",
            "revision_number",
            name="uq_economic_lens_eligibility_revision",
        ),
    )
    request = sa.Table(
        "economic_processing_requests",
        metadata,
        _id(),
        _fk("source_lineage_id", "economic_source_lineages.id"),
        _fk("evidence_packet_id", "economic_evidence_packets.id"),
        sa.Column("policy_bundle_version", sa.String(160), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "source_lineage_id",
            "evidence_packet_id",
            "policy_bundle_version",
            name="uq_economic_processing_request_identity",
        ),
    )
    extraction = sa.Table(
        "economic_extraction_artifacts",
        metadata,
        _id(),
        _fk("evidence_packet_id", "economic_evidence_packets.id"),
        sa.Column("extraction_policy_version", sa.String(120), nullable=False),
        sa.Column("result_status", sa.String(40), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("provider_response_hash", sa.String(128)),
        _created_at(),
        sa.UniqueConstraint(
            "evidence_packet_id",
            "extraction_policy_version",
            name="uq_economic_extraction_artifact_key",
        ),
    )
    review = sa.Table(
        "economic_claim_review_artifacts",
        metadata,
        _id(),
        _fk("extraction_artifact_id", "economic_extraction_artifacts.id"),
        sa.Column("claim_review_policy_version", sa.String(120), nullable=False),
        sa.Column("facet_catalog_semantic_hash", sa.String(128), nullable=False),
        sa.Column("result_status", sa.String(40), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("provider_response_hash", sa.String(128)),
        _created_at(),
        sa.UniqueConstraint(
            "extraction_artifact_id",
            "claim_review_policy_version",
            "facet_catalog_semantic_hash",
            name="uq_economic_claim_review_artifact_key",
        ),
    )
    attempt = sa.Table(
        "economic_classification_attempts",
        metadata,
        _id(),
        _fk("processing_request_id", "economic_processing_requests.id"),
        _fk("claim_review_artifact_id", "economic_claim_review_artifacts.id"),
        _fk("input_taxonomy_version_id", "economic_taxonomy_versions.id"),
        _fk("output_taxonomy_version_id", "economic_taxonomy_versions.id", nullable=True),
        sa.Column("resolver_policy_version", sa.String(120), nullable=False),
        sa.Column("naming_policy_version", sa.String(120), nullable=False),
        sa.Column("derivation_policy_version", sa.String(120), nullable=False),
        sa.Column("result_status", sa.String(40), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "processing_request_id",
            "claim_review_artifact_id",
            "input_taxonomy_version_id",
            "resolver_policy_version",
            "naming_policy_version",
            "derivation_policy_version",
            name="uq_economic_classification_attempt_key",
        ),
    )
    attempt_event = sa.Table(
        "economic_classification_attempt_events",
        metadata,
        _id(),
        _fk("classification_attempt_id", "economic_classification_attempts.id"),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "classification_attempt_id",
            "sequence_number",
            name="uq_economic_classification_attempt_event_sequence",
        ),
    )
    assignment = sa.Table(
        "economic_claim_assignments",
        metadata,
        _id(),
        _fk("classification_attempt_id", "economic_classification_attempts.id"),
        sa.Column("claim_fingerprint", sa.String(128), nullable=False),
        _fk("economic_theme_id", "economic_themes.id"),
        sa.Column("exposure_support", sa.String(40), nullable=False),
        sa.Column("claim_payload", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "classification_attempt_id",
            "claim_fingerprint",
            "economic_theme_id",
            name="uq_economic_claim_assignment_identity",
        ),
    )
    override = sa.Table(
        "economic_interpretation_override_revisions",
        metadata,
        _id(),
        _fk("source_lineage_id", "economic_source_lineages.id"),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("override_kind", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "source_lineage_id",
            "revision_number",
            name="uq_economic_interpretation_override_revision",
        ),
    )
    social_ref = sa.Table(
        "economic_social_association_revision_refs",
        metadata,
        _id(),
        sa.Column("association_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("decision_revision_id", sa.Uuid()),
        _created_at(),
        sa.UniqueConstraint(
            "association_id",
            "revision_number",
            name="uq_economic_social_association_revision_ref",
        ),
    )
    constituent_decision = sa.Table(
        "economic_constituent_decision_revisions",
        metadata,
        _id(),
        _fk("association_revision_ref_id", "economic_social_association_revision_refs.id"),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "association_revision_ref_id",
            "revision_number",
            name="uq_economic_constituent_decision_revision",
        ),
    )
    proposal_decision = sa.Table(
        "economic_proposal_decision_revisions",
        metadata,
        _id(),
        sa.Column("proposal_identity", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "proposal_identity",
            "revision_number",
            name="uq_economic_proposal_decision_revision",
        ),
    )
    development_selection = sa.Table(
        "economic_development_selection_revisions",
        metadata,
        _id(),
        sa.Column("development_identity", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "development_identity",
            "revision_number",
            name="uq_economic_development_selection_revision",
        ),
    )
    interpretation = sa.Table(
        "economic_interpretation_sets",
        metadata,
        _id(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("semantic_hash", sa.String(128)),
        sa.Column("artifact_integrity_hash", sa.String(128)),
        sa.Column("created_by", sa.String(200), nullable=False),
        _created_at(),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('unsealed','sealed')", name="ck_economic_interpretation_set_status"
        ),
    )
    selection = sa.Table(
        "economic_interpretation_selections",
        metadata,
        _id(),
        _fk("interpretation_set_id", "economic_interpretation_sets.id"),
        _fk("source_lineage_id", "economic_source_lineages.id"),
        _fk("evidence_packet_id", "economic_evidence_packets.id"),
        _fk("selected_classification_attempt_id", "economic_classification_attempts.id"),
        sa.Column("pinned_evidence_revision_ordinal", sa.Integer(), nullable=False),
        _fk("interpretation_override_revision_id", "economic_interpretation_override_revisions.id", nullable=True),
        _fk("social_association_revision_ref_id", "economic_social_association_revision_refs.id", nullable=True),
        _created_at(),
        sa.UniqueConstraint(
            "interpretation_set_id",
            "source_lineage_id",
            name="uq_economic_interpretation_selection_lineage",
        ),
    )
    observation = sa.Table(
        "economic_theme_observations",
        metadata,
        _id(),
        _fk("claim_assignment_id", "economic_claim_assignments.id"),
        sa.Column("observation_kind", sa.String(40), nullable=False),
        sa.Column("evidence_channel", sa.String(40), nullable=False),
        sa.Column("derivation_policy_version", sa.String(120), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "claim_assignment_id",
            "observation_kind",
            "evidence_channel",
            "derivation_policy_version",
            name="uq_economic_theme_observation_identity",
        ),
    )
    exposure = sa.Table(
        "economic_theme_constituent_exposures",
        metadata,
        _id(),
        _fk("claim_assignment_id", "economic_claim_assignments.id"),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("stock_universe.id"), nullable=False),
        sa.Column("exposure_kind", sa.String(40), nullable=False),
        sa.Column("exposure_strength", sa.Float()),
        sa.Column("derivation_policy_version", sa.String(120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "claim_assignment_id",
            "security_id",
            "exposure_kind",
            "derivation_policy_version",
            name="uq_economic_theme_constituent_exposure_identity",
        ),
    )
    signal = sa.Table(
        "economic_theme_signal_observations",
        metadata,
        _id(),
        _fk("claim_assignment_id", "economic_claim_assignments.id"),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("stock_universe.id")),
        sa.Column("signal_kind", sa.String(80), nullable=False),
        sa.Column("signal_policy_version", sa.String(120), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "claim_assignment_id",
            "security_id",
            "signal_kind",
            "signal_policy_version",
            name="uq_economic_theme_signal_observation_identity",
        ),
    )
    embedding = sa.Table(
        "economic_theme_embeddings",
        metadata,
        _id(),
        _fk("economic_theme_id", "economic_themes.id"),
        sa.Column("taxonomy_semantic_hash", sa.String(128), nullable=False),
        sa.Column("source_text_hash", sa.String(128), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("model_version", sa.String(120), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "economic_theme_id",
            "taxonomy_semantic_hash",
            "source_text_hash",
            "embedding_model",
            "model_version",
            name="uq_economic_theme_embedding_cache_key",
        ),
    )
    metrics_revision = sa.Table(
        "economic_metrics_revisions",
        metadata,
        _id(),
        sa.Column("status", sa.String(16), nullable=False),
        _fk("interpretation_set_id", "economic_interpretation_sets.id"),
        sa.Column("formula_version", sa.String(120), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("semantic_hash", sa.String(128)),
        sa.Column("artifact_integrity_hash", sa.String(128)),
        sa.Column("created_by", sa.String(200), nullable=False),
        _created_at(),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('unsealed','sealed')", name="ck_economic_metrics_revision_status"
        ),
        sa.UniqueConstraint(
            "interpretation_set_id",
            "formula_version",
            "as_of",
            name="uq_economic_metrics_revision_key",
        ),
    )
    metric = sa.Table(
        "economic_theme_metrics",
        metadata,
        _id(),
        _fk("metrics_revision_id", "economic_metrics_revisions.id"),
        _fk("economic_theme_id", "economic_themes.id"),
        sa.Column("ranking_view", sa.String(80), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("raw_value", sa.Float()),
        sa.Column("percentile", sa.Float()),
        sa.Column("components", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "metrics_revision_id",
            "economic_theme_id",
            "ranking_view",
            name="uq_economic_theme_metric_identity",
        ),
    )

    return [
        family,
        lineage,
        packet,
        precedence,
        lens,
        request,
        extraction,
        review,
        attempt,
        attempt_event,
        assignment,
        override,
        social_ref,
        constituent_decision,
        proposal_decision,
        development_selection,
        interpretation,
        selection,
        observation,
        exposure,
        signal,
        embedding,
        metrics_revision,
        metric,
    ]


def upgrade():
    bind = op.get_bind()
    tables = _schema()
    for table in tables:
        table.create(bind=bind)
    if bind.dialect.name == "postgresql":
        _create_postgres_triggers(tables)


def _create_postgres_triggers(tables):
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION economic_runtime_reject_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'runtime_payload_immutable';
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION economic_runtime_seal_once()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' OR OLD.status = 'sealed' THEN
                RAISE EXCEPTION 'sealed_payload_immutable';
              END IF;
              IF NEW.status <> 'sealed'
                 OR NEW.semantic_hash IS NULL
                 OR NEW.artifact_integrity_hash IS NULL
                 OR NEW.sealed_at IS NULL
                 OR (to_jsonb(NEW) - ARRAY['status','semantic_hash','artifact_integrity_hash','sealed_at']::text[])
                    IS DISTINCT FROM
                    (to_jsonb(OLD) - ARRAY['status','semantic_hash','artifact_integrity_hash','sealed_at']::text[]) THEN
                RAISE EXCEPTION 'runtime_payload_immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION economic_runtime_guard_interpretation_child()
            RETURNS trigger AS $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM economic_interpretation_sets
                WHERE id = NEW.interpretation_set_id AND status = 'sealed'
                FOR KEY SHARE
              ) THEN
                RAISE EXCEPTION 'sealed_payload_immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION economic_runtime_guard_metric_child()
            RETURNS trigger AS $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM economic_metrics_revisions
                WHERE id = NEW.metrics_revision_id AND status = 'sealed'
                FOR KEY SHARE
              ) THEN
                RAISE EXCEPTION 'sealed_payload_immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    mutable_parents = {"economic_interpretation_sets", "economic_metrics_revisions"}
    for table in tables:
        if table.name in mutable_parents:
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table.name}_seal_once "
                    f"BEFORE UPDATE OR DELETE ON {table.name} "
                    "FOR EACH ROW EXECUTE FUNCTION economic_runtime_seal_once()"
                )
            )
        else:
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table.name}_append_only "
                    f"BEFORE UPDATE OR DELETE ON {table.name} "
                    "FOR EACH ROW EXECUTE FUNCTION economic_runtime_reject_mutation()"
                )
            )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_economic_interpretation_selection_parent_open
            BEFORE INSERT ON economic_interpretation_selections
            FOR EACH ROW EXECUTE FUNCTION economic_runtime_guard_interpretation_child();
            CREATE TRIGGER trg_economic_theme_metric_parent_open
            BEFORE INSERT ON economic_theme_metrics
            FOR EACH ROW EXECUTE FUNCTION economic_runtime_guard_metric_child();
            """
        )
    )


def downgrade():
    bind = op.get_bind()
    tables = _schema()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP FUNCTION IF EXISTS economic_runtime_guard_metric_child() CASCADE"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS economic_runtime_guard_interpretation_child() CASCADE"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS economic_runtime_seal_once() CASCADE"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS economic_runtime_reject_mutation() CASCADE"))
    for table in reversed(tables):
        table.drop(bind=bind)

