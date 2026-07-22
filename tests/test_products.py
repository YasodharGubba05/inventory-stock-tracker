import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_product(client: AsyncClient):
    response = await client.post(
        "/api/v1/products",
        json={"sku": "TEST-001", "name": "Test Product", "quantity_on_hand": 10},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["sku"] == "TEST-001"
    assert data["quantity_on_hand"] == 10
    assert data["is_active"] is True
    assert data["version"] == 2  # bumped by initial RESTOCK movement


@pytest.mark.asyncio
async def test_duplicate_sku_rejected(client: AsyncClient):
    payload = {"sku": "DUP-001", "name": "First", "quantity_on_hand": 0}
    assert (await client.post("/api/v1/products", json=payload)).status_code == 201
    response = await client.post("/api/v1/products", json={**payload, "name": "Second"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_list_and_filter_products(client: AsyncClient):
    await client.post("/api/v1/products", json={"sku": "LIST-A", "name": "A", "quantity_on_hand": 0})
    await client.post("/api/v1/products", json={"sku": "LIST-B", "name": "B", "quantity_on_hand": 0})

    response = await client.get("/api/v1/products", params={"sku": "LIST-A"})
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["total"] >= 1
    assert any(item["sku"] == "LIST-A" for item in data["items"])


@pytest.mark.asyncio
async def test_update_product_with_version(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/products",
        json={"sku": "UPD-001", "name": "Original", "quantity_on_hand": 0},
    )
    product = create_resp.json()

    response = await client.patch(
        f"/api/v1/products/{product['id']}",
        json={"name": "Updated", "version": product["version"]},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated"
    assert response.json()["version"] == product["version"] + 1


@pytest.mark.asyncio
async def test_update_version_conflict(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/products",
        json={"sku": "VER-001", "name": "Version Test", "quantity_on_hand": 0},
    )
    product = create_resp.json()
    original_version = product["version"]

    await client.patch(
        f"/api/v1/products/{product['id']}",
        json={"name": "Updated once", "version": original_version},
    )

    response = await client.patch(
        f"/api/v1/products/{product['id']}",
        json={"name": "Stale", "version": original_version},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_delete_product_with_movements_deactivates(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/products",
        json={"sku": "DEL-001", "name": "Deletable", "quantity_on_hand": 5},
    )
    product = create_resp.json()

    response = await client.delete(f"/api/v1/products/{product['id']}")
    assert response.status_code == 409

    get_resp = await client.get(f"/api/v1/products/{product['id']}")
    assert get_resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_delete_product_without_movements(client: AsyncClient):
    create_resp = await client.post(
        "/api/v1/products",
        json={"sku": "DEL-002", "name": "Hard Delete", "quantity_on_hand": 0},
    )
    product = create_resp.json()

    response = await client.delete(f"/api/v1/products/{product['id']}")
    assert response.status_code == 204

    get_resp = await client.get(f"/api/v1/products/{product['id']}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_low_stock_endpoint(client: AsyncClient):
    await client.post(
        "/api/v1/products",
        json={"sku": "LOW-001", "name": "Low Stock", "quantity_on_hand": 3},
    )
    response = await client.get("/api/v1/products/low-stock", params={"threshold": 5})
    assert response.status_code == 200
    skus = [item["sku"] for item in response.json()["items"]]
    assert "LOW-001" in skus


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
