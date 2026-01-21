"""Authentication use-cases: registration and credential verification.

Service layer: no FastAPI here. Raises domain errors the router maps to HTTP.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.core.security import hash_password, verify_password
from orbit.models import User


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    pass


async def register_user(session: AsyncSession, email: str, full_name: str, password: str) -> User:
    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise EmailAlreadyRegistered(email)
    user = User(email=email, full_name=full_name, hashed_password=hash_password(password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    # Verify even when the user is missing to avoid a timing side-channel that
    # would reveal which emails are registered.
    dummy_hash = "$2b$12$" + "x" * 53
    if user is None:
        verify_password(password, dummy_hash)
        raise InvalidCredentials(email)
    if not verify_password(password, user.hashed_password):
        raise InvalidCredentials(email)
    return user
