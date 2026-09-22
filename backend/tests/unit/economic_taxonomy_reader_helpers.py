from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.infra.db.repositories.economic_taxonomy_publication_repo import (
    EconomicTaxonomyPublicationRepository,
)
from app.infra.db.repositories.economic_taxonomy_repo import (
    EconomicTaxonomyRepository,
)
from app.models.economic_taxonomy import (
    EconomicTheme,
    EconomicThemeAlias,
    EconomicThemeFacet,
    EconomicThemeRelationship,
    EconomicThemeRevision,
    FacetDimension,
    FacetValue,
    LegacyDestinationMapping,
    LegacyIdentityDisposition,
    TaxonomyVersion,
)
from app.models.economic_taxonomy_runtime import (
    DevelopmentSelectionRevision,
    GenerationInputManifest,
    InterpretationSet,
    MetricsRevision,
    ReaderCapabilityManifest,
    ServingGenerationEvent,
    TaxonomyAuthority,
    ThemeMetric,
)
from app.services.economic_taxonomy_snapshot_builder import (
    GenerationSnapshotInputs,
    build_snapshot_bundle,
)
from sqlalchemy import select

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def seed_generation(db, *, display_name="AI Memory", set_serving=True):
    taxonomy = TaxonomyVersion(
        status="draft",
        created_by="test:reader",
        reason="reader contract",
    )
    memory = EconomicTheme(created_by="test:reader")
    semiconductors = EconomicTheme(created_by="test:reader")
    db.add_all([taxonomy, memory, semiconductors])
    db.flush()
    db.add_all(
        [
            EconomicThemeRevision(
                taxonomy_version_id=taxonomy.id,
                theme_id=memory.id,
                display_name=display_name,
                definition="Memory demand serving AI workloads.",
                mechanism="AI infrastructure increases memory intensity.",
                lifecycle="established",
                lifecycle_policy_version="lifecycle-v1",
                created_by="test:reader",
            ),
            EconomicThemeRevision(
                taxonomy_version_id=taxonomy.id,
                theme_id=semiconductors.id,
                display_name="Semiconductors",
                definition="Semiconductor economic exposure.",
                mechanism="Chip demand and supply economics.",
                lifecycle="established",
                lifecycle_policy_version="lifecycle-v1",
                created_by="test:reader",
            ),
            FacetDimension(
                taxonomy_version_id=taxonomy.id,
                key="industry",
                definition="Industry participation.",
                inclusion_semantics="Direct industry exposure.",
                exclusion_semantics="End-market-only exposure.",
                value_type="keyword",
                cardinality="one",
                scope="theme",
                normalization_policy="facet-v1",
                created_by="test:reader",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            EconomicThemeAlias(
                taxonomy_version_id=taxonomy.id,
                theme_id=memory.id,
                alias="HBM",
                normalized_alias="hbm",
                created_by="test:reader",
            ),
            FacetValue(
                taxonomy_version_id=taxonomy.id,
                dimension_key="industry",
                normalized_value="memory_semiconductors",
                display_value="Memory Semiconductors",
                created_by="test:reader",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            EconomicThemeFacet(
                taxonomy_version_id=taxonomy.id,
                theme_id=memory.id,
                dimension_key="industry",
                normalized_value="memory_semiconductors",
                created_by="test:reader",
            ),
            EconomicThemeRelationship(
                taxonomy_version_id=taxonomy.id,
                source_theme_id=memory.id,
                target_theme_id=semiconductors.id,
                kind="specialization",
                direction="narrower",
                discriminator="memory",
                created_by="test:reader",
            ),
            LegacyIdentityDisposition(
                taxonomy_version_id=taxonomy.id,
                legacy_theme_cluster_id=42,
                disposition="mapped",
                created_by="test:reader",
            ),
        ]
    )
    db.flush()
    db.add(
        LegacyDestinationMapping(
            taxonomy_version_id=taxonomy.id,
            legacy_theme_cluster_id=42,
            destination_theme_id=memory.id,
            created_by="test:reader",
        )
    )
    db.flush()
    EconomicTaxonomyRepository(db).seal_draft(taxonomy.id)
    development_identity = uuid4()
    db.add(
        DevelopmentSelectionRevision(
            development_identity=development_identity,
            revision_number=7,
            selected=False,
            payload={"observation_ids": [], "observations": []},
        )
    )
    db.flush()
    manifest = GenerationInputManifest(
        status="unsealed",
        semantic_invalidation_revision=3,
        committed_revision_tuples=[
            ["development", "source-family:1", "selection", 7, "hash-7"]
        ],
        selections=[
            {
                "lineage": "reader-lineage",
                "evidence_packet_id": "reader-packet",
                "evidence_precedence_revision": 2,
                "lens_eligibility_revision": 3,
                "constituent_decision_revision": 4,
                "social_association_revision": {
                    "association_id": "00000000-0000-0000-0000-000000000001",
                    "revision_number": 5,
                },
                "social_decision_revision": 6,
                "development_identity": str(development_identity),
                "development_revision": 7,
                "override_revision": 8,
                "mapping_revision": "mapping-v1",
                "metrics_policy_revision": "metrics-v1",
                "compatibility_revision": 9,
            }
        ],
        created_by="test:reader",
    )
    db.add(manifest)
    db.flush()
    manifest.seal(
        semantic_hash=f"manifest:{display_name}",
        artifact_integrity_hash=f"manifest-artifact:{display_name}",
    )
    interpretation = InterpretationSet(
        status="unsealed",
        generation_input_manifest_id=manifest.id,
        created_by="test:reader",
    )
    db.add(interpretation)
    db.flush()
    interpretation.seal(
        semantic_hash=f"interpretation:{display_name}",
        artifact_integrity_hash=f"interpretation-artifact:{display_name}",
    )
    metrics = MetricsRevision(
        status="unsealed",
        interpretation_set_id=interpretation.id,
        generation_input_manifest_id=manifest.id,
        formula_version="metrics-v1",
        as_of=NOW,
        created_by="test:reader",
    )
    db.add(metrics)
    db.flush()
    db.add(
        ThemeMetric(
            metrics_revision_id=metrics.id,
            economic_theme_id=memory.id,
            ranking_view="narrative_attention",
            available=True,
            raw_value=3.0,
            percentile=88.0,
            components={"availability": "available"},
        )
    )
    db.flush()
    metrics.seal(
        semantic_hash=f"metrics:{display_name}",
        artifact_integrity_hash=f"metrics-artifact:{display_name}",
    )
    bundle = build_snapshot_bundle(
        db,
        GenerationSnapshotInputs(
            taxonomy_version_id=taxonomy.id,
            interpretation_set_id=interpretation.id,
            generation_input_manifest_id=manifest.id,
            metrics_revision_id=metrics.id,
            created_by="test:reader",
        ),
    )
    capability = db.scalar(
        select(ReaderCapabilityManifest).where(
            ReaderCapabilityManifest.backend_contract == 1,
            ReaderCapabilityManifest.frontend_contract == 1,
            ReaderCapabilityManifest.migration_version == "0055",
            ReaderCapabilityManifest.consumer_test_hash == "reader-tests-v1",
        )
    )
    if capability is None:
        capability = ReaderCapabilityManifest(
            backend_contract=1,
            frontend_contract=1,
            migration_version="0055",
            consumer_test_hash="reader-tests-v1",
            verified_by="test:reader",
        )
        db.add(capability)
        db.flush()
    generation = EconomicTaxonomyPublicationRepository(db).prepare_generation(
        taxonomy_version_id=taxonomy.id,
        interpretation_set_id=interpretation.id,
        metrics_revision_id=metrics.id,
        generation_input_manifest_id=manifest.id,
        reader_snapshot_bundle_id=bundle.id,
        reader_capability_manifest_id=capability.id,
        semantic_hash=f"generation:{display_name}",
        artifact_integrity_hash=f"generation-artifact:{display_name}",
        actor="test:reader",
    )
    db.flush()
    db.add(
        ServingGenerationEvent(
            serving_generation_id=generation.id,
            sequence_number=2,
            event_type="published",
            actor="test:reader",
            details={},
        )
    )
    authority = db.get(TaxonomyAuthority, 1)
    if authority is None:
        authority = TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_taxonomy_version_id=taxonomy.id,
            processing_head_revision=1,
            serving_generation_id=generation.id if set_serving else None,
            authority_epoch=2,
            writes_fenced=False,
            semantic_invalidation_revision=3,
            cutover_catch_up_cursor=[],
            rollback_state="ready",
        )
        db.add(authority)
    elif set_serving:
        authority.serving_generation_id = generation.id
    db.flush()
    return {
        "taxonomy": taxonomy,
        "memory": memory,
        "semiconductors": semiconductors,
        "manifest": manifest,
        "interpretation": interpretation,
        "metrics": metrics,
        "bundle": bundle,
        "generation": generation,
    }
