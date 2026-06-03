# orbit — feature contract (source of truth for the swarm)

The **foundation is built and tested**: config, JWT+bcrypt security, async DB,
all four ORM models, the RBAC permission matrix, auth endpoints, the app factory,
Alembic migration, and testcontainers-Postgres fixtures (9 auth tests pass). Your
job: the **projects** and **tasks** feature slices + **infra hardening**, on top.

The recruiter-facing point: clean layered architecture + **RBAC that provably
works** + high test coverage. Correctness of authorization is paramount.

## Foundation you build on (do NOT modify these)

- **Models** (`orbit.models`): `User(id, email, full_name, hashed_password)`,
  `Project(id, name, description, created_by, created_at)`,
  `ProjectMember(id, project_id, user_id, role)` (unique per project+user),
  `Task(id, project_id, title, description, status, assignee_id, created_by,
  created_at, updated_at)`. `TaskStatus` = todo|in_progress|done.
- **Roles** (`orbit.domain.roles`): `Role` = owner|editor|viewer; `Action` enum;
  `can(role, action)`. Matrix: viewer→view only; editor→view + create/edit/delete
  tasks; owner→everything incl. edit/delete project + `MANAGE_MEMBERS`.
- **Auth deps** (`orbit.api.deps`): `CurrentUser` (Annotated dep → `User`),
  `SessionDep` (Annotated → `AsyncSession`), and **`require_project_permission(action)`**
  → a dependency factory. Use it on every project-scoped route: it reads the
  path `project_id`, resolves the caller's membership, raises **404 if not a
  member** (don't leak existence), **403 if the role lacks the action**, and
  returns the caller's `Role` on success.
- **App factory** (`orbit.main.create_app`): auto-attaches `orbit.api.routers.projects`
  and `.tasks` if present (each must expose a top-level `router: APIRouter`).
- **Security/services patterns**: services raise plain domain exceptions; routers
  map them to `HTTPException`. Schemas live in `orbit/api/schemas/`. Follow the
  `auth` slice as the reference for layering.
- **Tests**: use fixtures from `tests/conftest.py` — `client` (async httpx bound
  to the app on a per-test Postgres), `session`, `register_and_login(client, email)
  → token`, `auth_header(token)`. Run: `uv run pytest tests/<file> -q --no-cov`.

## Agent P — projects + membership slice

Files: `src/orbit/services/project_service.py`, `src/orbit/api/routers/projects.py`,
`src/orbit/api/schemas/project.py`, `tests/test_projects.py`.

Endpoints (all require auth; `router = APIRouter(prefix="/projects", tags=["projects"])`):
- `POST /projects` — create a project; the creator becomes an **owner** member
  automatically (insert Project + a ProjectMember row, one transaction). 201.
- `GET /projects` — list projects the caller is a member of (with the caller's role).
- `GET /projects/{project_id}` — needs `VIEW_PROJECT`. Returns project + caller role.
- `PATCH /projects/{project_id}` — needs `EDIT_PROJECT` (name/description). 
- `DELETE /projects/{project_id}` — needs `DELETE_PROJECT` (owner only). 204.
- `GET /projects/{project_id}/members` — needs `VIEW_PROJECT`. List members+roles.
- `POST /projects/{project_id}/members` — needs `MANAGE_MEMBERS`. Body: `{user_id|email, role}`.
  Add a member; 409 if already a member; 404 if the user doesn't exist. Cannot add a
  second owner via a role you can't grant? Keep it simple: any role assignable by an owner.
- `PATCH /projects/{project_id}/members/{user_id}` — needs `MANAGE_MEMBERS`. Change role.
  **Must not allow demoting/removing the last owner** (a project always has ≥1 owner).
- `DELETE /projects/{project_id}/members/{user_id}` — needs `MANAGE_MEMBERS`. Remove a
  member; same last-owner guard.
Use `require_project_permission(Action.X)` as a dependency for the scoped routes.
Tests must cover: owner-created membership, each role's allowed/denied matrix on
every endpoint (viewer cannot edit/delete, editor cannot delete project or manage
members, non-member gets 404), the last-owner guard, and 409/404 edges.

## Agent T — tasks slice

Files: `src/orbit/services/task_service.py`, `src/orbit/api/routers/tasks.py`,
`src/orbit/api/schemas/task.py`, `tests/test_tasks.py`.

Endpoints nested under a project (`router = APIRouter(prefix="/projects/{project_id}/tasks",
tags=["tasks"])`), all project-scoped via `require_project_permission`:
- `POST` — needs `CREATE_TASK`. Create a task in the project (creator = caller). 201.
- `GET` — needs `VIEW_TASK`. List tasks with **filtering** (`?status=`, `?assignee_id=`)
  and **pagination** (`?limit=&offset=`, sane defaults + max). Return items + total count.
- `GET /{task_id}` — needs `VIEW_TASK`. 404 if the task isn't in this project.
- `PATCH /{task_id}` — needs `EDIT_TASK`. Update title/description/status/assignee.
  An assignee must be a member of the project (else 422). 
- `DELETE /{task_id}` — needs `DELETE_TASK`. 204.
Tests: create/list/filter/paginate, the permission matrix (viewer can read not
write, editor can CRUD tasks, non-member 404), task-not-in-project 404, and the
assignee-must-be-member rule.

## Agent I — infra & hardening

Files: `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`,
`tests/test_health_and_docs.py`, `tests/test_rate_limit.py`, `README.md`, `Makefile`.
- **Dockerfile**: python:3.12-slim + uv, run uvicorn `orbit.main:app`. 
- **docker-compose.yml**: `postgres:16-alpine` + the `api` (waits for pg healthy,
  runs `alembic upgrade head` then uvicorn). 
- **CI** (GitHub Actions): a Postgres **service container**; steps: uv sync, ruff,
  mypy, `alembic upgrade head` against the service PG, then `pytest --cov` (tests
  use their own testcontainers PG — ensure Docker is available on the runner, it is).
  Coverage gate: fail under 85%.
- **Tests**: `/health` returns ok; `/openapi.json` and `/docs` are served and the
  schema lists the auth/projects/tasks tags; rate-limit test (re-enable the limiter
  on a test app, hit an auth endpoint past the limit → 429).
- **README**: what it is, the architecture (layers + RBAC), the auth+RBAC model, run
  instructions (docker compose up), the OpenAPI docs, testing + the **real coverage
  number** (run `pytest --cov` and quote it), and a short "what I'd build next".
- **Makefile**: `up`, `test`, `lint`, `migrate` targets.

## Boundaries
- Agent P: only its 4 files. Agent T: only its 4 files. Agent I: only its listed files.
- Nobody edits the foundation (core, db, domain, models, deps, auth, main, alembic,
  conftest) or another agent's files. Import foundation pieces per their signatures.
- `require_project_permission` is the ONLY sanctioned authorization path — do not
  hand-roll membership/role checks in routers.
