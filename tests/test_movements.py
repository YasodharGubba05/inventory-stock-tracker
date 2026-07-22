import pytest
from httpx import AsyncClient


async def _create_product(client: AsyncClient, sku: str, qty: int = 100) -> dict:
    response = await client.post(
        "/api/v1/products",
        json={"sku": sku, "name": f"Product {sku}", "quantity_on_hand": qty},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_record_restock_and_sale(client: AsyncClient):
    product = await _create_product(client, "MOV-001", qty=50)

    restock = await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={"movement_type": "RESTOCK", "quantity": 10},
    )
    assert restock.status_code == 201
    assert restock.json()["resulting_quantity"] == 60

    sale = await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={"movement_type": "SALE", "quantity": 15},
    )
    assert sale.status_code == 201
    assert sale.json()["resulting_quantity"] == 45

    get_resp = await client.get(f"/api/v1/products/{product['id']}")
    assert get_resp.json()["quantity_on_hand"] == 45


@pytest.mark.asyncio
async def test_sale_rejected_when_insufficient_stock(client: AsyncClient):
    product = await _create_product(client, "MOV-002", qty=5)

    response = await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={"movement_type": "SALE", "quantity": 10},
    )
    assert response.status_code == 409

    get_resp = await client.get(f"/api/v1/products/{product['id']}")
    assert get_resp.json()["quantity_on_hand"] == 5


@pytest.mark.asyncio
async def test_adjustment_requires_reason(client: AsyncClient):
    product = await _create_product(client, "MOV-003", qty=10)

    response = await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={"movement_type": "ADJUSTMENT", "quantity": -2},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_adjustment_with_reason(client: AsyncClient):
    product = await _create_product(client, "MOV-004", qty=10)

    response = await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={
            "movement_type": "ADJUSTMENT",
            "quantity": -2,
            "reason": "Cycle count correction",
        },
    )
    assert response.status_code == 201
    assert response.json()["quantity_delta"] == -2
    assert response.json()["resulting_quantity"] == 8


@pytest.mark.asyncio
async def test_movement_history_pagination(client: AsyncClient):
    product = await _create_product(client, "MOV-005", qty=0)
    for i in range(5):
        await client.post(
            f"/api/v1/products/{product['id']}/movements",
            json={"movement_type": "RESTOCK", "quantity": 1},
        )

    response = await client.get(
        f"/api/v1/products/{product['id']}/movements",
        params={"limit": 2, "offset": 0},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["meta"]["total"] == 5
    assert data["meta"]["has_more"] is True


@pytest.mark.asyncio
async def test_movement_summary(client: AsyncClient):
    product = await _create_product(client, "MOV-006", qty=20)
    await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={"movement_type": "SALE", "quantity": 5},
    )

    response = await client.get(f"/api/v1/products/{product['id']}/movements/summary")
    assert response.status_code == 200
    summary = {item["movement_type"]: item for item in response.json()["summary"]}
    assert summary["RESTOCK"]["count"] == 1
    assert summary["SALE"]["count"] == 1


@pytest.mark.asyncio
async def test_idempotency_key(client: AsyncClient):
    product = await _create_product(client, "MOV-007", qty=10)
    headers = {"Idempotency-Key": "idem-test-001"}
    payload = {"movement_type": "SALE", "quantity": 2}

    first = await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json=payload,
        headers=headers,
    )
    second = await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json=payload,
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    get_resp = await client.get(f"/api/v1/products/{product['id']}")
    assert get_resp.json()["quantity_on_hand"] == 8


@pytest.mark.asyncio
async def test_quantity_matches_movement_log(client: AsyncClient):
    product = await _create_product(client, "MOV-008", qty=30)
    await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={"movement_type": "SALE", "quantity": 7},
    )
    await client.post(
        f"/api/v1/products/{product['id']}/movements",
        json={"movement_type": "RESTOCK", "quantity": 3},
    )

    product_resp = await client.get(f"/api/v1/products/{product['id']}")
    movements_resp = await client.get(f"/api/v1/products/{product['id']}/movements")

    quantity = product_resp.json()["quantity_on_hand"]
    total_delta = sum(m["quantity_delta"] for m in movements_resp.json()["items"])
    assert quantity == total_delta
