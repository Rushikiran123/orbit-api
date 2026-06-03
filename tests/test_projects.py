"""Projects + membership slice: full RBAC matrix, last-owner guard, and edges.

Every project-scoped endpoint is exercised for each role (owner / editor /
viewer) plus a non-member, asserting the exact allowed/denied outcome and that
non-members get 404 (existence not leaked) rather than 403.
"""

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header, register_and_login


async def _make_user(client: AsyncClient, email: str) -> tuple[str, str]:
    """Register + login a user; return (access_token, user_id)."""
    token = await register_and_login(client, email)
    me = await client.get("/auth/me", headers=auth_header(token))
    return token, me.json()["id"]


async def _create_project(client: AsyncClient, token: str, name: str = "Orbit") -> str:
    resp = await client.post(
        "/projects", json={"name": name, "description": "d"}, headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_member(
    client: AsyncClient, owner_token: str, project_id: str, user_id: str, role: str
) -> None:
    resp = await client.post(
        f"/projects/{project_id}/members",
        json={"user_id": user_id, "role": role},
        headers=auth_header(owner_token),
    )
    assert resp.status_code == 201, resp.text


@pytest.fixture
async def world(client: AsyncClient) -> dict[str, str]:
    """A project with an owner, editor, viewer, and an unrelated non-member."""
    owner_token, owner_id = await _make_user(client, "owner@x.com")
    editor_token, editor_id = await _make_user(client, "editor@x.com")
    viewer_token, viewer_id = await _make_user(client, "viewer@x.com")
    stranger_token, stranger_id = await _make_user(client, "stranger@x.com")

    project_id = await _create_project(client, owner_token)
    await _add_member(client, owner_token, project_id, editor_id, "editor")
    await _add_member(client, owner_token, project_id, viewer_id, "viewer")

    return {
        "project_id": project_id,
        "owner_token": owner_token,
        "owner_id": owner_id,
        "editor_token": editor_token,
        "editor_id": editor_id,
        "viewer_token": viewer_token,
        "viewer_id": viewer_id,
        "stranger_token": stranger_token,
        "stranger_id": stranger_id,
    }


# --------------------------------------------------------------------------- #
# creation + auto-owner membership + listing
# --------------------------------------------------------------------------- #


async def test_create_project_returns_owner_role(client: AsyncClient) -> None:
    token, _ = await _make_user(client, "a@x.com")
    resp = await client.post(
        "/projects", json={"name": "P", "description": "hi"}, headers=auth_header(token)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "owner"
    assert body["name"] == "P"
    assert body["description"] == "hi"


async def test_create_auto_enrolls_creator_as_owner(client: AsyncClient) -> None:
    token, uid = await _make_user(client, "a@x.com")
    pid = await _create_project(client, token)
    resp = await client.get(f"/projects/{pid}/members", headers=auth_header(token))
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["user_id"] == uid
    assert members[0]["role"] == "owner"


async def test_create_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/projects", json={"name": "P"})
    assert resp.status_code == 401


async def test_create_rejects_empty_name(client: AsyncClient) -> None:
    token, _ = await _make_user(client, "a@x.com")
    resp = await client.post("/projects", json={"name": ""}, headers=auth_header(token))
    assert resp.status_code == 422


async def test_list_projects_shows_only_memberships_with_role(client: AsyncClient) -> None:
    owner_token, _ = await _make_user(client, "o@x.com")
    other_token, other_id = await _make_user(client, "u@x.com")
    pid = await _create_project(client, owner_token, "Shared")
    # owner has an extra solo project the other user must not see
    await _create_project(client, owner_token, "Solo")
    await _add_member(client, owner_token, pid, other_id, "viewer")

    resp = await client.get("/projects", headers=auth_header(other_token))
    assert resp.status_code == 200
    projects = resp.json()
    assert len(projects) == 1
    assert projects[0]["id"] == pid
    assert projects[0]["role"] == "viewer"


# --------------------------------------------------------------------------- #
# GET /projects/{id} — VIEW_PROJECT (all members allowed, non-member 404)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("owner", 200), ("editor", 200), ("viewer", 200), ("stranger", 404)],
)
async def test_get_project_matrix(
    client: AsyncClient, world: dict[str, str], actor: str, expected: int
) -> None:
    resp = await client.get(
        f"/projects/{world['project_id']}", headers=auth_header(world[f"{actor}_token"])
    )
    assert resp.status_code == expected
    if expected == 200:
        assert resp.json()["role"] == actor


async def test_get_project_unknown_id_is_404(client: AsyncClient) -> None:
    token, _ = await _make_user(client, "a@x.com")
    resp = await client.get("/projects/does-not-exist", headers=auth_header(token))
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# PATCH /projects/{id} — EDIT_PROJECT (owner only)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("owner", 200), ("editor", 403), ("viewer", 403), ("stranger", 404)],
)
async def test_update_project_matrix(
    client: AsyncClient, world: dict[str, str], actor: str, expected: int
) -> None:
    resp = await client.patch(
        f"/projects/{world['project_id']}",
        json={"name": "Renamed"},
        headers=auth_header(world[f"{actor}_token"]),
    )
    assert resp.status_code == expected
    if expected == 200:
        assert resp.json()["name"] == "Renamed"


async def test_update_project_partial_description_only(
    client: AsyncClient, world: dict[str, str]
) -> None:
    resp = await client.patch(
        f"/projects/{world['project_id']}",
        json={"description": "new desc"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "new desc"
    assert resp.json()["name"] == "Orbit"


async def test_update_project_empty_body_is_422(client: AsyncClient, world: dict[str, str]) -> None:
    resp = await client.patch(
        f"/projects/{world['project_id']}",
        json={},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# DELETE /projects/{id} — DELETE_PROJECT (owner only)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("editor", 403), ("viewer", 403), ("stranger", 404)],
)
async def test_delete_project_denied_matrix(
    client: AsyncClient, world: dict[str, str], actor: str, expected: int
) -> None:
    resp = await client.delete(
        f"/projects/{world['project_id']}", headers=auth_header(world[f"{actor}_token"])
    )
    assert resp.status_code == expected


async def test_delete_project_owner_allowed(client: AsyncClient, world: dict[str, str]) -> None:
    pid = world["project_id"]
    resp = await client.delete(f"/projects/{pid}", headers=auth_header(world["owner_token"]))
    assert resp.status_code == 204
    # gone: even the former owner now gets 404
    follow = await client.get(f"/projects/{pid}", headers=auth_header(world["owner_token"]))
    assert follow.status_code == 404


# --------------------------------------------------------------------------- #
# GET /projects/{id}/members — VIEW_PROJECT
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("owner", 200), ("editor", 200), ("viewer", 200), ("stranger", 404)],
)
async def test_list_members_matrix(
    client: AsyncClient, world: dict[str, str], actor: str, expected: int
) -> None:
    resp = await client.get(
        f"/projects/{world['project_id']}/members",
        headers=auth_header(world[f"{actor}_token"]),
    )
    assert resp.status_code == expected
    if expected == 200:
        assert len(resp.json()) == 3


# --------------------------------------------------------------------------- #
# POST /projects/{id}/members — MANAGE_MEMBERS (owner only)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("editor", 403), ("viewer", 403), ("stranger", 404)],
)
async def test_add_member_denied_matrix(
    client: AsyncClient, world: dict[str, str], actor: str, expected: int
) -> None:
    _, newbie_id = await _make_user(client, f"new-{actor}@x.com")
    resp = await client.post(
        f"/projects/{world['project_id']}/members",
        json={"user_id": newbie_id, "role": "viewer"},
        headers=auth_header(world[f"{actor}_token"]),
    )
    assert resp.status_code == expected


async def test_add_member_by_email(client: AsyncClient, world: dict[str, str]) -> None:
    await _make_user(client, "byemail@x.com")
    resp = await client.post(
        f"/projects/{world['project_id']}/members",
        json={"email": "byemail@x.com", "role": "editor"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "byemail@x.com"
    assert resp.json()["role"] == "editor"


async def test_add_member_second_owner_allowed(client: AsyncClient, world: dict[str, str]) -> None:
    _, uid = await _make_user(client, "coowner@x.com")
    resp = await client.post(
        f"/projects/{world['project_id']}/members",
        json={"user_id": uid, "role": "owner"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "owner"


async def test_add_member_already_member_is_409(client: AsyncClient, world: dict[str, str]) -> None:
    resp = await client.post(
        f"/projects/{world['project_id']}/members",
        json={"user_id": world["editor_id"], "role": "viewer"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 409


async def test_add_member_unknown_user_is_404(client: AsyncClient, world: dict[str, str]) -> None:
    resp = await client.post(
        f"/projects/{world['project_id']}/members",
        json={"user_id": "ghost", "role": "viewer"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 404


async def test_add_member_requires_one_identifier(
    client: AsyncClient, world: dict[str, str]
) -> None:
    both = await client.post(
        f"/projects/{world['project_id']}/members",
        json={"user_id": "x", "email": "y@x.com", "role": "viewer"},
        headers=auth_header(world["owner_token"]),
    )
    neither = await client.post(
        f"/projects/{world['project_id']}/members",
        json={"role": "viewer"},
        headers=auth_header(world["owner_token"]),
    )
    assert both.status_code == 422
    assert neither.status_code == 422


# --------------------------------------------------------------------------- #
# PATCH /projects/{id}/members/{user_id} — MANAGE_MEMBERS + last-owner guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("editor", 403), ("viewer", 403), ("stranger", 404)],
)
async def test_update_member_denied_matrix(
    client: AsyncClient, world: dict[str, str], actor: str, expected: int
) -> None:
    resp = await client.patch(
        f"/projects/{world['project_id']}/members/{world['viewer_id']}",
        json={"role": "editor"},
        headers=auth_header(world[f"{actor}_token"]),
    )
    assert resp.status_code == expected


async def test_update_member_owner_can_promote(client: AsyncClient, world: dict[str, str]) -> None:
    resp = await client.patch(
        f"/projects/{world['project_id']}/members/{world['viewer_id']}",
        json={"role": "editor"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


async def test_update_member_not_a_member_is_404(
    client: AsyncClient, world: dict[str, str]
) -> None:
    resp = await client.patch(
        f"/projects/{world['project_id']}/members/{world['stranger_id']}",
        json={"role": "editor"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 404


async def test_demote_last_owner_is_blocked(client: AsyncClient, world: dict[str, str]) -> None:
    resp = await client.patch(
        f"/projects/{world['project_id']}/members/{world['owner_id']}",
        json={"role": "editor"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 409


async def test_demote_owner_allowed_when_another_owner_exists(
    client: AsyncClient, world: dict[str, str]
) -> None:
    pid = world["project_id"]
    _, co_id = await _make_user(client, "co@x.com")
    await _add_member(client, world["owner_token"], pid, co_id, "owner")
    # now demoting the original owner is fine
    resp = await client.patch(
        f"/projects/{pid}/members/{world['owner_id']}",
        json={"role": "viewer"},
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"


# --------------------------------------------------------------------------- #
# DELETE /projects/{id}/members/{user_id} — MANAGE_MEMBERS + last-owner guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("actor", "expected"),
    [("editor", 403), ("viewer", 403), ("stranger", 404)],
)
async def test_remove_member_denied_matrix(
    client: AsyncClient, world: dict[str, str], actor: str, expected: int
) -> None:
    resp = await client.delete(
        f"/projects/{world['project_id']}/members/{world['viewer_id']}",
        headers=auth_header(world[f"{actor}_token"]),
    )
    assert resp.status_code == expected


async def test_remove_member_owner_allowed(client: AsyncClient, world: dict[str, str]) -> None:
    resp = await client.delete(
        f"/projects/{world['project_id']}/members/{world['viewer_id']}",
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 204
    members = await client.get(
        f"/projects/{world['project_id']}/members",
        headers=auth_header(world["owner_token"]),
    )
    assert len(members.json()) == 2


async def test_remove_member_not_a_member_is_404(
    client: AsyncClient, world: dict[str, str]
) -> None:
    resp = await client.delete(
        f"/projects/{world['project_id']}/members/{world['stranger_id']}",
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 404


async def test_remove_last_owner_is_blocked(client: AsyncClient, world: dict[str, str]) -> None:
    resp = await client.delete(
        f"/projects/{world['project_id']}/members/{world['owner_id']}",
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 409


async def test_remove_owner_allowed_when_another_owner_exists(
    client: AsyncClient, world: dict[str, str]
) -> None:
    pid = world["project_id"]
    _, co_id = await _make_user(client, "co@x.com")
    await _add_member(client, world["owner_token"], pid, co_id, "owner")
    resp = await client.delete(
        f"/projects/{pid}/members/{world['owner_id']}",
        headers=auth_header(world["owner_token"]),
    )
    assert resp.status_code == 204


async def test_member_scoped_routes_require_auth(
    client: AsyncClient, world: dict[str, str]
) -> None:
    resp = await client.get(f"/projects/{world['project_id']}/members")
    assert resp.status_code == 401
