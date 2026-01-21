"""Task endpoints, nested under a project and gated by project RBAC.

Every route depends on ``require_project_permission(...)`` — the only sanctioned
authorization path. That dependency resolves the caller's membership from the
path ``project_id`` (404 for non-members, 403 for an insufficient role) before
any handler body runs, so these handlers never re-derive role checks.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from orbit.api.deps import CurrentUser, SessionDep, require_project_permission
from orbit.api.schemas.task import TaskCreate, TaskList, TaskOut, TaskUpdate
from orbit.domain.roles import Action
from orbit.models import TaskStatus
from orbit.services import task_service
from orbit.services.task_service import AssigneeNotMember, TaskNotFound

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


def _assignee_error(exc: AssigneeNotMember) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Assignee must be a member of the project",
    )


@router.post(
    "",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_project_permission(Action.CREATE_TASK))],
)
async def create_task(
    project_id: str,
    body: TaskCreate,
    session: SessionDep,
    user: CurrentUser,
) -> TaskOut:
    try:
        task = await task_service.create_task(
            session,
            project_id=project_id,
            creator_id=user.id,
            title=body.title,
            description=body.description,
            status=body.status,
            assignee_id=body.assignee_id,
        )
    except AssigneeNotMember as exc:
        raise _assignee_error(exc) from exc
    return TaskOut.model_validate(task)


@router.get(
    "",
    response_model=TaskList,
    dependencies=[Depends(require_project_permission(Action.VIEW_TASK))],
)
async def list_tasks(
    project_id: str,
    session: SessionDep,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    assignee_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskList:
    items, total = await task_service.list_tasks(
        session,
        project_id=project_id,
        status=status_filter,
        assignee_id=assignee_id,
        limit=limit,
        offset=offset,
    )
    return TaskList(
        items=[TaskOut.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{task_id}",
    response_model=TaskOut,
    dependencies=[Depends(require_project_permission(Action.VIEW_TASK))],
)
async def get_task(project_id: str, task_id: str, session: SessionDep) -> TaskOut:
    try:
        task = await task_service.get_task(session, project_id=project_id, task_id=task_id)
    except TaskNotFound as exc:
        raise _NOT_FOUND from exc
    return TaskOut.model_validate(task)


@router.patch(
    "/{task_id}",
    response_model=TaskOut,
    dependencies=[Depends(require_project_permission(Action.EDIT_TASK))],
)
async def update_task(
    project_id: str,
    task_id: str,
    body: TaskUpdate,
    session: SessionDep,
) -> TaskOut:
    changes = body.model_dump(exclude_unset=True)
    try:
        task = await task_service.update_task(
            session, project_id=project_id, task_id=task_id, changes=changes
        )
    except TaskNotFound as exc:
        raise _NOT_FOUND from exc
    except AssigneeNotMember as exc:
        raise _assignee_error(exc) from exc
    return TaskOut.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_project_permission(Action.DELETE_TASK))],
)
async def delete_task(project_id: str, task_id: str, session: SessionDep) -> None:
    try:
        await task_service.delete_task(session, project_id=project_id, task_id=task_id)
    except TaskNotFound as exc:
        raise _NOT_FOUND from exc
