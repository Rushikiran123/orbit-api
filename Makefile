.PHONY: help up down build logs migrate test lint format typecheck check ci

# Default target: list available commands.
help:
	@echo "orbit — make targets:"
	@echo "  up        Build & start the stack (Postgres + API) via docker compose"
	@echo "  down      Stop the stack and remove containers"
	@echo "  logs      Tail the API logs"
	@echo "  migrate   Apply Alembic migrations to head (uses ORBIT_DATABASE_URL)"
	@echo "  test      Run the test suite with coverage (85% gate)"
	@echo "  lint      Run ruff lint checks"
	@echo "  format    Auto-format with ruff"
	@echo "  typecheck Run mypy over src"
	@echo "  check     lint + typecheck + test (what CI runs)"

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f api

migrate:
	uv run alembic upgrade head

test:
	uv run pytest --cov=orbit --cov-report=term-missing --cov-fail-under=85

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

check: lint typecheck test

ci: check
