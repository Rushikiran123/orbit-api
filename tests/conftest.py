"""Test fixtures: a real ephemeral Postgres (testcontainers), an async client,
and auth helpers. Every test runs against Postgres — no SQLite dialect fudging.

The container is session-scoped (expensive to start); the engine and schema are
per-test so each test is fully isolated AND the async engine is bound to the
test's own event loop (avoids cross-loop errors with pytest-asyncio).
"""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def _postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        os.environ["ORBIT_DATABASE_URL"] = url
        yield url


@pytest_asyncio.fixture
async def db_engine(_postgres_url: str):
    from orbit.db.base import Base
    from orbit.models import Project, ProjectMember, Task, User  # noqa: F401  register metadata

    engine = create_async_engine(_postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def client(db_engine) -> AsyncIterator[AsyncClient]:
    """An httpx client bound to the ASGI app, sharing this test's engine."""
    from orbit.db.base import get_session
    from orbit.main import create_app

    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            try:
                yield s
            except Exception:
                await s.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_session] = _override_session
    app.state.limiter.enabled = False  # avoid rate-limit flakes in tests

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register_and_login(client: AsyncClient, email: str, password: str = "password123") -> str:
    """Register a user and return an access token (helper for auth-required tests)."""
    await client.post(
        "/auth/register",
        json={"email": email, "full_name": email.split("@")[0], "password": password},
    )
    resp = await client.post("/auth/login", data={"username": email, "password": password})
    return resp.json()["access_token"]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
