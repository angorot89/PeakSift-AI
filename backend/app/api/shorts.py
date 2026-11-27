"""The Shorts library: ``GET /shorts`` and ``GET /shorts/{short_id}``.

Owner-scoped (another creator's Short is a ``404``) and read-only except for hiding a Short from
the library (``PATCH /shorts/{short_id}``), built from existing rows by
``services/shorts_library.py``, which derives each Short's one creator-level status. A
``short_id`` is a version's id, or a draft's (a clip without versions; once it has versions the
newest one is returned, so an old draft link keeps working).
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.api.performance import analytics_access
from app.core.config import get_settings
from app.schemas.shorts import ShortDetailRead, ShortsLibraryRead, ShortUpdate, ShortUpdateRead
from app.services import shorts_library

router = APIRouter(prefix="/shorts", tags=["shorts"])


@router.get("", response_model=ShortsLibraryRead)
def shorts(current_user: CurrentUser, db: DbSession) -> dict:
    return shorts_library.library(db, current_user.id, get_settings())


@router.get("/{short_id}", response_model=ShortDetailRead)
def short(short_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> dict:
    found = shorts_library.detail(db, current_user.id, short_id, get_settings())
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short not found")
    return {**found, "analytics": analytics_access(db, current_user.id)}


@router.patch("/{short_id}", response_model=ShortUpdateRead)
def update_short(
    short_id: uuid.UUID, body: ShortUpdate, current_user: CurrentUser, db: DbSession
) -> dict:
    """Hide a Short (or draft) from the library, or show it again. Nothing else changes: it can
    still be opened, edited, published and scheduled."""
    if not shorts_library.set_hidden(db, current_user.id, short_id, body.hidden):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Short not found")
    return {"id": short_id, "hidden": body.hidden}
