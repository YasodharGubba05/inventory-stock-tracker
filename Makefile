.PHONY: up down build test migrate seed logs shell

up:
	docker compose up --build

up-d:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

test:
	docker compose --profile test run --rm test

migrate:
	docker compose run --rm app alembic upgrade head

seed:
	docker compose run --rm app python scripts/seed.py

logs:
	docker compose logs -f app

shell:
	docker compose exec app bash
