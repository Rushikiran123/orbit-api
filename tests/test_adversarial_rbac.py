"""Adversarial RBAC probes — gaps not covered by the existing suite."""

from httpx import AsyncClient

from tests.conftest import auth_header, register_and_login


async def _uid(client: AsyncClient, token: str) -> str:
    me = await client.get("/auth/me", headers=auth_header(token))
    return me.json()["id"]


async def _mkproj(client: AsyncClient, token: str, name: str = "P") -> str:
    r = await client.post("/projects", json={"name": name}, headers=auth_header(token))
    return r.json()["id"]


async def _add(client, owner_tok, pid, uid, role):
    return await client.post(
        f"/projects/{pid}/members",
        json={"user_id": uid, "role": role},
        headers=auth_header(owner_tok),
    )


# 1. Cross-project task WRITE paths (existing suite only covers GET cross-project)
async def test_cross_project_patch_task_is_404(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o1@x.com")
    pa = await _mkproj(client, owner, "A")
    pb = await _mkproj(client, owner, "B")
    # task in A
    t = await client.post(f"/projects/{pa}/tasks", json={"title": "x"}, headers=auth_header(owner))
    tid = t.json()["id"]
    # PATCH it under project B (owner of both)
    r = await client.patch(
        f"/projects/{pb}/tasks/{tid}", json={"title": "hax"}, headers=auth_header(owner)
    )
    print("CROSS PATCH:", r.status_code, r.text)
    assert r.status_code == 404, r.text


async def test_cross_project_delete_task_is_404(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o2@x.com")
    pa = await _mkproj(client, owner, "A")
    pb = await _mkproj(client, owner, "B")
    t = await client.post(f"/projects/{pa}/tasks", json={"title": "x"}, headers=auth_header(owner))
    tid = t.json()["id"]
    r = await client.delete(f"/projects/{pb}/tasks/{tid}", headers=auth_header(owner))
    print("CROSS DELETE:", r.status_code, r.text)
    assert r.status_code == 404, r.text


# 2. Assignee from another project on UPDATE must be rejected (422)
async def test_update_assignee_from_other_project_422(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o3@x.com")
    outsider = await register_and_login(client, "out3@x.com")
    out_id = await _uid(client, outsider)
    pa = await _mkproj(client, owner, "A")
    t = await client.post(f"/projects/{pa}/tasks", json={"title": "x"}, headers=auth_header(owner))
    tid = t.json()["id"]
    r = await client.patch(
        f"/projects/{pa}/tasks/{tid}",
        json={"assignee_id": out_id},
        headers=auth_header(owner),
    )
    print("UPDATE ASSIGNEE OTHER PROJ:", r.status_code, r.text)
    assert r.status_code == 422, r.text


# 3. Last-owner guard: demote self (sole owner) via PATCH must be blocked even with viewers present
async def test_demote_sole_owner_with_members_present_blocked(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o4@x.com")
    v = await register_and_login(client, "v4@x.com")
    v_id = await _uid(client, v)
    pid = await _mkproj(client, owner, "P")
    await _add(client, owner, pid, v_id, "viewer")
    owner_id = await _uid(client, owner)
    r = await client.patch(
        f"/projects/{pid}/members/{owner_id}", json={"role": "editor"}, headers=auth_header(owner)
    )
    print("DEMOTE SOLE OWNER:", r.status_code, r.text)
    assert r.status_code == 409, r.text
    # confirm still owner
    m = await client.get(f"/projects/{pid}/members", headers=auth_header(owner))
    roles = {x["user_id"]: x["role"] for x in m.json()}
    assert roles[owner_id] == "owner"


# 4. Editor cannot manage members even when they ARE a project member (403, not 200)
async def test_editor_cannot_add_member(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o5@x.com")
    ed = await register_and_login(client, "ed5@x.com")
    victim = await register_and_login(client, "vic5@x.com")
    ed_id = await _uid(client, ed)
    vic_id = await _uid(client, victim)
    pid = await _mkproj(client, owner, "P")
    await _add(client, owner, pid, ed_id, "editor")
    r = await _add(client, ed, pid, vic_id, "viewer")
    print("EDITOR ADD MEMBER:", r.status_code, r.text)
    assert r.status_code == 403, r.text


# 5. Editor cannot self-promote to owner via PATCH member (403)
async def test_editor_cannot_promote_self(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o6@x.com")
    ed = await register_and_login(client, "ed6@x.com")
    ed_id = await _uid(client, ed)
    pid = await _mkproj(client, owner, "P")
    await _add(client, owner, pid, ed_id, "editor")
    r = await client.patch(
        f"/projects/{pid}/members/{ed_id}", json={"role": "owner"}, headers=auth_header(ed)
    )
    print("EDITOR SELF PROMOTE:", r.status_code, r.text)
    assert r.status_code == 403, r.text


# 6. Non-member managing members returns 404 (existence not leaked), not 403
async def test_nonmember_manage_members_404(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o7@x.com")
    stranger = await register_and_login(client, "s7@x.com")
    victim = await register_and_login(client, "vic7@x.com")
    vic_id = await _uid(client, victim)
    pid = await _mkproj(client, owner, "P")
    r = await _add(client, stranger, pid, vic_id, "viewer")
    print("NONMEMBER ADD:", r.status_code, r.text)
    assert r.status_code == 404, r.text


# 7. Remove sole owner blocked even after adding then removing a second owner
async def test_last_owner_guard_after_churn(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o8@x.com")
    co = await register_and_login(client, "co8@x.com")
    co_id = await _uid(client, co)
    owner_id = await _uid(client, owner)
    pid = await _mkproj(client, owner, "P")
    await _add(client, owner, pid, co_id, "owner")  # 2 owners
    # remove the co-owner -> back to 1 owner
    r1 = await client.delete(f"/projects/{pid}/members/{co_id}", headers=auth_header(owner))
    assert r1.status_code == 204
    # now removing the sole owner must be blocked
    r2 = await client.delete(f"/projects/{pid}/members/{owner_id}", headers=auth_header(owner))
    print("REMOVE SOLE OWNER AFTER CHURN:", r2.status_code, r2.text)
    assert r2.status_code == 409, r2.text


# 8. Viewer cannot edit or delete project (403)
async def test_viewer_cannot_edit_or_delete_project(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o9@x.com")
    v = await register_and_login(client, "v9@x.com")
    v_id = await _uid(client, v)
    pid = await _mkproj(client, owner, "P")
    await _add(client, owner, pid, v_id, "viewer")
    e = await client.patch(f"/projects/{pid}", json={"name": "z"}, headers=auth_header(v))
    d = await client.delete(f"/projects/{pid}", headers=auth_header(v))
    print("VIEWER EDIT/DELETE PROJ:", e.status_code, d.status_code)
    assert e.status_code == 403
    assert d.status_code == 403


# 9. Editor cannot delete project (403)
async def test_editor_cannot_delete_project(client: AsyncClient) -> None:
    owner = await register_and_login(client, "o10@x.com")
    ed = await register_and_login(client, "ed10@x.com")
    ed_id = await _uid(client, ed)
    pid = await _mkproj(client, owner, "P")
    await _add(client, owner, pid, ed_id, "editor")
    d = await client.delete(f"/projects/{pid}", headers=auth_header(ed))
    print("EDITOR DELETE PROJ:", d.status_code)
    assert d.status_code == 403
