"""FastAPI dependencies: DB session, current user, and the RBAC gate.

``require_project_role`` / ``require_project_permission`` are the ONLY sanctioned
way for feature routers to authorize project-scoped access. They resolve the
caller's membership role and enforce the domain permission matrix, raising 404
for non-members (so private projects don't leak existence) and 403 for
insufficient role.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.core.security import TokenError, decode_token
from orbit.db.base import get_session
from orbit.domain.roles import Action, Role, can
from orbit.models import ProjectMember, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


async def get_current_user(
    session: SessionDep,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> User:
    """Resolve the authenticated user from a valid access token."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_token(token, expected_type="access")
    except TokenError as exc:
        raise credentials_error from exc
    user = await session.get(User, user_id)
    if user is None:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def _member_role(session: AsyncSession, project_id: str, user_id: str) -> Role | None:
    result = await session.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    role = result.scalar_one_or_none()
    return Role(role) if role is not None else None


def require_project_permission(action: Action):
    """Build a dependency that enforces ``action`` on the path's ``project_id``.

    404 if the caller is not a member (don't reveal existence); 403 if their
    role lacks the permission. On success, returns the caller's Role.
    """

    async def dependency(
        project_id: str,
        session: SessionDep,
        user: CurrentUser,
    ) -> Role:
        role = await _member_role(session, project_id, user.id)
        if role is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not can(role, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Your role ({role}) cannot {action}",
            )
        return role

    return dependency
