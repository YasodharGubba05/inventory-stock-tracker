import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.product import ProductCreate, ProductListResponse, ProductResponse, ProductUpdate
from app.services.product_service import (
    DuplicateSKUError,
    ProductHasMovementsError,
    ProductNotFoundError,
    VersionConflictError,
    create_product,
    delete_product,
    get_product,
    list_low_stock,
    list_products,
    update_product,
)

router = APIRouter()
settings = get_settings()


def _clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    limit = min(max(limit, 1), settings.max_page_size)
    offset = max(offset, 0)
    return limit, offset


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product_endpoint(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    try:
        product = await create_product(
            db,
            sku=payload.sku,
            name=payload.name,
            quantity_on_hand=payload.quantity_on_hand,
        )
        return ProductResponse.model_validate(product)
    except DuplicateSKUError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=ProductListResponse)
async def list_products_endpoint(
    sku: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=settings.default_page_size, ge=1),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    limit, offset = _clamp_pagination(limit, offset)
    items, meta = await list_products(db, sku=sku, is_active=is_active, limit=limit, offset=offset)
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in items],
        meta=meta,
    )


@router.get("/low-stock", response_model=ProductListResponse)
async def low_stock_endpoint(
    threshold: int = Query(default=settings.default_low_stock_threshold, ge=0),
    limit: int = Query(default=settings.default_page_size, ge=1),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ProductListResponse:
    limit, offset = _clamp_pagination(limit, offset)
    items, meta = await list_low_stock(db, threshold=threshold, limit=limit, offset=offset)
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in items],
        meta=meta,
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product_endpoint(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    try:
        product = await get_product(db, product_id)
        return ProductResponse.model_validate(product)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product_endpoint(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProductResponse:
    if payload.sku is None and payload.name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of sku or name must be provided",
        )
    try:
        product = await update_product(
            db,
            product_id,
            sku=payload.sku,
            name=payload.name,
            expected_version=payload.version,
        )
        return ProductResponse.model_validate(product)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateSKUError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except VersionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_endpoint(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await delete_product(db, product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProductHasMovementsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
