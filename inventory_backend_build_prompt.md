# Inventory & Stock Movement Tracking Service — Full Build Prompt

This is a complete engineering spec you (or an AI coding assistant like Claude Code) can follow end-to-end to build the take-home challenge and make it stand out from a typical submission. It expands the original assignment PDF into a concrete implementation plan, adds all bonus features, and layers on extras that signal senior-level engineering judgment.

**Deadline:** 23 July 2026, 07:00 PM IST — plan for this to take 4–8 focused hours, not a rushed 90-minute hack.

---

## 1. Project Summary

Build a backend service for a single-warehouse e-commerce team that:
- Tracks products (SKU, name, quantity on hand).
- Records every stock movement (RESTOCK, SALE, ADJUSTMENT) as an **immutable, append-only log**.
- Guarantees the product's quantity and the movement log can never drift out of sync, even under concurrent requests.
- Rejects any SALE that would drive quantity below zero.
- Exposes a clean, well-documented REST API.

The evaluators explicitly said they care most about: **transactional correctness, the "never go negative" rule, immutability of history, and clean separation between the product model and the movement log.** Everything you build should reinforce those four things — that's where most candidates will be weakest, so it's the highest-leverage place to be excellent.

---

## 2. Mandatory Tech Stack

- **Language/Framework:** Python 3.11+, **FastAPI exclusively** (no Flask/Django — this is a hard constraint from the brief).
- **ORM:** SQLAlchemy 2.0 (async) — gives you real transaction control, which is the whole point of this exercise.
- **DB:** PostgreSQL for local/prod (SQLite is fine for quick local dev/tests, but note in the README that Postgres is the intended production target because SQLite's locking model is too coarse to meaningfully demonstrate row-level concurrency control).
- **Migrations:** Alembic.
- **Validation:** Pydantic v2 schemas, separate from ORM models.
- **Testing:** pytest + pytest-asyncio + httpx.AsyncClient, with a concurrency test that actually exercises the race condition described in the reflection question.
- **Package/env management:** `uv` or `poetry` (either is fine, just be consistent and commit the lockfile).

---

## 3. Data Model

### Product
| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | don't expose sequential ints as public IDs |
| sku | string, unique, indexed | business key |
| name | string | |
| quantity_on_hand | integer, >= 0 | **derived/denormalized** from movements, updated only inside the movement transaction |
| version | integer | for optimistic locking (bonus) |
| is_active | boolean, default true | for soft-delete (bonus) |
| created_at / updated_at | timestamptz | |

### StockMovement
| Field | Type | Notes |
|---|---|---|
| id | UUID (PK) | |
| product_id | FK → Product | indexed |
| movement_type | enum(RESTOCK, SALE, ADJUSTMENT) | |
| quantity_delta | integer | positive for RESTOCK, negative for SALE, either sign for ADJUSTMENT |
| reason | string, nullable | **required** (validated) when type = ADJUSTMENT |
| resulting_quantity | integer | snapshot of quantity_on_hand *after* this movement — makes the log self-verifying and audit-friendly |
| created_at | timestamptz | immutable, no updated_at, no update/delete endpoints or ORM paths exposed anywhere |

**Key modeling decision to call out explicitly in the README:** `StockMovement` has no update or delete path at any layer (no PUT/PATCH/DELETE route, no service method, and ideally enforce at the DB level too — see §6). This is the "immutability of history" requirement made concrete, not just a convention you promise to follow.

---

## 4. Business Rules (must be airtight)

1. `quantity_on_hand` must never go below 0. A SALE that would violate this is rejected with `409 Conflict` (or `422`), no partial state is written.
2. Every quantity change happens **only** as a side effect of inserting a `StockMovement` row, inside the same DB transaction as the `Product.quantity_on_hand` update. There is no code path that updates quantity directly.
3. `ADJUSTMENT` requires a non-empty `reason`.
4. Movement history is returned in chronological order (by `created_at`, tie-broken by an insert-order column/sequence to avoid same-millisecond ordering bugs).
5. (Bonus) Deleting a product with any movement history is blocked (`409`) — deactivate (`is_active = false`) instead.

---

## 5. API Surface

Use versioned routes: `/api/v1/...`.

### Products
- `POST /api/v1/products` — create. Body: `sku`, `name`, optional initial `quantity_on_hand` (default 0). Reject duplicate SKU with `409`.
- `GET /api/v1/products` — list, paginated, filterable by `sku`/`is_active`.
- `GET /api/v1/products/{product_id}` — retrieve.
- `PATCH /api/v1/products/{product_id}` — update name/SKU only (never quantity directly — quantity is not a writable field on this endpoint, enforce via a separate response/request schema, not just "please don't send it" docs).
- `DELETE /api/v1/products/{product_id}` — soft-delete; `409` if movements exist and hard-delete was requested, deactivate instead.

### Stock Movements
- `POST /api/v1/products/{product_id}/movements` — record a movement. Body: `movement_type`, `quantity` (unsigned magnitude, sign is inferred from type for RESTOCK/SALE; ADJUSTMENT takes a signed `quantity_delta` directly), `reason` (required if ADJUSTMENT). Returns the created movement including `resulting_quantity`. This is the one endpoint where transactional correctness lives — see §6.
- `GET /api/v1/products/{product_id}/movements` — paginated history, chronological, filterable by `movement_type` and date range.

### Bonus/stand-out endpoints
- `GET /api/v1/products/low-stock?threshold=10` — list products at/below a threshold (threshold can be a query param with a sensible default, or a per-product field — pick one and justify it in the README).
- `GET /api/v1/health` — liveness/readiness probe (DB connectivity check).
- `GET /api/v1/products/{product_id}/movements/summary` — nice-to-have: aggregate counts/net-quantity by movement type over a date range, demonstrates you can do more than CRUD.

Every endpoint gets Pydantic request/response models, proper status codes, and shows up cleanly in the auto-generated OpenAPI docs (`/docs`).

---

## 6. Transactions & Concurrency — the heart of the exercise

This is what separates a passing submission from a standout one.

**Within a single instance / single DB:**
- Wrap "read product row FOR UPDATE → validate rule → insert movement → update quantity → commit" in one DB transaction.
- Use `SELECT ... FOR UPDATE` (row-level lock) on the product row when recording a movement, so two concurrent SALE requests against the same product serialize instead of both reading the same stale quantity.
- Alternative/complementary approach: optimistic locking via the `version` column — read version, write with `WHERE id = ? AND version = ?`, retry (with backoff, capped attempts) on version mismatch. Implement **both** conceptually if time allows: pessimistic row lock as the primary correctness mechanism, and mention optimistic locking as the documented alternative with its tradeoffs (better for low-contention, avoids holding locks, but needs retry logic and can thrash under high contention).
- Add a genuine **concurrency test**: fire two simultaneous SALE requests against a product with quantity that can only satisfy one of them, assert exactly one succeeds, one gets `409`, and the final `quantity_on_hand` matches the movement log exactly (`sum of deltas == quantity_on_hand`, no drift). This test is arguably the single highest-value thing you can add — it directly proves the thing the evaluators said they're grading.
- Consider a DB-level `CHECK (quantity_on_hand >= 0)` constraint as a last line of defense in addition to application-level checks — defense in depth.

**Immutability enforcement beyond "we just don't expose an endpoint":**
- No ORM update/delete calls anywhere touch `StockMovement`.
- Optionally add a DB trigger or a test that attempts a raw UPDATE/DELETE against the movements table and document that it's disallowed by design (this is a nice differentiator to mention even if you don't build the trigger — "future hardening" section in README).

---

## 7. Bonus Features (implement all four, don't skip any)

1. **Block deletion when movements exist, deactivate instead** — done via `is_active` flag, described above.
2. **Pagination on movement history** — `limit`/`offset` or cursor-based; return total count and next-cursor in the response envelope.
3. **Optimistic locking (version column)** — implement on the Product update paths, with clear 409 + retry guidance in the response.
4. **Low-stock threshold alert endpoint** — as above.

---

## 8. Extras That Make This Stand Out (beyond the stated bonus list)

Pick as many as time allows, roughly in priority order:

1. **Real concurrency test** (see §6) — highest signal-to-effort ratio.
2. **Docker Compose** setup: `app` + `postgres` services, one `docker compose up` to run everything. Massively improves reviewer experience.
3. **Alembic migrations** committed, with a `make migrate` / documented command, instead of `create_all()` at startup.
4. **Seed script** (`scripts/seed.py`) that creates a handful of products and a realistic movement history, so the reviewer can explore `/docs` immediately without manually creating data.
5. **Structured logging** (JSON logs via `structlog` or stdlib `logging` with a JSON formatter) around movement creation — include product_id, movement_type, resulting_quantity. Shows production-mindedness.
6. **Idempotency key support** on `POST .../movements` (optional header `Idempotency-Key`) — replaying the same request doesn't double-apply a movement. This maps directly to a real-world failure mode (client retries after a timeout) and is a strong signal of experience.
7. **OpenAPI examples** on request/response schemas (`Field(..., examples=[...])`) so `/docs` is genuinely usable, not just default-generated.
8. **Basic rate limiting or request size guards** are optional/low priority — don't over-engineer; call this out as "not implemented, would add slowapi or a gateway-level limiter in production" in the README instead of spending time on it.
9. **CI**: a minimal GitHub Actions workflow (`.github/workflows/ci.yml`) that installs deps and runs `pytest` on push. Free credibility signal, costs ~15 minutes.
10. **Postman/HTTPie collection or a `requests.http` file** for manual exploration, alongside `/docs`.

Do **not** over-scope — a working, correct core with 3–4 of these extras beats a half-finished attempt at all ten.

---

## 9. Testing Strategy

- Unit tests: business rule validation (negative quantity rejection, ADJUSTMENT requires reason, SKU uniqueness).
- Integration tests: full request/response cycle via `httpx.AsyncClient` against a test DB (use a throwaway Postgres via Docker in CI, or SQLite for speed with a documented caveat that concurrency tests need Postgres).
- **The concurrency test from §6 is non-negotiable** — it's the test an evaluator would write themselves to check your work, so write it for them.
- Aim for coverage of the movement-creation code path specifically over raw line-coverage percentage.

---

## 10. Suggested Project Structure

```
inventory-service/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── v1/
│   │   │   ├── products.py
│   │   │   └── movements.py
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # business logic (movement creation, locking)
│   ├── db/
│   │   ├── session.py
│   │   └── base.py
│   └── core/             # config, logging
├── alembic/
├── tests/
│   ├── test_products.py
│   ├── test_movements.py
│   └── test_concurrency.py
├── scripts/seed.py
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .github/workflows/ci.yml
└── README.md
```

---

## 11. README Requirements

The README is graded content, not boilerplate. It must include:
- Setup/run instructions (ideally just `docker compose up`).
- API overview (or link to `/docs`).
- Design decisions: why row-level locking, why UUID PKs, why `resulting_quantity` is stored, etc.
- **The two System Design Reflection answers, written thoughtfully** (see §12 — this is graded, don't treat it as an afterthought).
- What's implemented vs. explicitly deferred, and why (shows judgment, not just output).

---

## 12. System Design Reflection — how to think about these (write your own answers, don't copy verbatim)

**Q1 — two terminals, same product, near-simultaneous SALE:**
Talk about the race: both requests read `quantity_on_hand`, both see enough stock, both decrement, final quantity is wrong and can go negative — a classic lost-update / TOCTOU bug. Fix: `SELECT ... FOR UPDATE` to serialize on the product row (or optimistic locking with retry). Mention the tradeoff: pessimistic locking is simpler and correctness-first but reduces throughput under high contention on hot SKUs; optimistic locking scales better under low contention but needs retry logic and can starve under high contention. A mature answer picks one as primary, names the other as the alternative, and says *why* for this specific workload (retail sales are often bursty/hot on a few SKUs during promos — that pushes toward pessimistic locking or sharding hot rows).

**Q2 — 1 warehouse → 50 warehouses:**
Talk about: introducing a `Warehouse` entity and making quantity a property of `(product_id, warehouse_id)` rather than the product itself; movements now carry a `warehouse_id`; consider per-warehouse locking (so warehouse A's contention doesn't block warehouse B); read-heavy "total quantity across warehouses" queries probably want a materialized/denormalized rollup rather than summing on every read; eventual consistency becomes relevant if warehouses are geographically distributed with local DBs that sync centrally; and reconciliation/transfer-between-warehouses becomes a new movement type or a new domain concept entirely (a transfer is really two linked movements — a SALE-like decrement at the source and a RESTOCK-like increment at the destination — which raises its own atomicity question across warehouse boundaries).

---

## 13. Submission Checklist

- [ ] Public GitHub repo created, README.md included.
- [ ] FastAPI only, no other backend framework.
- [ ] All Core Requirements implemented and tested.
- [ ] All four Bonus items implemented.
- [ ] Concurrency test passing and included.
- [ ] `docker compose up` works from a clean clone.
- [ ] CI badge/workflow green.
- [ ] System Design Reflection answers written in README.
- [ ] Repo link shared before **23 July 2026, 07:00 PM IST**.
