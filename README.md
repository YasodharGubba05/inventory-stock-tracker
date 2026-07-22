# Inventory & Stock Movement Tracking Service

**Author:** Yasodhar Gubba

A production-ready FastAPI backend for single-warehouse inventory tracking. Every quantity change is recorded as an **immutable, append-only** stock movement inside a single database transaction — with row-level locking to prevent concurrent sales from driving stock negative.

[![CI](https://github.com/YasodharGubba05/inventory-stock-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/YasodharGubba05/inventory-stock-tracker/actions/workflows/ci.yml)

## Quick Start (Docker — recommended)

```bash
docker compose up --build
```

This starts:
- **PostgreSQL 16** on port `5432`
- **API** on [http://localhost:8000](http://localhost:8000)
- Runs Alembic migrations and seeds sample data automatically

Interactive API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Health check: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

## Local Development (without Docker)

**Requirements:** Python 3.11+, PostgreSQL 16+

```bash
cp .env.example .env
pip install ".[dev]"
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Overview

All routes are versioned under `/api/v1`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/products` | Create product (optional initial stock via RESTOCK movement) |
| `GET` | `/products` | List products (paginated, filter by `sku`, `is_active`) |
| `GET` | `/products/low-stock?threshold=10` | Products at or below threshold |
| `GET` | `/products/{id}` | Get product |
| `PATCH` | `/products/{id}` | Update name/SKU only (optimistic locking via `version`) |
| `DELETE` | `/products/{id}` | Hard-delete if no movements; otherwise deactivate (`409`) |
| `POST` | `/products/{id}/movements` | Record RESTOCK / SALE / ADJUSTMENT |
| `GET` | `/products/{id}/movements` | Paginated movement history (chronological) |
| `GET` | `/products/{id}/movements/summary` | Aggregates by movement type |
| `GET` | `/health` | Liveness/readiness with DB connectivity check |

See [`requests.http`](requests.http) for copy-paste examples.

### Movement rules

- **RESTOCK** / **SALE**: `quantity` is an unsigned magnitude; sign is inferred from type.
- **ADJUSTMENT**: `quantity` is a signed delta; `reason` is required.
- **SALE** that would drive `quantity_on_hand` below zero → `409 Conflict`, no partial write.
- Optional **`Idempotency-Key`** header on movement creation prevents double-application on client retries.

## Design Decisions

### Immutable movement log

`StockMovement` rows are append-only: no update/delete routes, no service methods, no ORM update paths. Each row stores `resulting_quantity` — a snapshot after the movement — so the log is self-verifying and audit-friendly. Future hardening: PostgreSQL trigger to reject `UPDATE`/`DELETE` on `stock_movements`.

### Transactional quantity updates

`quantity_on_hand` is a denormalized cache updated **only** inside the movement-creation transaction:

1. `SELECT ... FOR UPDATE` on the product row (pessimistic row lock)
2. Validate business rules (non-negative stock, active product, ADJUSTMENT reason)
3. Insert `StockMovement`
4. Update `Product.quantity_on_hand` and bump `version`
5. Commit

There is no code path that modifies quantity outside this flow. A DB-level `CHECK (quantity_on_hand >= 0)` provides defense in depth.

### Concurrency: pessimistic locking (primary) + optimistic locking (product metadata)

**Movements** use `SELECT ... FOR UPDATE` so concurrent SALE requests on the same SKU serialize at the database — exactly one succeeds when stock can satisfy only one. This is the correctness-first choice for bursty retail workloads where a few SKUs become hot during promotions.

**Product metadata updates** (name, SKU) use optimistic locking via the `version` column: PATCH requires the client's expected version; mismatch returns `409` with retry guidance. Optimistic locking avoids holding locks on read-heavy product catalog paths but would thrash under high write contention — acceptable here since metadata changes are rare compared to movements.

### UUID primary keys

Public IDs are UUIDs rather than sequential integers to avoid enumeration and simplify future distributed/sharded deployments.

### PostgreSQL as production target

SQLite is supported for fast local unit tests (`sqlite+aiosqlite:///:memory:`), but PostgreSQL is the intended production database. SQLite's coarse locking cannot meaningfully demonstrate row-level concurrency control — the concurrency test requires PostgreSQL and is skipped on SQLite.

### Low-stock threshold

A global query parameter (`threshold`, default `10`) rather than per-product fields — simpler for a single-warehouse MVP. Per-SKU reorder points would be a natural extension.

## Testing

```bash
# SQLite in-memory (fast; concurrency test skipped)
pytest -v

# Full suite including concurrency test (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://inventory:inventory@localhost:5432/inventory_test pytest -v

# Via Docker
make test
```

The **concurrency test** fires two simultaneous SALE requests against a product with quantity `5` and sale quantity `5`. It asserts exactly one `201` and one `409`, final quantity `0`, and `sum(deltas) == quantity_on_hand`.

## Deployment

### Railway (production)

1. Push this repo to GitHub.
2. In [Railway](https://railway.app): **New Project → Deploy from GitHub repo**.
3. Add a **PostgreSQL** database to the project.
4. On the **web service**, set variables:

   | Variable | Value |
   |----------|--------|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (use variable reference picker) |
   | `LOG_LEVEL` | `INFO` |
   | `LOG_JSON` | `true` |

5. **Settings → Networking → Generate Domain** to get a public URL.
6. Deploy. On startup the app automatically runs migrations, seeds sample data, and binds to Railway's `PORT`.

`railway.toml` and `scripts/start.sh` handle the start command — no manual config needed unless you override it.

**Verify after deploy:**

```bash
curl https://YOUR-APP.up.railway.app/api/v1/health
curl https://YOUR-APP.up.railway.app/api/v1/products
```

Interactive docs: `https://YOUR-APP.up.railway.app/docs`

> **Note:** Railway provides `postgresql://` URLs; the app auto-converts them to `postgresql+asyncpg://` for async SQLAlchemy.

### Live Demo

<!-- Replace with your Railway URL after deploy -->
- API: `https://YOUR-APP.up.railway.app`
- Docs: `https://YOUR-APP.up.railway.app/docs`
- Health: `https://YOUR-APP.up.railway.app/api/v1/health`

### Docker / other platforms

The included `Dockerfile` is production-oriented:
- Slim Python 3.11 image with production dependencies only
- Connection pooling with `pool_pre_ping`
- JSON structured logging (`structlog`)
- Health check at `/api/v1/health`

Environment variables (see [`.env.example`](.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL URL (`postgresql://` or `postgresql+asyncpg://`) |
| `PORT` | `8000` | Server port (set automatically by Railway) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_JSON` | `true` | JSON log output for log aggregators |

**Not implemented (deferred):** rate limiting — would add at API gateway or via `slowapi` in production.

## System Design Reflection

### Q1 — Two terminals, same product, near-simultaneous SALE

Both requests can read the same `quantity_on_hand` before either writes — a classic **lost-update / TOCTOU** race. Both see sufficient stock, both decrement, and the final quantity can be wrong or negative.

**Fix:** serialize updates on the product row. This service uses **`SELECT ... FOR UPDATE`** (pessimistic locking) as the primary mechanism: the second transaction blocks until the first commits, then re-reads the current quantity and correctly rejects the sale if stock is insufficient.

**Alternative:** optimistic locking — read `version`, apply movement, update with `WHERE version = ?`, retry on mismatch. Better when contention is low (avoids lock waits) but can starve or thrash under high contention on hot SKUs.

**Why pessimistic for this workload:** e-commerce sales are often bursty on a few SKUs during promotions. Correctness on inventory is non-negotiable; slightly reduced throughput on hot rows is an acceptable tradeoff for a single-warehouse system. At scale, you'd shard hot SKUs or use warehouse-level partitioning (see Q2).

### Q2 — Scaling from 1 warehouse to 50 warehouses

Introduce a **`Warehouse`** entity. Quantity becomes a property of `(product_id, warehouse_id)` rather than the product alone. Movements carry `warehouse_id`; locking is **per warehouse row**, so contention in warehouse A doesn't block warehouse B.

Read-heavy queries like "total quantity across all warehouses" should use a **denormalized rollup** (materialized view or async aggregator) rather than summing 50 rows on every catalog read.

Geographically distributed warehouses with local databases introduce **eventual consistency** for cross-region reads; a central reconciliation job would detect drift between movement logs and denormalized quantities.

**Transfers between warehouses** become a new domain concept: atomically a decrement at source and increment at destination — either two linked movements in one transaction (same DB) or a saga/outbox pattern across regions. This raises the same atomicity question as concurrent sales, but across warehouse boundaries.

## Project Structure

```
app/
├── api/v1/          # Route handlers
├── core/            # Config, structured logging
├── db/              # SQLAlchemy session, Base
├── models/          # ORM models
├── schemas/         # Pydantic v2 request/response models
├── services/        # Business logic (movements, locking)
└── main.py
alembic/             # Database migrations
tests/               # Unit, integration, concurrency tests
scripts/seed.py      # Sample data for reviewers
```

## Implemented vs. Deferred

| Feature | Status |
|---------|--------|
| Core CRUD + movements | ✅ |
| Row-level locking (`FOR UPDATE`) | ✅ |
| Optimistic locking on product PATCH | ✅ |
| Immutable movement log + `resulting_quantity` | ✅ |
| Soft-delete when movements exist | ✅ |
| Pagination | ✅ |
| Low-stock endpoint | ✅ |
| Idempotency keys | ✅ |
| Docker Compose + CI | ✅ |
| Concurrency test | ✅ (PostgreSQL) |
| DB trigger blocking movement UPDATE/DELETE | Deferred (documented) |
| Rate limiting | Deferred (gateway-level in prod) |
