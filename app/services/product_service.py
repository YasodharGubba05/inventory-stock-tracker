import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.product import IdempotencyRecord, MovementType, Product, StockMovement
from app.schemas.movement import MovementCreate, MovementSummaryItem
from app.schemas.pagination import PaginationMeta

logger = get_logger(__name__)
settings = get_settings()


class ProductNotFoundError(Exception):
    pass


class DuplicateSKUError(Exception):
    pass


class ProductHasMovementsError(Exception):
    pass


class VersionConflictError(Exception):
    pass


class InsufficientStockError(Exception):
    pass


class ProductInactiveError(Exception):
    pass


async def create_product(
    session: AsyncSession,
    *,
    sku: str,
    name: str,
    quantity_on_hand: int = 0,
) -> Product:
    existing = await session.scalar(select(Product).where(Product.sku == sku))
    if existing:
        raise DuplicateSKUError(f"Product with SKU '{sku}' already exists")

    product = Product(sku=sku, name=name, quantity_on_hand=0)
    session.add(product)
    await session.flush()

    if quantity_on_hand > 0:
        movement = StockMovement(
            product_id=product.id,
            movement_type=MovementType.RESTOCK,
            quantity_delta=quantity_on_hand,
            reason=None,
            resulting_quantity=quantity_on_hand,
        )
        session.add(movement)
        product.quantity_on_hand = quantity_on_hand
        product.version += 1

    await session.flush()
    await session.refresh(product)
    return product


async def get_product(session: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if not product:
        raise ProductNotFoundError(f"Product {product_id} not found")
    return product


async def list_products(
    session: AsyncSession,
    *,
    sku: str | None = None,
    is_active: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Product], PaginationMeta]:
    query = select(Product)
    count_query = select(func.count()).select_from(Product)

    if sku is not None:
        query = query.where(Product.sku.ilike(f"%{sku}%"))
        count_query = count_query.where(Product.sku.ilike(f"%{sku}%"))
    if is_active is not None:
        query = query.where(Product.is_active == is_active)
        count_query = count_query.where(Product.is_active == is_active)

    total = await session.scalar(count_query) or 0
    result = await session.scalars(
        query.order_by(Product.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(result.all())
    meta = PaginationMeta(
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )
    return items, meta


async def update_product(
    session: AsyncSession,
    product_id: uuid.UUID,
    *,
    sku: str | None,
    name: str | None,
    expected_version: int,
) -> Product:
    product = await session.scalar(
        select(Product).where(Product.id == product_id).with_for_update()
    )
    if not product:
        raise ProductNotFoundError(f"Product {product_id} not found")

    if product.version != expected_version:
        raise VersionConflictError(
            f"Version mismatch: expected {expected_version}, current is {product.version}. "
            "Re-fetch the product and retry with the updated version."
        )

    if sku is not None and sku != product.sku:
        existing = await session.scalar(
            select(Product).where(Product.sku == sku, Product.id != product_id)
        )
        if existing:
            raise DuplicateSKUError(f"Product with SKU '{sku}' already exists")
        product.sku = sku

    if name is not None:
        product.name = name

    product.version += 1
    await session.flush()
    await session.refresh(product)
    return product


async def delete_product(session: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await get_product(session, product_id)

    movement_count = await session.scalar(
        select(func.count()).select_from(StockMovement).where(StockMovement.product_id == product_id)
    )
    if movement_count and movement_count > 0:
        product.is_active = False
        product.version += 1
        await session.flush()
        await session.refresh(product)
        raise ProductHasMovementsError(
            "Product has movement history and cannot be hard-deleted; deactivated instead"
        )

    await session.delete(product)
    await session.flush()
    return product


async def list_low_stock(
    session: AsyncSession,
    *,
    threshold: int,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Product], PaginationMeta]:
    query = (
        select(Product)
        .where(Product.is_active.is_(True))
        .where(Product.quantity_on_hand <= threshold)
    )
    count_query = (
        select(func.count())
        .select_from(Product)
        .where(Product.is_active.is_(True))
        .where(Product.quantity_on_hand <= threshold)
    )

    total = await session.scalar(count_query) or 0
    result = await session.scalars(
        query.order_by(Product.quantity_on_hand.asc(), Product.sku.asc()).limit(limit).offset(offset)
    )
    items = list(result.all())
    meta = PaginationMeta(
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )
    return items, meta
