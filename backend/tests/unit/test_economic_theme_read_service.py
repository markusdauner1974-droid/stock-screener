from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.models.economic_taxonomy_runtime import (
    ServingGeneration,
    ServingGenerationEvent,
    TaxonomyAuthority,
)
from app.services.economic_theme_read_service import (
    EconomicThemeReader,
    GenerationNotFound,
)

from .economic_taxonomy_reader_helpers import seed_generation


@pytest.mark.parametrize(
    ("mode", "source"),
    [
        ("legacy", "legacy"),
        ("shadow", "legacy"),
        ("dual", "legacy"),
        ("economic", "economic"),
    ],
)
def test_reader_follows_authority(mode, source):
    assert EconomicThemeReader.for_mode(mode).source_name == source


def test_economic_request_resolves_one_generation(db_session, monkeypatch):
    seeded = seed_generation(db_session)
    reader = EconomicThemeReader(db_session)
    calls = []
    original = reader.resolve_generation

    def counted(generation_id=None):
        calls.append(generation_id)
        return original(generation_id)

    monkeypatch.setattr(reader, "resolve_generation", counted)

    payload = reader.read_current_catalog()

    assert payload["generation_id"] == str(seeded["generation"].id)
    assert calls == [seeded["generation"].id]


def test_historical_generation_keeps_original_publication_timestamp(db_session):
    seeded = seed_generation(db_session)
    generation = seeded["generation"]
    published = db_session.query(ServingGenerationEvent).filter_by(
        serving_generation_id=generation.id,
        event_type="published",
    ).one()
    published_at = published.created_at
    db_session.add(
        ServingGenerationEvent(
            serving_generation_id=generation.id,
            sequence_number=3,
            event_type="superseded",
            actor="test:reader",
            details={},
            created_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
    )
    db_session.commit()

    metadata = EconomicThemeReader(db_session).generation_metadata(generation.id)

    assert metadata["status"] == "superseded"
    assert metadata["published_at"] == published_at.isoformat()


def test_non_economic_modes_do_not_read_generation_payload(db_session):
    seed_generation(db_session)
    authority = db_session.get(TaxonomyAuthority, 1)
    authority.mode = "dual"
    db_session.commit()

    selection = EconomicThemeReader(db_session).select_authority()

    assert selection.source_name == "legacy"
    assert selection.generation_id is None


@pytest.mark.parametrize("final_event", (None, "abandoned"))
def test_explicit_read_rejects_generation_without_publication(db_session, final_event):
    seeded = seed_generation(db_session)
    source = seeded["generation"]
    generation = ServingGeneration(
        taxonomy_version_id=source.taxonomy_version_id,
        interpretation_set_id=source.interpretation_set_id,
        metrics_revision_id=source.metrics_revision_id,
        generation_input_manifest_id=source.generation_input_manifest_id,
        reader_snapshot_bundle_id=source.reader_snapshot_bundle_id,
        reader_capability_manifest_id=source.reader_capability_manifest_id,
        semantic_hash=f"unpublished:{uuid4()}",
        artifact_integrity_hash=f"unpublished-artifact:{uuid4()}",
        created_by="test:reader",
    )
    db_session.add(generation)
    db_session.flush()
    db_session.add(
        ServingGenerationEvent(
            serving_generation_id=generation.id,
            sequence_number=1,
            event_type="prepared",
            actor="test:reader",
            details={},
        )
    )
    if final_event is not None:
        db_session.add(
            ServingGenerationEvent(
                serving_generation_id=generation.id,
                sequence_number=2,
                event_type=final_event,
                actor="test:reader",
                details={},
            )
        )
    db_session.commit()

    with pytest.raises(GenerationNotFound, match="generation_not_published"):
        EconomicThemeReader(db_session).read_catalog(generation.id)


def test_legacy_compatibility_uses_reviewed_mapping_not_name(db_session):
    seeded = seed_generation(db_session, display_name="Renamed AI Infrastructure")
    reader = EconomicThemeReader(db_session)

    theme = reader.read_legacy_theme(42)

    assert theme["economic_theme_id"] == str(seeded["memory"].id)
    assert theme["display_name"] == "Renamed AI Infrastructure"
    assert reader.read_legacy_theme(404) is None


def test_stock_theme_summaries_use_generation_constituents(db_session):
    seed_generation(db_session)
    reader = EconomicThemeReader(db_session)
    catalog = reader.read_current_catalog()
    catalog["themes"][0]["constituents"] = [
        {
            "security_id": 1,
            "canonical_symbol": "MU",
            "market": "US",
            "exposure_kind": "direct",
            "exposure_strength": 0.9,
        }
    ]
    monkeypatch_catalog = catalog
    reader.read_current_catalog = lambda: monkeypatch_catalog

    rows = reader.theme_summaries_for_symbol("mu")

    assert rows[0]["theme_id"] == UUID(catalog["themes"][0]["economic_theme_id"])
    assert rows[0]["display_name"] == "AI Memory"


def test_legacy_rankings_follow_reviewed_redirects_without_name_inference(db_session):
    source_id = "00000000-0000-0000-0000-000000000001"
    target_id = "00000000-0000-0000-0000-000000000002"
    reader = EconomicThemeReader(db_session)
    reader.read_current_catalog = lambda: {
        "generation_id": "generation-1",
        "mappings": [
            {"legacy_theme_cluster_id": 42, "destination_theme_id": source_id}
        ],
        "redirects": [
            {"source_theme_id": source_id, "target_theme_id": target_id}
        ],
        "themes": [
            {
                "economic_theme_id": target_id,
                "display_name": "Renamed Memory Infrastructure",
                "lifecycle": "established",
                "metrics": {
                    "technical_attention": {
                        "availability": "available",
                        "percentile": 91,
                        "components": {},
                    }
                },
                "constituents": [],
            }
        ],
    }

    rows, total = reader.legacy_rankings(pipeline="technical", limit=20)

    assert total == 1
    assert rows[0]["theme_cluster_id"] == 42
    assert rows[0]["economic_theme_id"] == target_id
    assert rows[0]["theme"] == "Renamed Memory Infrastructure"
