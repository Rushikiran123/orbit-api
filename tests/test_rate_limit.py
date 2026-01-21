"""Rate-limit hardening test.

The shared ``client`` fixture disables the limiter to avoid flaky tests, so here
we build a *fresh* app with the limiter re-enabled and prove that exceeding the
configured ``auth_rate_limit`` on an auth endpoint yields HTTP 429.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orbit.core.config import get_settings
from orbit.core.rate_limit import limiter


def _limit_count() -> int:
    """Parse the numeric portion of e.g. ``"10/minute"``."""
    return int(get_settings().auth_rate_limit.split("/")[0])


@pytest_asyncio.fixture
async def limited_client(db_engine) -> AsyncIterator[AsyncClient]:
    """An app identical to the shared client but with the limiter ENABLED."""
    from orbit.db.base import get_session
    from orbit.main import create_app

    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_session] = _override_session

    previous_enabled = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        limiter.reset()
        limiter.enabled = previous_enabled


@pytest.mark.asyncio
async def test_auth_endpoint_rate_limited(limited_client: AsyncClient) -> None:
    limit = _limit_count()
    body = {
        "email": "ratelimit@example.com",
        "full_name": "Rate Limited",
        "password": "password123",
    }

    statuses = [
        (await limited_client.post("/auth/register", json=body)).status_code
        for _ in range(limit + 1)
    ]

    # Every request up to the limit is admitted (not throttled); at least the
    # final over-limit request is rejected with 429.
    assert 429 not in statuses[:limit]
    assert statuses[-1] == 429


@pytest.mark.asyncio
async def test_limiter_disabled_in_default_client(client: AsyncClient) -> None:
    """Sanity: the shared fixture leaves the limiter off, so bursts pass."""
    for _ in range(_limit_count() + 3):
        resp = await client.get("/health")
        assert resp.status_code == 200
