"""Tasks slice: CRUD, filtering/pagination, and the full RBAC permission matrix.

Members are seeded directly via the ORM (the projects/members API belongs to a
sibling agent), so these tests exercise the tasks router against real Postgres
without depending on that slice's endpoints.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.domain.roles import Role
from orbit.models import Project, ProjectMember, User
from tests.conftest import auth_header, register_and_login


async def _user_id(session: AsyncSession, email: str) -> str:
    from sqlalchemy import select

    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one().id


async def _make_project(session: AsyncSession, owner_id: str, name: str = "Proj") -> str:
    project = Project(name=name, description="", created_by=owner_id)
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=owner_id, role=Role.OWNER))
    await session.commit()
    return project.id


async def _add_member(session: AsyncSession, project_id: str, user_id: str, role: Role) -> None:
    session.add(ProjectMember(project_id=project_id, user_id=user_id, role=role))
    await session.commit()


@pytest_asyncio.fixture
async def env(client: AsyncClient, session: AsyncSession) -> dict[str, object]:
    """A project with one owner, editor, viewer, and a non-member — each with a token."""
    owner_tok = await register_and_login(client, "owner@x.com")
    editor_tok = await register_and_login(client, "editor@x.com")
    viewer_tok = await register_and_login(client, "viewer@x.com")
    outsider_tok = await register_and_login(client, "outsider@x.com")

    owner_id = await _user_id(session, "owner@x.com")
    editor_id = await _user_id(session, "editor@x.com")
    viewer_id = await _user_id(session, "viewer@x.com")
    outsider_id = await _user_id(session, "outsider@x.com")

    project_id = await _make_project(session, owner_id)
    await _add_member(session, project_id, editor_id, Role.EDITOR)
    await _add_member(session, project_id, viewer_id, Role.VIEWER)

    return {
        "project_id": project_id,
        "owner": (owner_tok, owner_id),
        "editor": (editor_tok, editor_id),
        "viewer": (viewer_tok, viewer_id),
        "outsider": (outsider_tok, outsider_id),
    }


def _tok(env: dict[str, object], who: str) -> str:
    return env[who][0]  # type: ignore[index]


def _uid(env: dict[str, object], who: str) -> str:
    return env[who][1]  # type: ignore[index]


def _url(env: dict[str, object], suffix: str = "") -> str:
    return f"/projects/{env['project_id']}/tasks{suffix}"


async def _create(client: AsyncClient, env: dict[str, object], who: str, **body: object) -> dict:
    payload: dict[str, object] = {"title": "T"}
    payload.update(body)
    resp = await client.post(_url(env), json=payload, headers=auth_header(_tok(env, who)))
    return resp.json()


# --------------------------------------------------------------------------- create


async def test_editor_creates_task(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.post(
        _url(env),
        json={"title": "Ship it", "description": "now"},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Ship it"
    assert body["status"] == "todo"
    assert body["created_by"] == _uid(env, "editor")
    assert body["project_id"] == env["project_id"]


async def test_owner_creates_task(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.post(
        _url(env), json={"title": "Owner task"}, headers=auth_header(_tok(env, "owner"))
    )
    assert resp.status_code == 201


async def test_viewer_cannot_create(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.post(
        _url(env), json={"title": "nope"}, headers=auth_header(_tok(env, "viewer"))
    )
    assert resp.status_code == 403


async def test_non_member_create_gets_404(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.post(
        _url(env), json={"title": "nope"}, headers=auth_header(_tok(env, "outsider"))
    )
    assert resp.status_code == 404


async def test_create_requires_auth(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.post(_url(env), json={"title": "x"})
    assert resp.status_code == 401


async def test_create_with_valid_assignee(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.post(
        _url(env),
        json={"title": "assigned", "assignee_id": _uid(env, "viewer")},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 201
    assert resp.json()["assignee_id"] == _uid(env, "viewer")


async def test_create_with_non_member_assignee_422(
    client: AsyncClient, env: dict[str, object]
) -> None:
    resp = await client.post(
        _url(env),
        json={"title": "bad", "assignee_id": _uid(env, "outsider")},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 422


async def test_create_invalid_title_422(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.post(
        _url(env), json={"title": ""}, headers=auth_header(_tok(env, "editor"))
    )
    assert resp.status_code == 422


# ----------------------------------------------------------------------------- read


async def test_viewer_can_list(client: AsyncClient, env: dict[str, object]) -> None:
    await _create(client, env, "editor", title="one")
    resp = await client.get(_url(env), headers=auth_header(_tok(env, "viewer")))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["limit"] == 50
    assert body["offset"] == 0


async def test_non_member_list_404(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.get(_url(env), headers=auth_header(_tok(env, "outsider")))
    assert resp.status_code == 404


async def test_get_single_task(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="findme")
    resp = await client.get(
        _url(env, f"/{created['id']}"), headers=auth_header(_tok(env, "viewer"))
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


async def test_get_missing_task_404(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.get(_url(env, f"/{uuid.uuid4()}"), headers=auth_header(_tok(env, "viewer")))
    assert resp.status_code == 404


async def test_task_from_other_project_is_404(
    client: AsyncClient, session: AsyncSession, env: dict[str, object]
) -> None:
    # A task that exists but belongs to a different project must 404 here, not leak.
    other_project = await _make_project(session, _uid(env, "owner"), name="Other")
    task_resp = await client.post(
        f"/projects/{other_project}/tasks",
        json={"title": "elsewhere"},
        headers=auth_header(_tok(env, "owner")),
    )
    other_task_id = task_resp.json()["id"]
    resp = await client.get(
        _url(env, f"/{other_task_id}"), headers=auth_header(_tok(env, "viewer"))
    )
    assert resp.status_code == 404


# ------------------------------------------------------------------ filter/paginate


async def test_filter_by_status(client: AsyncClient, env: dict[str, object]) -> None:
    await _create(client, env, "editor", title="a", status="todo")
    await _create(client, env, "editor", title="b", status="done")
    await _create(client, env, "editor", title="c", status="done")
    resp = await client.get(
        _url(env), params={"status": "done"}, headers=auth_header(_tok(env, "viewer"))
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {t["status"] for t in body["items"]} == {"done"}


async def test_filter_by_assignee(client: AsyncClient, env: dict[str, object]) -> None:
    await _create(client, env, "editor", title="mine", assignee_id=_uid(env, "editor"))
    await _create(client, env, "editor", title="unassigned")
    resp = await client.get(
        _url(env),
        params={"assignee_id": _uid(env, "editor")},
        headers=auth_header(_tok(env, "viewer")),
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "mine"


async def test_pagination(client: AsyncClient, env: dict[str, object]) -> None:
    for i in range(5):
        await _create(client, env, "editor", title=f"t{i}")
    resp = await client.get(
        _url(env),
        params={"limit": 2, "offset": 0},
        headers=auth_header(_tok(env, "viewer")),
    )
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2

    resp2 = await client.get(
        _url(env),
        params={"limit": 2, "offset": 4},
        headers=auth_header(_tok(env, "viewer")),
    )
    assert len(resp2.json()["items"]) == 1


async def test_pagination_limit_validation(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.get(
        _url(env), params={"limit": 0}, headers=auth_header(_tok(env, "viewer"))
    )
    assert resp.status_code == 422
    resp2 = await client.get(
        _url(env), params={"limit": 101}, headers=auth_header(_tok(env, "viewer"))
    )
    assert resp2.status_code == 422


# --------------------------------------------------------------------------- update


async def test_editor_updates_task(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="old")
    resp = await client.patch(
        _url(env, f"/{created['id']}"),
        json={"title": "new", "status": "in_progress"},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "new"
    assert body["status"] == "in_progress"


async def test_viewer_cannot_update(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.patch(
        _url(env, f"/{created['id']}"),
        json={"title": "hax"},
        headers=auth_header(_tok(env, "viewer")),
    )
    assert resp.status_code == 403


async def test_non_member_update_404(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.patch(
        _url(env, f"/{created['id']}"),
        json={"title": "hax"},
        headers=auth_header(_tok(env, "outsider")),
    )
    assert resp.status_code == 404


async def test_update_missing_task_404(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.patch(
        _url(env, f"/{uuid.uuid4()}"),
        json={"title": "x"},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 404


async def test_update_assignee_to_member(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.patch(
        _url(env, f"/{created['id']}"),
        json={"assignee_id": _uid(env, "viewer")},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 200
    assert resp.json()["assignee_id"] == _uid(env, "viewer")


async def test_update_assignee_non_member_422(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.patch(
        _url(env, f"/{created['id']}"),
        json={"assignee_id": _uid(env, "outsider")},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 422


async def test_update_unassign(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x", assignee_id=_uid(env, "editor"))
    resp = await client.patch(
        _url(env, f"/{created['id']}"),
        json={"assignee_id": None},
        headers=auth_header(_tok(env, "editor")),
    )
    assert resp.status_code == 200
    assert resp.json()["assignee_id"] is None


# --------------------------------------------------------------------------- delete


async def test_editor_deletes_task(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.delete(
        _url(env, f"/{created['id']}"), headers=auth_header(_tok(env, "editor"))
    )
    assert resp.status_code == 204
    check = await client.get(
        _url(env, f"/{created['id']}"), headers=auth_header(_tok(env, "editor"))
    )
    assert check.status_code == 404


async def test_viewer_cannot_delete(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.delete(
        _url(env, f"/{created['id']}"), headers=auth_header(_tok(env, "viewer"))
    )
    assert resp.status_code == 403


async def test_owner_can_delete(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.delete(
        _url(env, f"/{created['id']}"), headers=auth_header(_tok(env, "owner"))
    )
    assert resp.status_code == 204


async def test_non_member_delete_404(client: AsyncClient, env: dict[str, object]) -> None:
    created = await _create(client, env, "editor", title="x")
    resp = await client.delete(
        _url(env, f"/{created['id']}"), headers=auth_header(_tok(env, "outsider"))
    )
    assert resp.status_code == 404


async def test_delete_missing_task_404(client: AsyncClient, env: dict[str, object]) -> None:
    resp = await client.delete(
        _url(env, f"/{uuid.uuid4()}"), headers=auth_header(_tok(env, "editor"))
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("who", "expected"),
    [("owner", 201), ("editor", 201), ("viewer", 403), ("outsider", 404)],
)
async def test_create_permission_matrix(
    client: AsyncClient, env: dict[str, object], who: str, expected: int
) -> None:
    resp = await client.post(
        _url(env), json={"title": "matrix"}, headers=auth_header(_tok(env, who))
    )
    assert resp.status_code == expected


@pytest.mark.parametrize(
    ("who", "expected"),
    [("owner", 200), ("editor", 200), ("viewer", 200), ("outsider", 404)],
)
async def test_list_permission_matrix(
    client: AsyncClient, env: dict[str, object], who: str, expected: int
) -> None:
    resp = await client.get(_url(env), headers=auth_header(_tok(env, who)))
    assert resp.status_code == expected
