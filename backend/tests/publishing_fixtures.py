"""Plain helpers (not fixtures) for publishing tests: a ready edit and a connected account."""

import uuid

from sqlalchemy.orm import Session

from app.models import ClipEdit, PublishingConnection, User
from app.services.clip_edit.config import EditConfig
from app.services.clip_edit.storage import edit_storage_key
from app.services.publishing import connections
from app.services.publishing.tokens import TokenCipher, decode_key, generate_key
from tests.test_clip_edit_model import make_clip, make_edit

REFRESH_TOKEN = "1//0gPublishingTestRefreshToken"
CIPHER = TokenCipher(decode_key(generate_key()), 1)


def ready_edit(db: Session, *, status: str = "ready") -> tuple[User, ClipEdit]:
    clip = make_clip(db)
    edit = make_edit(db, clip, EditConfig.create(layout="center_crop", captions_enabled=False))
    edit.status = status
    if status == "ready":
        edit.storage_key = edit_storage_key(edit.id)
        edit.file_size, edit.duration_seconds = 4096, 20.0
    db.commit()
    return clip.video.project.owner, edit


def connect(db: Session, user: User, cipher: TokenCipher = CIPHER) -> PublishingConnection:
    return connections.save_connection(
        db, cipher, user_id=user.id, refresh_token=REFRESH_TOKEN, account_id="",
        account_title="", scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )  # fmt: skip


def new_user(db: Session) -> User:
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db.add(user)
    db.commit()
    return user
