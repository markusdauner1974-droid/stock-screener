"""#471: ingested non-X content is admitted as economic taxonomy evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.economic_taxonomy_runtime import (
    EvidencePacket,
    ProcessingRequest,
    SourceFamily,
    SourceLineage,
    TaxonomyAuthority,
)
from app.models.theme import ContentItem, ContentSource
from app.services.content_ingestion_service import ContentIngestionService
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


def test_x_posts_are_left_to_social_admission(db_session):
    source = _source(db_session, source_type="twitter")

    _ingest(db_session, source, _Feed(_item(external_id="tw-1")))

    assert db_session.scalar(select(func.count()).select_from(ContentItem)) == 1
    assert db_session.scalar(select(func.count()).select_from(EvidencePacket)) == 0
