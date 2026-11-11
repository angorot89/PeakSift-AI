"""The creator-facing pages PeakSift links to, in one place (the frontend's routes).

Used by the next-action engine (Home's *Continue working*, the project Overview) and by Copilot
actions, so a step suggested anywhere opens the same page. Only ids the creator owns ever go in.
"""

import uuid
from urllib.parse import quote


def brand_studio() -> str:
    return "/brand"


def template(template_id: uuid.UUID) -> str:
    return f"/brand/templates/{template_id}"


def home() -> str:
    return "/home"


def new_project() -> str:
    return "/projects/new"


def analytics(published_id: uuid.UUID | None = None) -> str:
    return f"/analytics/{published_id}" if published_id else "/analytics"


def shorts() -> str:
    return "/shorts"


def short(short_id: uuid.UUID) -> str:
    """One Short (a version id) or draft (a clip id)."""
    return f"/shorts/{short_id}"


def project(project_id: uuid.UUID, section: str = "") -> str:
    """``section``: "" (Overview), "source", "clips", "assets" or "analytics"."""
    return f"/projects/{project_id}" + (f"/{section}" if section else "")


def assets_search(project_id: uuid.UUID, query: str) -> str:
    return f"{project(project_id, 'assets')}?q={quote(query, safe='')}"


def create(project_id: uuid.UUID, clip_id: uuid.UUID) -> str:
    return f"/projects/{project_id}/clips/{clip_id}/create"


def auto_edit(project_id: uuid.UUID, clip_id: uuid.UUID) -> str:
    return f"/projects/{project_id}/clips/{clip_id}/auto-edit"


def editor(
    project_id: uuid.UUID,
    clip_id: uuid.UUID,
    *,
    edit_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
) -> str:
    path = f"/projects/{project_id}/clips/{clip_id}"
    if edit_id:
        return f"{path}?edit={edit_id}"
    if plan_id:
        return f"{path}?plan={plan_id}"
    return path
