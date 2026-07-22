#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Seeding database (skips if already seeded)..."
python scripts/seed.py

echo "Starting server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
