"""Project & membership use-cases.

Service layer: no FastAPI here. Functions raise domain errors that the router
maps to HTTP responses. Authorization (who may call what) is enforced upstream by
``require_project_permission`` in the router; this layer trusts that gate and only
encodes *business* invariants — most importantly the **last-owner guard**: a
project must always retain at least one owner.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.domain.roles import Role
from orbit.models import Project, ProjectMember, User


class UserNotFound(Exception):
    """The user to add as a member does not exist."""


class AlreadyMember(Exception):
    """The user is already a member of the project."""


class MemberNotFound(Exception):
    """The target user is not a member of the project."""


class LastOwnerError(Exception):
    """The operation would leave the project with no owner."""


async def create_project(
    session: AsyncSession, creator: User, name: str, description: str
) -> Project:
    """Create a project and auto-enroll the creator as an owner, atomically."""
    project = Project(name=name, description=description, created_by=creator.id)
    session.add(project)
    await session.flush()  # assigns project.id without committing
    session.add(ProjectMember(project_id=project.id, user_id=creator.id, role=Role.OWNER))
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects_for_user(session: AsyncSession, user_id: str) -> list[tuple[Project, Role]]:
    """Return (project, caller_role) for every project the user belongs to."""
    result = await session.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
        .order_by(Project.created_at)
    )
    return [(project, Role(role)) for project, role in result.all()]


async def get_project(session: AsyncSession, project_id: str) -> Project:
    """Fetch a project by id. Membership is validated by the router's gate."""
    project = await session.get(Project, project_id)
    if project is None:  # pragma: no cover - gate resolves membership first
        raise MemberNotFound(project_id)
    return project


async def update_project(
    session: AsyncSession,
    project_id: str,
    name: str | None,
    description: str | None,
) -> Project:
    project = await get_project(session, project_id)
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, project_id: str) -> None:
    project = await get_project(session, project_id)
    await session.delete(project)
    await session.commit()


async def list_members(session: AsyncSession, project_id: str) -> list[tuple[ProjectMember, User]]:
    result = await session.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.email)
    )
    return [(member, user) for member, user in result.all()]


async def _get_membership(
    session: AsyncSession, project_id: str, user_id: str
) -> ProjectMember | None:
    result = await session.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _owner_count(session: AsyncSession, project_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(ProjectMember)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.role == Role.OWNER,
        )
    )
    return result.scalar_one()


async def add_member(
    session: AsyncSession,
    project_id: str,
    role: Role,
    *,
    user_id: str | None = None,
    email: str | None = None,
) -> tuple[ProjectMember, User]:
    """Add a member identified by id or email. Returns (membership, user).

    Raises ``UserNotFound`` if no such user, ``AlreadyMember`` if already enrolled.
    """
    if email is not None:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
    else:
        user = await session.get(User, user_id)
    if user is None:
        raise UserNotFound(email or user_id)

    if await _get_membership(session, project_id, user.id) is not None:
        raise AlreadyMember(user.id)

    membership = ProjectMember(project_id=project_id, user_id=user.id, role=role)
    session.add(membership)
    await session.commit()
    await session.refresh(membership)
    return membership, user


async def update_member_role(
    session: AsyncSession, project_id: str, user_id: str, role: Role
) -> tuple[ProjectMember, User]:
    """Change a member's role, guarding the last owner.

    Raises ``MemberNotFound`` if the user isn't a member; ``LastOwnerError`` if
    demoting would drop the project's owner count to zero.
    """
    membership = await _get_membership(session, project_id, user_id)
    if membership is None:
        raise MemberNotFound(user_id)
    demoting_owner = membership.role == Role.OWNER and role != Role.OWNER
    if demoting_owner and await _owner_count(session, project_id) <= 1:
        raise LastOwnerError(project_id)
    membership.role = role
    await session.commit()
    await session.refresh(membership)
    user = await session.get(User, user_id)
    assert user is not None  # FK guarantees existence
    return membership, user


async def remove_member(session: AsyncSession, project_id: str, user_id: str) -> None:
    """Remove a member, guarding the last owner.

    Raises ``MemberNotFound`` if the user isn't a member; ``LastOwnerError`` if
    removing would leave the project without an owner.
    """
    membership = await _get_membership(session, project_id, user_id)
    if membership is None:
        raise MemberNotFound(user_id)
    if membership.role == Role.OWNER and await _owner_count(session, project_id) <= 1:
        raise LastOwnerError(project_id)
    await session.delete(membership)
    await session.commit()
