import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import product  # noqa: F401


@pytest.mark.asyncio
async def test_concurrent_sales_exactly_one_succeeds(is_postgres: bool):
    if not is_postgres:
        pytest.skip("Concurrency test requires PostgreSQL (row-level locking)")

    database_url = __import__("os").environ["DATABASE_URL"]
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        from fastapi import HTTPException

        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except HTTPException:
                await session.commit()
                raise
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/products",
            json={"sku": "RACE-001", "name": "Race Product", "quantity_on_hand": 5},
        )
        assert create_resp.status_code == 201
        product_id = create_resp.json()["id"]

        async def attempt_sale():
            return await client.post(
                f"/api/v1/products/{product_id}/movements",
                json={"movement_type": "SALE", "quantity": 5},
            )

        results = await asyncio.gather(attempt_sale(), attempt_sale())
        statuses = sorted(r.status_code for r in results)

        assert statuses == [201, 409]

        product_resp = await client.get(f"/api/v1/products/{product_id}")
        assert product_resp.json()["quantity_on_hand"] == 0

        movements_resp = await client.get(f"/api/v1/products/{product_id}/movements")
        movements = movements_resp.json()["items"]
        sale_movements = [m for m in movements if m["movement_type"] == "SALE"]
        assert len(sale_movements) == 1

        total_delta = sum(m["quantity_delta"] for m in movements)
        assert total_delta == product_resp.json()["quantity_on_hand"]

    app.dependency_overrides.clear()
    await engine.dispose()
