import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.product import IdempotencyRecord, MovementType, Product, StockMovement
from app.schemas.movement import MovementCreate, MovementSummaryItem
from app.schemas.pagination import PaginationMeta
from app.services.product_service import (
    InsufficientStockError,
    ProductInactiveError,
    ProductNotFoundError,
)

logger = get_logger(__name__)


class IdempotencyConflictError(Exception):
    pass


def _compute_delta(payload: MovementCreate) -> int:
    if payload.movement_type == MovementType.RESTOCK:
        return payload.quantity
    if payload.movement_type == MovementType.SALE:
        return -payload.quantity
    return payload.quantity


def _hash_request(payload: MovementCreate) -> str:
    body = payload.model_dump(mode="json")
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


async def create_movement(
    session: AsyncSession,
    product_id: uuid.UUID,
    payload: MovementCreate,
) -> StockMovement:
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if not product:
        raise ProductNotFoundError(f"Product {product_id} not found")
    if not product.is_active:
        raise ProductInactiveError("Cannot record movement for inactive product")

    delta = _compute_delta(payload)
    new_quantity = product.quantity_on_hand + delta

    if new_quantity < 0:
        raise InsufficientStockError(
            f"SALE would reduce quantity below zero (current: {product.quantity_on_hand}, "
            f"requested: {abs(delta)})"
        )

    movement = StockMovement(
        product_id=product.id,
        movement_type=payload.movement_type,
        quantity_delta=delta,
        reason=payload.reason.strip() if payload.reason else None,
        resulting_quantity=new_quantity,
    )
    session.add(movement)

    product.quantity_on_hand = new_quantity
    product.version += 1

    await session.flush()
    await session.refresh(movement)

    logger.info(
        "stock_movement_created",
        product_id=str(product.id),
        movement_id=str(movement.id),
        movement_type=payload.movement_type.value,
        quantity_delta=delta,
        resulting_quantity=new_quantity,
    )

    return movement


async def list_movements(
    session: AsyncSession,
    product_id: uuid.UUID,
    *,
    movement_type: MovementType | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[StockMovement], PaginationMeta]:
    await _ensure_product_exists(session, product_id)

    query = select(StockMovement).where(StockMovement.product_id == product_id)
    count_query = (
        select(func.count())
        .select_from(StockMovement)
        .where(StockMovement.product_id == product_id)
    )

    if movement_type is not None:
        query = query.where(StockMovement.movement_type == movement_type)
        count_query = count_query.where(StockMovement.movement_type == movement_type)
    if from_date is not None:
        query = query.where(StockMovement.created_at >= from_date)
        count_query = count_query.where(StockMovement.created_at >= from_date)
    if to_date is not None:
        query = query.where(StockMovement.created_at <= to_date)
        count_query = count_query.where(StockMovement.created_at <= to_date)

    total = await session.scalar(count_query) or 0
    result = await session.scalars(
        query.order_by(StockMovement.created_at.asc(), StockMovement.sequence.asc())
        .limit(limit)
        .offset(offset)
    )
    items = list(result.all())
    meta = PaginationMeta(
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )
    return items, meta


async def movement_summary(
    session: AsyncSession,
    product_id: uuid.UUID,
    *,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[MovementSummaryItem]:
    await _ensure_product_exists(session, product_id)

    query = (
        select(
            StockMovement.movement_type,
            func.count().label("count"),
            func.coalesce(func.sum(StockMovement.quantity_delta), 0).label("net_quantity"),
        )
        .where(StockMovement.product_id == product_id)
        .group_by(StockMovement.movement_type)
    )

    if from_date is not None:
        query = query.where(StockMovement.created_at >= from_date)
    if to_date is not None:
        query = query.where(StockMovement.created_at <= to_date)

    rows = await session.execute(query)
    return [
        MovementSummaryItem(
            movement_type=row.movement_type,
            count=row.count,
            net_quantity=int(row.net_quantity),
        )
        for row in rows.all()
    ]


async def verify_quantity_integrity(session: AsyncSession, product_id: uuid.UUID) -> bool:
    product = await session.get(Product, product_id)
    if not product:
        return False
    total_delta = await session.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity_delta), 0)).where(
            StockMovement.product_id == product_id
        )
    )
    return int(total_delta or 0) == product.quantity_on_hand


async def get_idempotency_record(
    session: AsyncSession,
    *,
    idempotency_key: str,
    endpoint: str,
) -> IdempotencyRecord | None:
    return await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.idempotency_key == idempotency_key,
            IdempotencyRecord.endpoint == endpoint,
        )
    )


async def store_idempotency_record(
    session: AsyncSession,
    *,
    idempotency_key: str,
    endpoint: str,
    request_hash: str,
    response_status: int,
    response_body: str,
) -> None:
    record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        endpoint=endpoint,
        request_hash=request_hash,
        response_status=response_status,
        response_body=response_body,
    )
    session.add(record)
    await session.flush()


async def _ensure_product_exists(session: AsyncSession, product_id: uuid.UUID) -> None:
    exists = await session.scalar(select(Product.id).where(Product.id == product_id))
    if not exists:
        raise ProductNotFoundError(f"Product {product_id} not found")
