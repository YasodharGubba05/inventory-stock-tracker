import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.product import MovementType
from app.schemas.movement import (
    MovementCreate,
    MovementListResponse,
    MovementResponse,
    MovementSummaryResponse,
)
from app.services.movement_service import (
    _hash_request,
    create_movement,
    get_idempotency_record,
    list_movements,
    movement_summary,
    store_idempotency_record,
)
from app.services.product_service import (
    InsufficientStockError,
    ProductInactiveError,
    ProductNotFoundError,
)

router = APIRouter()
settings = get_settings()


def _clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    limit = min(max(limit, 1), settings.max_page_size)
    offset = max(offset, 0)
    return limit, offset


@router.post(
    "/products/{product_id}/movements",
    response_model=MovementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_movement_endpoint(
    product_id: uuid.UUID,
    payload: MovementCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MovementResponse:
    endpoint = str(request.url.path)
    request_hash = _hash_request(payload)

    if idempotency_key:
        existing = await get_idempotency_record(
            db, idempotency_key=idempotency_key, endpoint=endpoint
        )
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key reused with a different request body",
                )
            return MovementResponse.model_validate(json.loads(existing.response_body))

    try:
        movement = await create_movement(db, product_id, payload)
        response = MovementResponse.model_validate(movement)

        if idempotency_key:
            await store_idempotency_record(
                db,
                idempotency_key=idempotency_key,
                endpoint=endpoint,
                request_hash=request_hash,
                response_status=status.HTTP_201_CREATED,
                response_body=response.model_dump_json(),
            )

        return response
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProductInactiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/products/{product_id}/movements", response_model=MovementListResponse)
async def list_movements_endpoint(
    product_id: uuid.UUID,
    movement_type: MovementType | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=settings.default_page_size, ge=1),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> MovementListResponse:
    limit, offset = _clamp_pagination(limit, offset)
    try:
        items, meta = await list_movements(
            db,
            product_id,
            movement_type=movement_type,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
        return MovementListResponse(
            items=[MovementResponse.model_validate(m) for m in items],
            meta=meta,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/products/{product_id}/movements/summary",
    response_model=MovementSummaryResponse,
)
async def movement_summary_endpoint(
    product_id: uuid.UUID,
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> MovementSummaryResponse:
    try:
        summary = await movement_summary(
            db, product_id, from_date=from_date, to_date=to_date
        )
        return MovementSummaryResponse(
            product_id=product_id,
            from_date=from_date,
            to_date=to_date,
            summary=summary,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
