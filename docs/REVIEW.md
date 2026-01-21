# Review process & findings

I built the security-critical **foundation** directly (config, JWT+bcrypt security,
async DB, the four ORM models, the RBAC permission matrix, the
`require_project_permission` gate, the full auth flow, the Alembic migration, and
testcontainers-Postgres fixtures — 9 tests green) because everything downstream
depends on it being exactly right. A swarm then built the **projects** and
**tasks** feature slices + **infra** in parallel against `docs/CONTRACT.md`,
followed by three adversarial reviewers: authorization correctness, auth/input
security, and test-coverage/quality.

## Integration fixes (found while composing the slices)

- **FastAPI 0.139 broke route composition.** The lockfile had drifted to a
  FastAPI version whose rewritten `include_router` attaches opaque lazy wrappers
  instead of flattening routes onto `app.routes`. Pinned `fastapi>=0.115,<0.130`
  (resolves to 0.129.2, the newest that still flattens).
- **Coverage was under-reported (77% → real 97%).** SQLAlchemy's async layer runs
  query bodies inside greenlets that `coverage.py` doesn't trace by default, so
  heavily-exercised services read as ~40–50% covered. Added
  `[tool.coverage.run] concurrency = ["thread", "greenlet"]`. After the fix every
  service and router reads 100%.

## Security reviews: NO FINDINGS (with reproduction)

Both the **authorization** and **auth/input-security** reviewers ran adversarial
probes against a real Postgres and confirmed — reproducing each — that:

- Every project-scoped route authorizes solely through `require_project_permission`
  (no hand-rolled checks; the gate runs before any handler body).
- **VIEWER** → 403 on all writes; **EDITOR** → task CRUD but 403 on project delete
  and member management; **NON-MEMBER** → 404 on every scoped route (existence is
  never leaked).
- **Cross-project access** blocked (a task id from project A → 404 under project B).
- **Last-owner guard** holds on both demote and remove (409).
- **Token-type confusion** blocked (access token can't refresh, refresh can't
  authenticate); expired/malformed/missing → 401.
- **No email enumeration** (unknown email and wrong password return identical 401;
  a dummy bcrypt verify runs for missing users to avoid a timing oracle).
- **No IDOR, no mass-assignment** (`TaskUpdate`/`ProjectUpdate` use
  `extra="forbid"`; `created_by`/`id`/`project_id` can't be set via PATCH → 422).
- **No password leakage** in any response schema; **no string SQL** (ORM only).

## Quality review: one finding (fixed)

The README quoted **77% coverage** (the infra agent's snapshot before the two
integration fixes) when the real figure is **97%** with all slices at 100% — and
77% would contradict the 85% CI gate the same README describes. Corrected to 97%
with the greenlet-coverage note.

## Verified by hand before shipping

`pytest --cov` → **109 passed, 97%**; ruff + mypy clean; and a full RBAC flow
driven against a **live server on real Postgres** (owner creates task 201, viewer
403, viewer reads 200, non-member 404, last-owner-removal 409, no-auth 401);
`/openapi.json` + `/docs` render with the correct tags.
