from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.economic_taxonomy import EconomicTheme
from app.models.economic_taxonomy_runtime import (
    DevelopmentSelectionRevision,
    SourceFamily,
    TaxonomyAuthority,
    TaxonomySourceRevisionLog,
)
from app.models.theme import ContentItem, ThemeCluster
from app.models.theme_intelligence import (
    EconomicThemeDevelopment,
    LegacyDevelopmentEventMapping,
    ThemeDevelopmentEvent,
    ThemeDevelopmentObservation,
    ThemeDevelopmentTheme,
)
from app.services.economic_taxonomy_fence import AuthorityWritesFenced
from app.services.theme_development_service import (
    current_development_event,
    migrate_legacy_development_events,
    record_developments,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _item(db_session, suffix: str) -> ContentItem:
    item = ContentItem(
        source_type="twitter",
        external_id=f"post-{suffix}",
        url=f"https://x.com/example/status/{suffix}",
        content="Nebius confirmed Project A order 2026-09.",
        published_at=NOW,
    )
    db_session.add(item)
    db_session.flush()
    return item


def _facts(*, legacy_theme_ids=()):
    return {
        "theme_ids": list(legacy_theme_ids),
        "actor": "Nebius",
        "action": "order",
        "object": "Project A order",
        "event_time": "2026-09",
        "reference": None,
        "status": "confirmed",
        "summary": "Nebius confirmed Project A order.",
        "quantities": [],
        "citations": [
            {
                "source_id": "primary",
                "quote": "Nebius confirmed Project A order 2026-09",
            }
        ],
    }


def _source_family(db_session) -> SourceFamily:
    row = SourceFamily(
        provider="x",
        canonical_source_key="x:post:project-a",
        canonical_item_id="project-a",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_social_native_development_has_narrative_provenance(db_session):
    theme = EconomicTheme(created_by="test:development")
    db_session.add(theme)
    db_session.flush()
    item = _item(db_session, "narrative")
    source_family = _source_family(db_session)

    rows = record_developments(
        db_session,
        item=item,
        pipeline="narrative",
        analysis_channel="narrative",
        revision="n" * 64,
        theme_ids=[],
        economic_theme_ids=[theme.id],
        source_family_id=source_family.id,
        sources={"primary": item.content},
        observations=[_facts()],
        available_at=NOW,
        development_support="present",
    )

    assert len(rows) == 1
    assert rows[0].analysis_channel == "narrative"
    assert rows[0].development_support == "present"
    assert [link.economic_theme_id for link in rows[0].economic_theme_links] == [
        theme.id
    ]
    selection = db_session.query(DevelopmentSelectionRevision).one()
    assert selection.selected is True
    assert selection.payload["observation_ids"] == [rows[0].id]
    dirty = db_session.query(TaxonomySourceRevisionLog).one()
    assert dirty.producer_kind == "development"


def test_dual_routes_share_one_canonical_event_identity(db_session):
    economic_theme = EconomicTheme(created_by="test:development")
    legacy_theme = ThemeCluster(
        name="AI Infrastructure",
        display_name="AI Infrastructure",
        canonical_key="ai_infrastructure",
        pipeline="technical",
    )
    db_session.add_all([economic_theme, legacy_theme])
    db_session.flush()
    source_family = _source_family(db_session)
    narrative_item = _item(db_session, "social-route")
    legacy_item = _item(db_session, "legacy-route")

    narrative = record_developments(
        db_session,
        item=narrative_item,
        pipeline="narrative",
        analysis_channel="narrative",
        revision="a" * 64,
        theme_ids=[],
        economic_theme_ids=[economic_theme.id],
        source_family_id=source_family.id,
        sources={"primary": narrative_item.content},
        observations=[_facts()],
        available_at=NOW,
    )[0]
    legacy = record_developments(
        db_session,
        item=legacy_item,
        pipeline="technical",
        analysis_channel="technical",
        revision="b" * 64,
        theme_ids=[legacy_theme.id],
        economic_theme_ids=[economic_theme.id],
        source_family_id=source_family.id,
        sources={"primary": legacy_item.content},
        observations=[_facts(legacy_theme_ids=[legacy_theme.id])],
        available_at=NOW,
    )[0]

    assert narrative.event_id == legacy.event_id
    assert db_session.query(ThemeDevelopmentEvent).count() == 1
    assert db_session.query(ThemeDevelopmentObservation).count() == 2
    assert db_session.query(ThemeDevelopmentTheme).count() == 1
    assert db_session.query(EconomicThemeDevelopment).count() == 2


def test_compatibility_delivery_adds_legacy_link_without_second_event(db_session):
    economic_theme = EconomicTheme(created_by="test:development")
    legacy_theme = ThemeCluster(
        name="AI Infrastructure",
        display_name="AI Infrastructure",
        canonical_key="ai_infrastructure_compatibility",
        pipeline="technical",
    )
    db_session.add_all([economic_theme, legacy_theme])
    db_session.flush()
    source_family = _source_family(db_session)
    item = _item(db_session, "compatibility")
    arguments = {
        "item": item,
        "pipeline": "narrative",
        "analysis_channel": "narrative",
        "revision": "k" * 64,
        "economic_theme_ids": [economic_theme.id],
        "source_family_id": source_family.id,
        "sources": {"primary": item.content},
        "observations": [_facts()],
        "available_at": NOW,
    }
    original = record_developments(
        db_session,
        theme_ids=[],
        **arguments,
    )[0]
    mirrored = record_developments(
        db_session,
        theme_ids=[legacy_theme.id],
        economic_link_origin="compatibility",
        **arguments,
    )[0]

    assert mirrored.id == original.id
    assert mirrored.event_id == original.event_id
    assert mirrored.theme_ids == [legacy_theme.id]
    assert db_session.query(ThemeDevelopmentEvent).count() == 1
    assert db_session.query(ThemeDevelopmentObservation).count() == 1


def test_legacy_duplicate_identity_is_preserved_and_resolves_canonical(db_session):
    identity = {
        "actor": "nebius",
        "action": "order",
        "object": "project a order",
        "anchor": "2026 09",
    }
    event_key = "c" * 64
    technical = ThemeDevelopmentEvent(
        pipeline="technical", event_key=event_key, identity=identity
    )
    fundamental = ThemeDevelopmentEvent(
        pipeline="fundamental", event_key=event_key, identity=identity
    )
    db_session.add_all([technical, fundamental])
    db_session.flush()
    item = _item(db_session, "legacy-duplicate")
    observations = []
    for event, channel in ((technical, "technical"), (fundamental, "fundamental")):
        observation = ThemeDevelopmentObservation(
            event_id=event.id,
            content_item_id=item.id,
            pipeline=channel,
            analysis_channel=channel,
            revision=channel[0] * 64,
            observation_key=channel[0] * 64,
            facts={key: value for key, value in _facts().items() if key not in {"theme_ids", "citations"}},
            citations=_facts()["citations"],
            classification="uncertain",
            development_support="present",
            available_at=NOW,
            superseded=False,
        )
        db_session.add(observation)
        observations.append(observation)
    db_session.flush()
    historical_event_ids = [row.event_id for row in observations]

    result = migrate_legacy_development_events(
        db_session, migration_run_id=uuid4()
    )

    assert result.legacy_mapping_count == 2
    assert {
        current_development_event(db_session, event.id).id
        for event in (technical, fundamental)
    } == {result.canonical_event_id}
    assert [row.event_id for row in observations] == historical_event_ids
    assert db_session.query(LegacyDevelopmentEventMapping).count() == 2


def test_legacy_development_mapping_is_append_only(db_session):
    event = ThemeDevelopmentEvent(
        pipeline="technical",
        event_key="m" * 64,
        identity={"source": "legacy"},
    )
    db_session.add(event)
    db_session.flush()
    migrate_legacy_development_events(db_session, migration_run_id=uuid4())
    mapping = db_session.query(LegacyDevelopmentEventMapping).one()

    mapping.old_pipeline = "fundamental"
    with pytest.raises(
        ValueError, match="legacy_development_event_mapping_append_only"
    ):
        db_session.flush()


def test_development_support_is_separate_and_rejects_exposure_values(db_session):
    item = _item(db_session, "support")
    source_family = _source_family(db_session)
    theme = EconomicTheme(created_by="test:development")
    db_session.add(theme)
    db_session.flush()

    rows = record_developments(
        db_session,
        item=item,
        pipeline="narrative",
        analysis_channel="narrative",
        revision="u" * 64,
        theme_ids=[],
        economic_theme_ids=[theme.id],
        source_family_id=source_family.id,
        sources={"primary": item.content},
        observations=[_facts()],
        available_at=NOW,
        development_support="unresolved",
    )
    assert rows[0].development_support == "unresolved"

    absent = record_developments(
        db_session,
        item=item,
        pipeline="narrative",
        analysis_channel="narrative",
        revision="a" * 64,
        theme_ids=[],
        economic_theme_ids=[theme.id],
        source_family_id=source_family.id,
        sources={"primary": item.content},
        observations=[_facts()],
        available_at=NOW,
        development_support="absent",
    )[0]
    assert absent.development_support == "absent"
    latest = db_session.query(DevelopmentSelectionRevision).order_by(
        DevelopmentSelectionRevision.revision_number.desc()
    ).first()
    assert latest.selected is False

    with pytest.raises(ValueError, match="invalid_development_support"):
        record_developments(
            db_session,
            item=item,
            pipeline="narrative",
            analysis_channel="narrative",
            revision="x" * 64,
            theme_ids=[],
            economic_theme_ids=[theme.id],
            source_family_id=source_family.id,
            sources={"primary": item.content},
            observations=[_facts()],
            available_at=NOW,
            development_support="unsupported",
        )


def test_corrected_empty_appends_selection_without_rewriting_history(db_session):
    item = _item(db_session, "corrected-empty")
    source_family = _source_family(db_session)
    theme = EconomicTheme(created_by="test:development")
    db_session.add(theme)
    db_session.flush()
    first = record_developments(
        db_session,
        item=item,
        pipeline="narrative",
        analysis_channel="narrative",
        revision="p" * 64,
        theme_ids=[],
        economic_theme_ids=[theme.id],
        source_family_id=source_family.id,
        sources={"primary": item.content},
        observations=[_facts()],
        available_at=NOW,
    )[0]
    selected = db_session.query(DevelopmentSelectionRevision).one()

    corrected = record_developments(
        db_session,
        item=item,
        pipeline="narrative",
        analysis_channel="narrative",
        revision="e" * 64,
        theme_ids=[],
        economic_theme_ids=[theme.id],
        source_family_id=source_family.id,
        sources={"primary": item.content},
        observations=[],
        available_at=NOW,
    )

    revisions = db_session.query(DevelopmentSelectionRevision).order_by(
        DevelopmentSelectionRevision.revision_number
    ).all()
    assert corrected == []
    assert first.superseded is True
    assert [(row.revision_number, row.selected) for row in revisions] == [
        (1, True),
        (2, False),
    ]
    assert selected.payload["observation_ids"] == [first.id]
    assert revisions[1].payload["observation_ids"] == []


def test_development_write_respects_authority_fence(db_session):
    item = _item(db_session, "fenced")
    source_family = _source_family(db_session)
    theme = EconomicTheme(created_by="test:development")
    db_session.add(theme)
    db_session.add(
        TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_head_revision=0,
            authority_epoch=3,
            writes_fenced=True,
            semantic_invalidation_revision=0,
            cutover_catch_up_cursor=[],
            rollback_state="ready",
        )
    )
    db_session.flush()

    with pytest.raises(AuthorityWritesFenced, match="authority_writes_fenced"):
        record_developments(
            db_session,
            item=item,
            pipeline="narrative",
            analysis_channel="narrative",
            revision="f" * 64,
            theme_ids=[],
            economic_theme_ids=[theme.id],
            source_family_id=source_family.id,
            sources={"primary": item.content},
            observations=[_facts()],
            available_at=NOW,
        )

    assert db_session.query(ThemeDevelopmentEvent).count() == 0
