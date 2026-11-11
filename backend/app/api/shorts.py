"""The Shorts library: ``GET /shorts`` and ``GET /shorts/{short_id}``.

Read-only and owner-scoped (another creator's Short is a ``404``), built from existing rows by
``services/shorts_library.py``, which derives each Short's one creator-level status. A
``short_id`` is a version's id, or a draft's (a clip without versions; once it has versions the
newest one is returned, so an old draft link keeps working).
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.schemas.shorts import ShortDetailRead, ShortsLibraryRead
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
    return found
