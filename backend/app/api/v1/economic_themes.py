"""Generation-scoped Economic Theme product reads."""

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


@router.get("")
def list_economic_themes(
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
        return EconomicThemeReader(db).read_catalog(generation_id)
    except EconomicThemeReadError as exc:
        raise _read_error(exc) from exc


@router.get("/{economic_theme_id}")
def get_economic_theme(
    economic_theme_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    generation_id: Annotated[UUID | None, Query()] = None,
):
    try:
        payload = EconomicThemeReader(db).read_catalog(generation_id)
    except EconomicThemeReadError as exc:
        raise _read_error(exc) from exc
    selected = next(
        (
            row
            for row in payload["themes"]
            if row["economic_theme_id"] == str(economic_theme_id)
        ),
        None,
    )
    if selected is None:
        raise HTTPException(
            status_code=404, detail={"code": "economic_theme_not_found"}
        )
    return {
        "generation_id": payload["generation_id"],
        "generation": payload["generation"],
        "taxonomy_version_id": payload["taxonomy_version_id"],
        "generation_input_manifest_hash": payload[
            "generation_input_manifest_hash"
        ],
        "theme": selected,
    }
