"""Task use-cases: create, list (filter + paginate), fetch, update, delete.

Service layer: no FastAPI here. Authorization is enforced upstream by the
``require_project_permission`` dependency; this layer only enforces data-integrity
invariants (a task belongs to its project; an assignee must be a project member)
and raises domain errors the router maps to HTTP.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.models import ProjectMember, Task, TaskStatus


class TaskNotFound(Exception):
    """The task does not exist within the given project."""


class AssigneeNotMember(Exception):
    """The proposed assignee is not a member of the project."""


async def _is_member(session: AsyncSession, project_id: str, user_id: str) -> bool:
    result = await session.execute(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def create_task(
    session: AsyncSession,
    *,
    project_id: str,
    creator_id: str,
    title: str,
    description: str,
    status: TaskStatus,
    assignee_id: str | None,
) -> Task:
    if assignee_id is not None and not await _is_member(session, project_id, assignee_id):
        raise AssigneeNotMember(assignee_id)
    task = Task(
        project_id=project_id,
        title=title,
        description=description,
        status=status,
        assignee_id=assignee_id,
        created_by=creator_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def list_tasks(
    session: AsyncSession,
    *,
    project_id: str,
    status: TaskStatus | None = None,
    assignee_id: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Task], int]:
    """Return a page of tasks and the total matching count (ignoring paging)."""
    filters = [Task.project_id == project_id]
    if status is not None:
        filters.append(Task.status == status)
    if assignee_id is not None:
        filters.append(Task.assignee_id == assignee_id)

    total_result = await session.execute(select(func.count()).select_from(Task).where(*filters))
    total = total_result.scalar_one()

    items_result = await session.execute(
        select(Task)
        .where(*filters)
        .order_by(Task.created_at.desc(), Task.id)
        .limit(limit)
        .offset(offset)
    )
    items = list(items_result.scalars().all())
    return items, total


async def get_task(session: AsyncSession, *, project_id: str, task_id: str) -> Task:
    task = await session.get(Task, task_id)
    if task is None or task.project_id != project_id:
        raise TaskNotFound(task_id)
    return task


async def update_task(
    session: AsyncSession,
    *,
    project_id: str,
    task_id: str,
    changes: dict[str, Any],
) -> Task:
    """Apply the given partial ``changes`` (already exclude-unset) to the task.

    Validates that a newly assigned ``assignee_id`` (when not ``None``) is a
    project member.
    """
    task = await get_task(session, project_id=project_id, task_id=task_id)

    if "assignee_id" in changes:
        new_assignee = changes["assignee_id"]
        if new_assignee is not None and not await _is_member(session, project_id, new_assignee):
            raise AssigneeNotMember(new_assignee)

    for field, value in changes.items():
        setattr(task, field, value)

    await session.commit()
    await session.refresh(task)
    return task


async def delete_task(session: AsyncSession, *, project_id: str, task_id: str) -> None:
    task = await get_task(session, project_id=project_id, task_id=task_id)
    await session.delete(task)
    await session.commit()
