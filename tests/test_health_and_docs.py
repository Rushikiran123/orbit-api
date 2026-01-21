"""Smoke tests for operational endpoints: health check and OpenAPI docs.

These assert the app boots, the health probe is green, and the generated
OpenAPI schema advertises the feature areas (auth + the project/task slices).
"""

from collections.abc import Iterable

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_openapi_schema_served(client: AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert schema["info"]["title"] == "orbit"
    assert "/health" in schema["paths"]
    assert "/auth/login" in schema["paths"]


@pytest.mark.asyncio
async def test_swagger_docs_served(client: AsyncClient) -> None:
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "swagger-ui" in resp.text.lower()


def _tags_in(schema: dict) -> set[str]:
    tags: set[str] = set()
    paths: dict = schema["paths"]
    for methods in paths.values():
        for operation in methods.values():
            for tag in _as_list(operation.get("tags")):
                tags.add(tag)
    return tags


def _as_list(value: Iterable[str] | None) -> list[str]:
    return list(value) if value else []


@pytest.mark.asyncio
async def test_openapi_lists_feature_tags(client: AsyncClient) -> None:
    """The schema must advertise the auth tag; project/task tags appear once
    those slices are mounted (the app factory attaches them if present)."""
    schema = (await client.get("/openapi.json")).json()
    tags = _tags_in(schema)
    assert "auth" in tags
    # These are present whenever the sibling slices have been built.
    for optional_tag in ("projects", "tasks"):
        if any(optional_tag in path for path in schema["paths"]):
            assert optional_tag in tags
