"""Put a test session under economic Theme authority."""

from __future__ import annotations

from app.models.economic_taxonomy_runtime import TaxonomyAuthority


def set_economic_authority(db) -> None:
    """Create the authority row in economic mode; no serving generation needed."""
    TaxonomyAuthority.__table__.create(bind=db.get_bind(), checkfirst=True)
    db.add(
        TaxonomyAuthority(
            id=1,
            mode="economic",
            processing_head_revision=0,
            authority_epoch=1,
            writes_fenced=False,
            semantic_invalidation_revision=0,
            cutover_catch_up_cursor=[],
            rollback_state="ready",
        )
    )
    db.commit()
