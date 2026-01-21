"""Project & membership endpoints.

Every project-scoped route authorizes through ``require_project_permission`` —
the only sanctioned authorization path. Non-members receive 404 (existence is not
leaked); members with an insufficient role receive 403. Services raise domain
errors that are mapped to HTTP here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from orbit.api.deps import CurrentUser, SessionDep, require_project_permission
from orbit.api.schemas.project import (
    MemberAdd,
    MemberOut,
    MemberUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from orbit.domain.roles import Action, Role
from orbit.models import Project
from orbit.services import project_service
from orbit.services.project_service import (
    AlreadyMember,
    LastOwnerError,
    MemberNotFound,
    UserNotFound,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _project_out(project: Project, role: Role) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        created_by=project.created_by,
        created_at=project.created_at,
        role=role,
    )


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: CurrentUser, session: SessionDep) -> ProjectOut:
    project = await project_service.create_project(session, user, body.name, body.description)
    return _project_out(project, Role.OWNER)


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, session: SessionDep) -> list[ProjectOut]:
    pairs = await project_service.list_projects_for_user(session, user.id)
    return [_project_out(project, role) for project, role in pairs]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    session: SessionDep,
    role: Annotated[Role, Depends(require_project_permission(Action.VIEW_PROJECT))],
) -> ProjectOut:
    project = await project_service.get_project(session, project_id)
    return _project_out(project, role)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    session: SessionDep,
    role: Annotated[Role, Depends(require_project_permission(Action.EDIT_PROJECT))],
) -> ProjectOut:
    project = await project_service.update_project(session, project_id, body.name, body.description)
    return _project_out(project, role)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    session: SessionDep,
    _: Annotated[Role, Depends(require_project_permission(Action.DELETE_PROJECT))],
) -> None:
    await project_service.delete_project(session, project_id)


@router.get("/{project_id}/members", response_model=list[MemberOut])
async def list_members(
    project_id: str,
    session: SessionDep,
    _: Annotated[Role, Depends(require_project_permission(Action.VIEW_PROJECT))],
) -> list[MemberOut]:
    rows = await project_service.list_members(session, project_id)
    return [
        MemberOut(
            user_id=member.user_id,
            email=user.email,
            full_name=user.full_name,
            role=Role(member.role),
        )
        for member, user in rows
    ]


@router.post(
    "/{project_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: str,
    body: MemberAdd,
    session: SessionDep,
    _: Annotated[Role, Depends(require_project_permission(Action.MANAGE_MEMBERS))],
) -> MemberOut:
    try:
        member, user = await project_service.add_member(
            session, project_id, body.role, user_id=body.user_id, email=body.email
        )
    except UserNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except AlreadyMember as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this project",
        ) from exc
    return MemberOut(
        user_id=member.user_id,
        email=user.email,
        full_name=user.full_name,
        role=Role(member.role),
    )


@router.patch("/{project_id}/members/{user_id}", response_model=MemberOut)
async def update_member(
    project_id: str,
    user_id: str,
    body: MemberUpdate,
    session: SessionDep,
    _: Annotated[Role, Depends(require_project_permission(Action.MANAGE_MEMBERS))],
) -> MemberOut:
    try:
        member, user = await project_service.update_member_role(
            session, project_id, user_id, body.role
        )
    except MemberNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        ) from exc
    except LastOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot demote the last owner of the project",
        ) from exc
    return MemberOut(
        user_id=member.user_id,
        email=user.email,
        full_name=user.full_name,
        role=Role(member.role),
    )


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: str,
    user_id: str,
    session: SessionDep,
    _: Annotated[Role, Depends(require_project_permission(Action.MANAGE_MEMBERS))],
) -> None:
    try:
        await project_service.remove_member(session, project_id, user_id)
    except MemberNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        ) from exc
    except LastOwnerError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the last owner of the project",
        ) from exc
