"""Generation-scoped Economic Taxonomy review and generation reads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.economic_theme_read_service import (
    EconomicThemeReader,
    EconomicThemeReadError,
    GenerationNotFound,
    ReaderSnapshotCoherenceError,
    ReaderSnapshotUnavailable,
    ServingGenerationUnavailable,
)

router = APIRouter()


def _read_error(exc: EconomicThemeReadError) -> HTTPException:
    if isinstance(exc, GenerationNotFound):
        return HTTPException(status_code=404, detail={"code": str(exc)})
    if isinstance(exc, ServingGenerationUnavailable):
        return HTTPException(status_code=503, detail={"code": str(exc)})
    if isinstance(exc, (ReaderSnapshotUnavailable, ReaderSnapshotCoherenceError)):
        return HTTPException(status_code=409, detail={"code": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc)})


@router.get("/review")
def taxonomy_review(
    db: Annotated[Session, Depends(get_db)],
    generation_id: Annotated[UUID | None, Query()] = None,
    interpretation_set_id: Annotated[UUID | None, Query()] = None,
):
    if interpretation_set_id is not None:
        raise HTTPException(
            status_code=422,
            detail={"code": "generation_id_required_for_product_read"},
        )
    try:
        return EconomicThemeReader(db).read_taxonomy_review(generation_id)
    except EconomicThemeReadError as exc:
        raise _read_error(exc) from exc


@router.get("/generations/{generation_id}")
def generation_metadata(
    generation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
):
    try:
        return EconomicThemeReader(db).generation_metadata(generation_id)
    except EconomicThemeReadError as exc:
        raise _read_error(exc) from exc
