# orbit

A production-grade, async **projects & tasks REST API** built with **FastAPI**,
**SQLAlchemy 2.0 (async)**, and **PostgreSQL**. The point of the codebase is a
clean layered architecture and **role-based access control that provably works**,
backed by a test suite that runs against a real ephemeral Postgres.

## What it is

Users register and log in (JWT). They create projects, invite members with a
role, and manage tasks inside each project. Every project-scoped operation is
gated by an explicit permission matrix - a viewer can read, an editor can CRUD
tasks, and only an owner can edit/delete the project or manage members.

## Architecture

The code is layered so each concern is testable in isolation and the
authorization path is impossible to bypass:

```
HTTP  ---v  Routers (orbit/api/routers/*)      request/response, HTTPException mapping
          |  depend on
          v
          Deps (orbit/api/deps.py)            auth (CurrentUser) + RBAC gate
          |      require_project_permission(Action.X)
          v
          Services (orbit/services/*)         business logic, raise domain errors
          |  use
          v
          Models (orbit/models/*)             SQLAlchemy ORM
          |
          v
          DB (orbit/db/base.py)               async engine + session per request
```

Cross-cutting: `orbit/core/` holds config (`pydantic-settings`), JWT + bcrypt
security, structured logging, and the slowapi rate limiter. Schemas
(`orbit/api/schemas/*`) are Pydantic models that validate every input and shape
every response. Alembic (`migrations/`) owns the schema.

### Layering rules

- **Routers never hand-roll auth.** They declare
  `require_project_permission(Action.X)` as a FastAPI dependency; it resolves the
  caller's membership and enforces the matrix.
- **Services raise plain domain exceptions**; routers translate those into
  `HTTPException`s.
- **Inputs are validated by Pydantic**, not by ad-hoc checks in handlers.

## Auth & RBAC model

- **AuthN** - OAuth2 password flow. `POST /auth/register`, `POST /auth/login`
  (returns an access + refresh token pair), `POST /auth/refresh`, `GET /auth/me`.
  Passwords are bcrypt-hashed; tokens are signed JWTs (HS256).
- **AuthZ** - membership + role per project. Roles: `owner`, `editor`, `viewer`.
  The domain matrix (`orbit/domain/roles.py`, `can(role, action)`):

  | Action | viewer | editor | owner |
  |---|:--:|:--:|:--:|
  | View project / tasks | Y | Y | Y |
  | Create / edit / delete tasks | N | Y | Y |
  | Edit / delete project | N | N | Y |
  | Manage members | N | N | Y |

- **Existence hiding** - a caller who is **not a member** of a project gets
  **404** (never 403), so private projects don't leak their existence. A member
  whose role lacks the action gets **403**. This is enforced centrally by
  `require_project_permission`, the single sanctioned authorization path.

## Running it

### Docker (recommended)

Brings up `postgres:16-alpine` plus the API; the API waits for Postgres to be
healthy, runs `alembic upgrade head`, then serves uvicorn:

```bash
docker compose up --build
# API on http://localhost:8000
```

### Local (uv)

```bash
uv sync --dev
cp .env.example .env                 # then set ORBIT_JWT_SECRET
uv run alembic upgrade head          # against your ORBIT_DATABASE_URL
uv run uvicorn orbit.main:app --reload
```

Configuration is environment-driven (prefix `ORBIT_`): `ORBIT_DATABASE_URL`,
`ORBIT_JWT_SECRET`, `ORBIT_RATE_LIMIT`, `ORBIT_AUTH_RATE_LIMIT` - see
`.env.example`.

## API docs (OpenAPI)

Interactive docs are served by the app:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Raw schema: `http://localhost:8000/openapi.json`
- Health probe: `http://localhost:8000/health` -> `{"status": "ok"}`

The schema is tag-grouped: `auth`, `projects`, `tasks`, `meta`.

## Testing & coverage

Tests run against a **real ephemeral Postgres** via `testcontainers` (no SQLite
substitution) - each test gets an isolated schema, so authorization behavior is
verified against the actual database. Docs/health and the rate limiter are
smoke-tested in `tests/test_health_and_docs.py` and `tests/test_rate_limit.py`
(the latter builds a fresh app with the limiter re-enabled and asserts a `429`
past the `auth_rate_limit`).

```bash
make test        # uv run pytest --cov=orbit --cov-fail-under=85
# or a single slice:
uv run pytest tests/test_projects.py -q --no-cov
```

**Measured coverage: 97% total, 109 tests passing** (`uv run pytest --cov`). Every
feature slice is at 100% - `services/auth_service.py`, `services/project_service.py`,
`services/task_service.py`, and all three routers. The ~21 uncovered lines are
non-critical, fail-closed foundation glue (the production DB session factory, which
tests replace with an override; the unused `roles.require()` helper; a couple of
token/credential edge branches). CI enforces an **85% gate** (`--cov-fail-under=85`).

> Coverage note: SQLAlchemy's async layer runs query bodies inside greenlets, which
> coverage.py doesn't trace by default - so `[tool.coverage.run] concurrency =
> ["thread", "greenlet"]` is set. Without it, heavily-exercised services misleadingly
> read as ~40-50% covered.

CI (`.github/workflows/ci.yml`) runs on every push/PR: `ruff` lint + format
check, `mypy`, `alembic upgrade head` against a Postgres **service container**,
then `pytest --cov` with the 85% gate. The test job still provisions its own
testcontainers Postgres (Docker is available on the runner).

## Make targets

| Target | Does |
|---|---|
| `make up` | Build & start the stack (Postgres + API) |
| `make down` | Stop and remove the stack |
| `make migrate` | `alembic upgrade head` |
| `make test` | Full suite + coverage gate |
| `make lint` / `make format` | ruff check / ruff format |
| `make typecheck` | mypy over `src` |
| `make check` | lint + typecheck + test (what CI runs) |

## What I'd build next

- **Refresh-token rotation + revocation** (a token store / denylist) rather than
  stateless refresh, and short-lived access tokens.
- **Audit log** of membership and role changes for compliance.
- **Task activity & comments**, plus `updated_by` tracking and optimistic
  concurrency (`If-Match`/ETag) on task edits.
- **Cursor pagination** for large task lists instead of limit/offset.
- **Observability**: OpenTelemetry traces + a `/metrics` endpoint, and a
  distributed rate-limit backend (Redis) so limits hold across API replicas.

## About the Maintainer

This project is actively maintained by Rushi Kiran Adiboina, a Full Stack Developer with 6+ years of experience in designing, developing, and supporting scalable enterprise applications. Rushi specializes in building robust backend services and intuitive frontend components, leveraging technologies such as FastAPI, PostgreSQL, React.js, and Java.

For questions or collaborations, you can reach Rushi via:
- Email: rushikiranadiboina@gmail.com
- LinkedIn: https://www.linkedin.com/in/rushi-adiboina/