"""Task request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from orbit.models import TaskStatus


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10000)
    status: TaskStatus = TaskStatus.TODO
    assignee_id: str | None = None


class TaskUpdate(BaseModel):
    """Partial update. Any field left unset is untouched.

    ``assignee_id`` uses a sentinel-free convention: send ``null`` to unassign,
    omit the field to leave the current assignee unchanged.
    """

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None
    assignee_id: str | None = None

    model_config = {"extra": "forbid"}


class TaskOut(BaseModel):
    id: str
    project_id: str
    title: str
    description: str
    status: TaskStatus
    assignee_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskList(BaseModel):
    items: list[TaskOut]
    total: int
    limit: int
    offset: int
