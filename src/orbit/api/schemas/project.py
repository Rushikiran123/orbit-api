"""Project & membership request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

from orbit.domain.roles import Role


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProjectUpdate":
        if self.name is None and self.description is None:
            raise ValueError("At least one of name or description must be provided")
        return self


class ProjectOut(BaseModel):
    """A project plus the requesting caller's role in it."""

    id: str
    name: str
    description: str
    created_by: str
    created_at: datetime
    role: Role

    model_config = {"from_attributes": True}


class MemberOut(BaseModel):
    user_id: str
    email: EmailStr
    full_name: str
    role: Role


class MemberAdd(BaseModel):
    """Identify the target user by id or email; assign a role."""

    user_id: str | None = None
    email: EmailStr | None = None
    role: Role

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "MemberAdd":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("Provide exactly one of user_id or email")
        return self


class MemberUpdate(BaseModel):
    role: Role
