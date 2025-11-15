"""Project roles and the permission matrix — pure domain logic, no framework deps.

This is the single source of truth for "who can do what" and is unit-tested on
its own. The API layer enforces it via a dependency; services never re-derive it.
"""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class Action(StrEnum):
    # Project-level
    VIEW_PROJECT = "view_project"
    EDIT_PROJECT = "edit_project"
    DELETE_PROJECT = "delete_project"
    MANAGE_MEMBERS = "manage_members"
    # Task-level
    VIEW_TASK = "view_task"
    CREATE_TASK = "create_task"
    EDIT_TASK = "edit_task"
    DELETE_TASK = "delete_task"


# What each role is allowed to do. Higher roles are supersets, but we list
# explicitly rather than rely on ordering so the matrix is auditable.
_MATRIX: dict[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset({Action.VIEW_PROJECT, Action.VIEW_TASK}),
    Role.EDITOR: frozenset(
        {
            Action.VIEW_PROJECT,
            Action.VIEW_TASK,
            Action.CREATE_TASK,
            Action.EDIT_TASK,
            Action.DELETE_TASK,
        }
    ),
    Role.OWNER: frozenset(Action),  # everything
}


def can(role: Role, action: Action) -> bool:
    """True if ``role`` is permitted to perform ``action``."""
    return action in _MATRIX[role]


def require(role: Role, action: Action) -> None:
    """Raise PermissionError if ``role`` may not perform ``action``."""
    if not can(role, action):
        raise PermissionError(f"role {role} may not {action}")
