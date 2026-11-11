"""Markets (V1.8): ``GET /markets`` — the markets PeakSift offers and the content languages a
project can be in. Read-only, the same for every signed-in creator (no creator data)."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.services import markets

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("")
def list_markets(current_user: CurrentUser) -> dict:
    return {
        "markets": [profile.read() for profile in markets.MARKETS.values()],
        "content_languages": [
            {"code": code, "label": label} for code, label in markets.CONTENT_LANGUAGES.items()
        ],
    }
