# syntax=docker/dockerfile:1
# --- builder: install deps into a project virtualenv with uv ---
FROM python:3.12-slim AS builder

# uv: fast, reproducible installs from uv.lock
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached layer) using only the lockfiles.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now copy the source and install the project itself.
# README.md is copied too because pyproject's `readme = "README.md"` makes the
# uv_build backend require it when building the project wheel.
COPY README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime: slim image with just the venv + app ---
FROM python:3.12-slim AS runtime

# Non-root runtime user.
RUN useradd --create-home --uid 10001 orbit

WORKDIR /app

COPY --from=builder --chown=orbit:orbit /app /app

# Put the project venv on PATH so `uvicorn`/`alembic` resolve directly.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER orbit
EXPOSE 8000

# Default: serve the ASGI app. docker-compose overrides this to first run
# `alembic upgrade head` (see the api service command).
CMD ["uvicorn", "orbit.main:app", "--host", "0.0.0.0", "--port", "8000"]
