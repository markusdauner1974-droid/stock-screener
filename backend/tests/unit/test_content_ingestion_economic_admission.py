"""#471: ingested non-X content is admitted as economic taxonomy evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from app.database import SessionLocal
from app.infra.db.models.social_signals import ContentPipelineEligibility
from app.models.economic_taxonomy_runtime import (
    EvidencePacket,
    LensEligibilityRevision,
    ProcessingRequest,
    SourceFamily,
    SourceLineage,
    TaxonomyAuthority,
)
from app.models.theme import ContentItem, ContentSource
from app.services.content_ingestion_service import ContentIngestionService
from app.services.theme_pipeline_state_service import reconcile_source_pipeline_change
from app.tasks.economic_taxonomy_tasks import EconomicTaxonomyTaskService

NOW = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)


class _Feed:
    def __init__(self, *items):
        self.items = list(items)

    def fetch(self, source, since=None):
        return list(self.items)


def _item(content="Memory demand is accelerating.", external_id="rss-1", **overrides):
    return {
        "external_id": external_id,
        "title": "Memory upcycle",
        "content": content,
        "url": "https://example.com/memory",
        "author": "Analyst",
        "published_at": NOW,
        **overrides,
    }


def _source(db_session, source_type="rss"):
    source = ContentSource(
        name="Example feed",
        source_type=source_type,
        url=f"https://example.com/{source_type}",
        pipelines=["technical", "fundamental"],
    )
    db_session.add(source)
    db_session.commit()
    return source


def _ingest(db_session, source, feed):
    service = ContentIngestionService(db_session)
    service.fetchers[source.source_type] = feed
    return service.fetch_source(source)


def _packets(db_session):
    return db_session.scalars(
        select(EvidencePacket).order_by(EvidencePacket.evidence_revision_ordinal)
    ).all()


def test_ingested_item_is_admitted_and_picked_up_by_economic_discovery(db_session):
    db_session.add(
        TaxonomyAuthority(
            id=1, mode="shadow", processing_head_revision=1, authority_epoch=7,
            writes_fenced=False, semantic_invalidation_revision=0,
            cutover_catch_up_cursor=[], rollback_state="ready",
        )
    )
    source = _source(db_session)

    assert _ingest(db_session, source, _Feed(_item())) == 1

    item = db_session.scalar(select(ContentItem))
    (packet,) = _packets(db_session)
    family = db_session.scalar(
        select(SourceFamily)
        .join(SourceLineage, SourceLineage.source_family_id == SourceFamily.id)
        .where(SourceLineage.id == packet.source_lineage_id)
    )
    assert family.canonical_source_key == "rss:post:rss-1"
    assert packet.capture_route == "content_ingestion"
    assert packet.precedence_state == "effective"
    assert packet.original_text_ref == "Memory upcycle\n\nMemory demand is accelerating."
    assert packet.source_metadata["content_item_id"] == item.id

    discovered = EconomicTaxonomyTaskService(
        SessionLocal, pipeline=SimpleNamespace(), clock=lambda: NOW
    ).discover(limit=10)

    assert discovered["enqueued"] == 1
    assert db_session.scalar(
        select(ProcessingRequest.id).where(ProcessingRequest.evidence_packet_id == packet.id)
    ) is not None


def test_repolling_an_unchanged_item_adds_no_packet(db_session):
    source = _source(db_session)
    feed = _Feed(_item())

    _ingest(db_session, source, feed)
    _ingest(db_session, source, feed)

    assert db_session.scalar(select(func.count()).select_from(EvidencePacket)) == 1


def test_corrections_including_to_empty_go_through_the_same_lineage(db_session):
    source = _source(db_session)
    _ingest(db_session, source, _Feed(_item()))

    _ingest(db_session, source, _Feed(_item(content="Memory demand is slowing.")))
    _ingest(db_session, source, _Feed(_item(content="", title="")))
    _ingest(db_session, source, _Feed(_item(content="", title="")))  # re-poll

    original, corrected, emptied = _packets(db_session)
    assert {p.source_lineage_id for p in (original, corrected, emptied)} == {
        original.source_lineage_id
    }
    assert emptied.original_text_ref == ""
    # No provider revision order: the precedence policy holds corrections for
    # review instead of letting admission order claim freshness.
    assert original.precedence_state == "effective"
    assert corrected.precedence_state == emptied.precedence_state == "hold_review"


def test_capture_is_attributed_to_the_polled_source(db_session):
    # Two feeds of one type share a ContentItem; the second one's changed
    # capture must name the second feed, not the item's first source.
    first = _source(db_session)
    second = ContentSource(
        name="Mirror feed", source_type="rss", url="https://mirror.example.com/rss",
        pipelines=["technical"],
    )
    db_session.add(second)
    db_session.commit()
    _ingest(db_session, first, _Feed(_item()))

    _ingest(db_session, second, _Feed(_item(content="Memory demand is slowing.")))

    corrected = _packets(db_session)[-1]
    assert corrected.source_metadata["content_source_id"] == second.id
    assert corrected.source_metadata["source_name"] == "Mirror feed"


def test_unchanged_capture_from_a_mirror_feed_keeps_its_own_provenance(db_session):
    first = _source(db_session)
    mirror = ContentSource(
        name="Mirror feed", source_type="rss", url="https://mirror.example.com/rss",
        pipelines=["technical"],
    )
    db_session.add(mirror)
    db_session.commit()
    _ingest(db_session, first, _Feed(_item()))

    _ingest(db_session, mirror, _Feed(_item()))
    _ingest(db_session, mirror, _Feed(_item()))  # re-poll

    original, mirrored = _packets(db_session)
    assert mirrored.precedence_state == "equivalent"
    assert mirrored.source_metadata["content_source_id"] == mirror.id
    assert original.source_metadata["content_source_id"] == first.id


def test_backfill_admits_previously_ingested_items_once(db_session):
    source = _source(db_session)
    twitter = _source(db_session, source_type="twitter")
    fetched_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for item_source, external_id in ((source, "old-1"), (source, "old-2"), (twitter, "tw-old")):
        db_session.add(ContentItem(
            source_id=item_source.id, source_type=item_source.source_type,
            source_name=item_source.name, external_id=external_id, title="Old",
            content=f"Old article {external_id}", published_at=fetched_at,
            fetched_at=fetched_at,
        ))
    db_session.commit()
    service = ContentIngestionService(db_session)

    first = service.backfill_economic_evidence(batch_size=1)
    again = service.backfill_economic_evidence(batch_size=1)

    packets = _packets(db_session)
    assert first["admitted"] == again["admitted"] == 2
    assert len(packets) == 2
    assert {p.available_at.replace(tzinfo=timezone.utc) for p in packets} == {fetched_at}


def test_backfill_replays_each_recorded_legacy_observation(db_session):
    technical = ContentSource(name="Tech feed", source_type="rss",
                              url="https://a.example.com/rss", pipelines=["technical"])
    fundamental = ContentSource(name="Fund feed", source_type="rss",
                                url="https://b.example.com/rss", pipelines=["technical"])
    db_session.add_all([technical, fundamental])
    db_session.flush()
    observed = datetime(2026, 9, 1, tzinfo=timezone.utc)
    item = ContentItem(source_id=technical.id, source_type="rss", source_name="Tech feed",
                       external_id="shared-1", title="Old", content="Old article",
                       published_at=observed, fetched_at=observed)
    db_session.add(item)
    db_session.flush()
    # The second feed's pipelines changed after it granted fundamental.
    for source, pipeline in ((technical, "technical"), (fundamental, "fundamental")):
        db_session.add(ContentPipelineEligibility(
            content_item_id=item.id, pipeline=pipeline, channel="legacy",
            originating_source_id=source.id, observed_at=observed,
        ))
    db_session.commit()

    ContentIngestionService(db_session).backfill_economic_evidence()

    packets = _packets(db_session)
    assert {p.source_metadata["content_source_id"] for p in packets} == {
        technical.id, fundamental.id,
    }
    channels = {
        channel
        for revision in db_session.scalars(select(LensEligibilityRevision))
        for channel in revision.evidence_channels
    }
    assert channels == {"technical", "fundamental"}


def test_pipeline_added_to_a_source_reaches_economic_lens_of_old_items(db_session):
    source = ContentSource(name="Feed", source_type="rss", url="https://feed.example.com/rss",
                           pipelines=["technical"])
    db_session.add(source)
    db_session.commit()
    _ingest(db_session, source, _Feed(_item()))
    (packet,) = _packets(db_session)

    def channels():
        latest = db_session.scalars(
            select(LensEligibilityRevision)
            .where(LensEligibilityRevision.evidence_packet_id == packet.id)
            .order_by(LensEligibilityRevision.revision_number.desc())
        ).first()
        return latest.evidence_channels

    assert channels() == ["technical"]

    reconcile_source_pipeline_change(
        db_session, source.id, ["technical"], ["technical", "fundamental"]
    )
    revisions = db_session.scalar(select(func.count()).select_from(LensEligibilityRevision))
    reconcile_source_pipeline_change(  # already applied: no new revision
        db_session, source.id, ["technical", "fundamental"], ["technical", "fundamental"]
    )

    assert channels() == ["fundamental", "technical"]
    assert db_session.scalar(select(func.count()).select_from(LensEligibilityRevision)) == revisions


def test_unchanged_held_correction_is_not_readmitted_on_repoll(db_session):
    source = _source(db_session)
    _ingest(db_session, source, _Feed(_item()))
    corrected = _Feed(_item(content="Memory demand is slowing."))

    _ingest(db_session, source, corrected)
    _ingest(db_session, source, corrected)

    assert [p.precedence_state for p in _packets(db_session)] == ["effective", "hold_review"]


def test_title_already_leading_the_content_is_not_repeated(db_session):
    # RedditFetcher builds content as "title\n\nselftext".
    source = _source(db_session, source_type="reddit")

    _ingest(db_session, source, _Feed(_item(
        title="Memory upcycle", content="Memory upcycle\n\nDRAM prices up.",
    )))

    (packet,) = _packets(db_session)
    assert packet.original_text_ref == "Memory upcycle\n\nDRAM prices up."


def test_x_posts_are_left_to_social_admission(db_session):
    source = _source(db_session, source_type="twitter")

    _ingest(db_session, source, _Feed(_item(external_id="tw-1")))

    assert db_session.scalar(select(func.count()).select_from(ContentItem)) == 1
    assert db_session.scalar(select(func.count()).select_from(EvidencePacket)) == 0
