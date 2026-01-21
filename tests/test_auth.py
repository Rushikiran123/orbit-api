"""Auth flow + security foundation tests (against real Postgres)."""

import pytest

from orbit.core.security import (
    TokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from orbit.domain.roles import Action, Role, can
from tests.conftest import auth_header, register_and_login


def test_password_hash_roundtrip():
    h = hash_password("s3cret-password")
    assert h != "s3cret-password"
    assert verify_password("s3cret-password", h)
    assert not verify_password("wrong", h)


def test_token_type_is_enforced():
    tok = create_token("user-1", "access")
    assert decode_token(tok, "access") == "user-1"
    with pytest.raises(TokenError):
        decode_token(tok, "refresh")  # right signature, wrong type
    with pytest.raises(TokenError):
        decode_token("garbage.token.here", "access")


def test_permission_matrix():
    assert can(Role.OWNER, Action.DELETE_PROJECT)
    assert can(Role.EDITOR, Action.CREATE_TASK)
    assert not can(Role.VIEWER, Action.CREATE_TASK)
    assert not can(Role.EDITOR, Action.DELETE_PROJECT)
    assert not can(Role.EDITOR, Action.MANAGE_MEMBERS)
    assert can(Role.VIEWER, Action.VIEW_TASK)


async def test_register_login_me_flow(client):
    r = await client.post(
        "/auth/register",
        json={"email": "a@x.io", "full_name": "Ada", "password": "password123"},
    )
    assert r.status_code == 201
    assert r.json()["email"] == "a@x.io"
    assert "hashed_password" not in r.json()

    r = await client.post("/auth/login", data={"username": "a@x.io", "password": "password123"})
    assert r.status_code == 200
    tokens = r.json()
    assert tokens["token_type"] == "bearer"

    r = await client.get("/auth/me", headers=auth_header(tokens["access_token"]))
    assert r.status_code == 200
    assert r.json()["full_name"] == "Ada"


async def test_duplicate_email_conflicts(client):
    body = {"email": "dup@x.io", "full_name": "D", "password": "password123"}
    assert (await client.post("/auth/register", json=body)).status_code == 201
    assert (await client.post("/auth/register", json=body)).status_code == 409


async def test_login_wrong_password_401(client):
    await client.post(
        "/auth/register",
        json={"email": "b@x.io", "full_name": "B", "password": "password123"},
    )
    r = await client.post("/auth/login", data={"username": "b@x.io", "password": "nope"})
    assert r.status_code == 401


async def test_protected_route_requires_valid_token(client):
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/auth/me", headers=auth_header("bad"))).status_code == 401


async def test_refresh_rotates_access_token(client):
    token = await register_and_login(client, "c@x.io")
    login = await client.post("/auth/login", data={"username": "c@x.io", "password": "password123"})
    refresh = login.json()["refresh_token"]
    r = await client.post("/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200
    assert r.json()["access_token"]
    # An access token cannot be used to refresh.
    r = await client.post("/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401


async def test_short_password_rejected(client):
    r = await client.post(
        "/auth/register",
        json={"email": "e@x.io", "full_name": "E", "password": "short"},
    )
    assert r.status_code == 422
