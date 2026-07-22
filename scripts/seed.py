"""Database seed script — creates sample products and movement history."""

import asyncio
import sys

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.product import Product
from app.schemas.movement import MovementCreate
from app.models.product import MovementType
from app.services.movement_service import create_movement
from app.services.product_service import create_product


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(Product).limit(1))
        if existing:
            print("Database already seeded, skipping.")
            return

        products_data = [
            ("SKU-001", "Widget Pro", 100),
            ("SKU-002", "Gadget Basic", 25),
            ("SKU-003", "Premium Bundle", 5),
            ("SKU-004", "Spare Part A", 0),
        ]

        for sku, name, qty in products_data:
            product = await create_product(session, sku=sku, name=name, quantity_on_hand=qty)
            await session.flush()

            if sku == "SKU-001":
                await create_movement(
                    session,
                    product.id,
                    MovementCreate(movement_type=MovementType.SALE, quantity=10),
                )
                await create_movement(
                    session,
                    product.id,
                    MovementCreate(movement_type=MovementType.RESTOCK, quantity=20),
                )
            elif sku == "SKU-002":
                await create_movement(
                    session,
                    product.id,
                    MovementCreate(
                        movement_type=MovementType.ADJUSTMENT,
                        quantity=-3,
                        reason="Damaged in warehouse",
                    ),
                )

        await session.commit()
        print("Seed data created successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except Exception as exc:
        print(f"Seed failed: {exc}", file=sys.stderr)
        sys.exit(1)
