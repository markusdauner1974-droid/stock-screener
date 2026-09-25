"""Append-only, non-authoritative embedding cache for theme retrieval."""

from __future__ import annotations

import json
from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.economic_taxonomy import (
    EconomicThemeAlias,
    EconomicThemeFacet,
    EconomicThemeRevision,
    TaxonomyVersion,
)
from app.models.economic_taxonomy_runtime import EconomicThemeEmbedding


class EmbeddingProvider(Protocol):
    def embed(self, *, text: str, model: str, model_version: str): ...


def _source_text(session: Session, version_id: UUID, theme_id: UUID) -> str:
    revision = session.get(EconomicThemeRevision, (version_id, theme_id))
    if revision is None:
        raise KeyError(f"theme {theme_id} is not present in taxonomy {version_id}")
    aliases = session.scalars(
        select(EconomicThemeAlias.alias)
        .where(
            EconomicThemeAlias.taxonomy_version_id == version_id,
            EconomicThemeAlias.theme_id == theme_id,
        )
        .order_by(EconomicThemeAlias.normalized_alias)
    ).all()
    facets = session.execute(
        select(
            EconomicThemeFacet.dimension_key,
            EconomicThemeFacet.normalized_value,
        )
        .where(
            EconomicThemeFacet.taxonomy_version_id == version_id,
            EconomicThemeFacet.theme_id == theme_id,
        )
        .order_by(
            EconomicThemeFacet.dimension_key,
            EconomicThemeFacet.normalized_value,
        )
    ).all()
    payload = {
        "display_name": revision.display_name,
        "definition": revision.definition,
        "mechanism": revision.mechanism,
        "aliases": list(aliases),
        "facets": [[key, value] for key, value in facets],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def get_or_recompute_embedding(
    session: Session,
    *,
    taxonomy_version_id: UUID,
    theme_id: UUID,
    embedding_model: str,
    model_version: str,
    provider: EmbeddingProvider,
) -> EconomicThemeEmbedding | None:
    """Return the exact cache entry, or append it from the sealed revision.

    Provider failure deliberately returns ``None``. Retrieval remains correct
    through lexical and facet candidates and never treats this cache as identity
    authority.
    """

    version = session.get(TaxonomyVersion, taxonomy_version_id)
    if version is None or version.status != "sealed" or not version.semantic_hash:
        raise ValueError("embedding_source_must_be_sealed")
    source_text = _source_text(session, taxonomy_version_id, theme_id)
    source_text_hash = sha256(source_text.encode("utf-8")).hexdigest()
    key = (
        EconomicThemeEmbedding.economic_theme_id == theme_id,
        EconomicThemeEmbedding.taxonomy_semantic_hash == version.semantic_hash,
        EconomicThemeEmbedding.source_text_hash == source_text_hash,
        EconomicThemeEmbedding.embedding_model == embedding_model,
        EconomicThemeEmbedding.model_version == model_version,
    )
    existing = session.execute(
        select(EconomicThemeEmbedding).where(*key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    try:
        raw = provider.embed(
            text=source_text,
            model=embedding_model,
            model_version=model_version,
        )
    except Exception:  # noqa: BLE001 - provider outages must degrade to lexical search
        return None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        return None
    try:
        vector = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None

    try:
        with session.begin_nested():
            row = EconomicThemeEmbedding(
                economic_theme_id=theme_id,
                taxonomy_semantic_hash=version.semantic_hash,
                source_text_hash=source_text_hash,
                embedding_model=embedding_model,
                model_version=model_version,
                embedding=vector,
            )
            session.add(row)
            session.flush()
            return row
    except IntegrityError:
        return session.execute(select(EconomicThemeEmbedding).where(*key)).scalar_one()
