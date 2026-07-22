# Inventory & Stock Movement Tracking Service

**Author:** Yasodhar Gubba  
**Version:** 1.0.0  
**Target Environment:** Production (Docker, Render)

[![CI](https://github.com/YasodharGubba05/inventory-stock-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/YasodharGubba05/inventory-stock-tracker/actions/workflows/ci.yml)
[![FastAPI](https://img.shields.io/badge/Framework-FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-PostgreSQL%2016-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)

A production-grade, audit-compliant FastAPI microservice designed for single-warehouse inventory tracking. The system enforces data consistency and prevents race conditions (e.g., double sales, negative stock) under heavy concurrent write loads using database-level transaction control and strict append-only journaling.

---

## 🌟 Key Enterprise Features

*   **Immutable Append-Only Audit Trail:** Quantity changes are recorded as immutable stock movements. Updates or deletions of historical movements are prohibited at the application level to ensure strict financial and operational audit compliance.
*   **Race Condition Mitigation:** Employs database-level pessimistic row-locking (`SELECT ... FOR UPDATE`) on product records inside a transaction, preventing negative stock levels during flash sales.
*   **Dual Concurrency Locking Strategy:**
    *   *Pessimistic Locking* for stock movements to serialize stock allocation.
    *   *Optimistic Concurrency Control (OCC)* using version checks for metadata updates (e.g., updates to product descriptions or SKUs).
*   **Idempotent Operations:** Supports client-provided `Idempotency-Key` headers on mutation endpoints to avoid duplicate processing on network retries.
*   **UUID Primary Keys:** Uses random UUIDv4 identifiers across endpoints to prevent resource enumeration.

---

## 🏗️ System Architecture & Concurrency Flow

The sequence below illustrates how the service handles stock movements atomically. Concurrent updates to the same product SKU are serialized at the database level to ensure data integrity.

```mermaid
sequenceDiagram
    autonumber
    Client->>API: POST /api/v1/products/{id}/movements (Idempotency-Key)
    API->>Database: BEGIN TRANSACTION
    API->>Database: SELECT * FROM products WHERE id = {id} FOR UPDATE (Row Lock)
    Note over Database: Serializes concurrent updates on same product
    Database-->>API: Product Data & current quantity_on_hand
    API-->>API: Validate rules (non-negative stock, active product, reason if adjustment)
    alt Validation Fails
        API->>Database: ROLLBACK
        API-->>Client: 409 Conflict / 400 Bad Request
    else Validation Passes
        API->>Database: INSERT INTO stock_movements (resulting_quantity, ...)
        API->>Database: UPDATE products SET quantity_on_hand, version = version + 1 WHERE id = {id}
        API->>Database: COMMIT
        Database-->>API: Transaction Committed
        API-->>Client: 201 Created (StockMovement JSON)
    end
```

---

## 🚀 Getting Started

### Prerequisites
*   Docker and Docker Compose
*   *Alternatively (for local execution):* Python 3.11+, PostgreSQL 16+

### Option A: Standard Containerized Run (Recommended)
This method spins up a PostgreSQL 16 database instance alongside the FastAPI application, automatically executing migrations and seeding mock data.

```bash
docker compose up --build
```
*   **Interactive API Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
*   **Health Check:** [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

### Option B: Local Setup (Bare-Metal)
1. Clone the repository and navigate to the project directory.
2. Initialize configuration:
   ```bash
   cp .env.example .env
   ```
3. Install dependencies:
   ```bash
   pip install ".[dev]"
   ```
4. Run migrations and seed data:
   ```bash
   alembic upgrade head
   python scripts/seed.py
   ```
5. Start the development server:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

---

## ⚙️ Configuration Registry

The service is configured via environment variables.

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | *(Required)* | Fully qualified JDBC/SQLAlchemy connection string (`postgresql+asyncpg://...`) |
| `PORT` | `8000` | Port on which the application server listens |
| `LOG_LEVEL` | `INFO` | Verbosity of the structured logger (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_JSON` | `true` | Outputs logs in JSON format (ideal for ELK stack, Datadog, CloudWatch) |

---

## 📋 API Specification

All endpoints are versioned under `/api/v1` and return standard JSON payloads.

| Method | Endpoint | Description | Idempotency |
| :--- | :--- | :--- | :--- |
| `POST` | `/products` | Creates a new product catalog item | Yes (optional initial restock) |
| `GET` | `/products` | Lists products (paginated, supports `sku` and `is_active` filters) | Read-only |
| `GET` | `/products/low-stock` | Retrieves products at or below the specified stock `threshold` | Read-only |
| `GET` | `/products/{id}` | Retrieves a single product by UUID | Read-only |
| `PATCH` | `/products/{id}` | Updates metadata (name/SKU) utilizing OCC version check | Yes |
| `DELETE` | `/products/{id}` | Deactivates if stock movement logs exist; deletes otherwise | Yes |
| `POST` | `/products/{id}/movements` | Registers a stock movement (`RESTOCK`, `SALE`, `ADJUSTMENT`) | Yes (via `Idempotency-Key`) |
| `GET` | `/products/{id}/movements` | Paginated historical ledger of stock movements (chronological) | Read-only |
| `GET` | `/products/{id}/movements/summary` | Aggregated statistical summary of movements by type | Read-only |
| `GET` | `/health` | Liveness & readiness probes verifying database connectivity | Read-only |

For API testing payloads, see [`requests.http`](requests.http).

---

## 🧪 Testing Suite

We maintain unit, integration, and high-concurrency race condition test suites.

```bash
# Execute fast tests using SQLite in-memory db (skips PostgreSQL concurrency tests)
pytest -v

# Execute full suite including PostgreSQL concurrency simulation
DATABASE_URL=postgresql+asyncpg://inventory:inventory@localhost:5432/inventory_test pytest -v

# Run the complete test suite using Docker Compose
make test
```

> [!NOTE]
> The **concurrency test** simulates race conditions by firing parallel allocation requests against a hot SKU. It verifies that exactly one transaction succeeds when quantity is depleted, keeping the ledger and product quantity fully synchronized.

---

## 📈 Architecture Scaling Roadmap

### 1. Scaling to Multiple Warehouses
To scale the service beyond a single warehouse to a multi-node, multi-warehouse topology:
*   **Schema Extension:** Introduce a `Warehouse` entity. Map the inventory balance (`quantity_on_hand`) to a composite relation `(product_id, warehouse_id)` instead of a single product column.
*   **Granular Locking:** Row locks (`FOR UPDATE`) will target the specific warehouse inventory rows, ensuring transaction contention in Warehouse A does not block allocations in Warehouse B.
*   **Inventory Transfers:** Transfers will be implemented as atomic multi-movement transactions (deduct from Source, credit to Destination).

### 2. Distributed Reconciliation
In a distributed network, local databases may experience replication lag:
*   **Async Rollups:** Read-heavy catalog queries can read from replica read-only databases or cached datastores (e.g., Redis).
*   **Outbox Pattern:** Use transactional outboxes to publish inventory events to Kafka/RabbitMQ to update search models or catalog caches.
*   **Reconciliation Worker:** Run scheduled reconciliation workers that compare the append-only logs against denormalized cached totals to detect and resolve drift.

---

## ☁️ Deployment

### Production Deployment to Render
This project includes a `render.yaml` Blueprint spec file that automatically spins up a PostgreSQL database and a FastAPI Docker container on Render's free tier.

1. Push this repository to your GitHub account.
2. Log in to [Render](https://render.com).
3. Go to **Blueprints** and click **New Blueprint Instance** (or **New** -> **Blueprint**).
4. Connect your GitHub repository.
5. Render will automatically read the `render.yaml` spec and prompt you to create the services. Click **Apply**.
6. Render will automatically provision the PostgreSQL database, build the Docker container, link the `DATABASE_URL` environment variable, run alembic migrations, seed mock data, and expose the API publicly.

