"""Protected published COT catalog, history, and snapshot routes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.cot import CotCatalogResponse, CotHistoryResponse, CotSnapshotResponse
from app.services.cot_response_cache import cot_cache_key, get_cot_response_cache
from app.use_cases.cot.queries import (
    CotInstrumentUnavailable,
    CotPublicationUnavailable,
)
from app.wiring.bootstrap import get_cot_queries


router = APIRouter()


def _unavailable(code: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code})


def _set_cache_control(response: Response) -> None:
    response.headers["Cache-Control"] = "private, max-age=60"


@router.get("/instruments", response_model=CotCatalogResponse)
def get_cot_catalog(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> CotCatalogResponse:
    _set_cache_control(response)
    queries = get_cot_queries(db)
    try:
        publication = queries.publication()
        key = cot_cache_key("catalog", publication.publication_id)
        cache = get_cot_response_cache()
        cached = cache.get(key)
        if cached is not None:
            return CotCatalogResponse.model_validate_json(cached)
        response = CotCatalogResponse.from_view(queries.catalog())
        cache.set(key, response.model_dump_json())
        return response
    except CotPublicationUnavailable as exc:
        raise _unavailable("cot_publication_unavailable") from exc


@router.get("/instruments/{slug}/history", response_model=CotHistoryResponse)
def get_cot_history(
    slug: str,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    range_name: Annotated[Literal["1y", "3y", "5y"], Query(alias="range")] = "1y",
) -> CotHistoryResponse:
    _set_cache_control(response)
    queries = get_cot_queries(db)
    try:
        publication = queries.publication()
        key = cot_cache_key(
            "history",
            publication.publication_id,
            slug=slug,
            range_name=range_name,
        )
        cache = get_cot_response_cache()
        cached = cache.get(key)
        if cached is not None:
            return CotHistoryResponse.model_validate_json(cached)
        response = CotHistoryResponse.from_view(queries.history(slug, range_name))
        cache.set(key, response.model_dump_json())
        return response
    except CotInstrumentUnavailable as exc:
        raise _unavailable("cot_instrument_unavailable") from exc
    except CotPublicationUnavailable as exc:
        raise _unavailable("cot_publication_unavailable") from exc


@router.get("/snapshot", response_model=CotSnapshotResponse)
def get_cot_snapshot(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> CotSnapshotResponse:
    _set_cache_control(response)
    queries = get_cot_queries(db)
    try:
        publication = queries.publication()
        key = cot_cache_key("snapshot", publication.publication_id)
        cache = get_cot_response_cache()
        cached = cache.get(key)
        if cached is not None:
            return CotSnapshotResponse.model_validate_json(cached)
        response = CotSnapshotResponse.from_view(queries.snapshot())
        cache.set(key, response.model_dump_json())
        return response
    except CotPublicationUnavailable as exc:
        raise _unavailable("cot_publication_unavailable") from exc
