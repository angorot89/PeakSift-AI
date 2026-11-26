"""What a publish request may say, by YouTube's documented rules — refused, never trimmed.

YouTube's limits (videos resource, ``snippet``): a title of 1-100 characters, a
description of at most 5000 bytes, tags totalling at most 500 characters (a tag containing
a space counts its surrounding quotes, and tags are comma-separated), and no ``<`` or ``>``
in any of them. Text that breaks a rule is a ``422`` naming the field; PeakSift never
silently truncates or rewrites what the user reviewed.

Prefill (what the publish dialog starts with) comes from the clip's own candidate — its
title and hook — with no AI involved; the user edits it before anything is sent.
"""

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field

from app.models import Privacy

TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_BYTES = 5000
TAGS_MAX_CHARS = 500
TAG_MAX_COUNT = 50
# "People & Blogs": YouTube's default upload category. Users can change it in YouTube Studio.
DEFAULT_CATEGORY_ID = "22"
_ANGLE = re.compile(r"[<>]")


YOUTUBE_PRIVACY = (Privacy.PRIVATE, Privacy.UNLISTED, Privacy.PUBLIC)


class MetadataError(ValueError):
    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name
        self.message = message


@dataclass(frozen=True)
class PublishMetadata:
    title: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    privacy: Privacy = Privacy.PRIVATE
    made_for_kids: bool = False

    @classmethod
    def create(
        cls,
        *,
        title: str,
        description: str = "",
        tags: list[str] | tuple[str, ...] = (),
        privacy: Privacy | str = Privacy.PRIVATE,
        made_for_kids: bool = False,
    ) -> "PublishMetadata":
        title = title.strip()
        description = description.strip()
        cleaned_tags = tuple(tag.strip() for tag in tags)
        _check_text("title", title, allow_newlines=False)
        if not title:
            raise MetadataError("title", "Add a title")
        if len(title) > TITLE_MAX_CHARS:
            raise MetadataError(
                "title", f"The title is {len(title)} characters; YouTube allows {TITLE_MAX_CHARS}"
            )
        _check_text("description", description, allow_newlines=True)
        size = len(description.encode())
        if size > DESCRIPTION_MAX_BYTES:
            raise MetadataError(
                "description",
                f"The description is {size} bytes; YouTube allows {DESCRIPTION_MAX_BYTES}",
            )
        if len(cleaned_tags) > TAG_MAX_COUNT:
            raise MetadataError("tags", f"Use at most {TAG_MAX_COUNT} tags")
        for tag in cleaned_tags:
            if not tag:
                raise MetadataError("tags", "Tags cannot be empty")
            if "," in tag:
                raise MetadataError("tags", "A tag cannot contain a comma")
            _check_text("tags", tag, allow_newlines=False)
        if len({tag.casefold() for tag in cleaned_tags}) != len(cleaned_tags):
            raise MetadataError("tags", "Each tag can appear only once")
        counted = tags_length(cleaned_tags)
        if counted > TAGS_MAX_CHARS:
            raise MetadataError(
                "tags", f"The tags total {counted} characters; YouTube allows {TAGS_MAX_CHARS}"
            )
        try:
            privacy = Privacy(privacy)
        except ValueError:
            privacy = None
        if privacy not in YOUTUBE_PRIVACY:  # other platforms' levels are not YouTube's
            raise MetadataError("privacy", "Choose private, unlisted or public")
        return cls(title, description, cleaned_tags, privacy, bool(made_for_kids))


def tags_length(tags: tuple[str, ...] | list[str]) -> int:
    """YouTube's count: each tag, plus 2 for quotes around a tag with a space, plus commas."""
    if not tags:
        return 0
    return sum(len(tag) + (2 if " " in tag else 0) for tag in tags) + len(tags) - 1


def _check_text(field_name: str, text: str, *, allow_newlines: bool) -> None:
    if _ANGLE.search(text):
        raise MetadataError(field_name, "YouTube does not accept < or > here")
    for char in text:
        if char in "\n\r\t" and allow_newlines:
            continue
        if unicodedata.category(char) in ("Cc", "Cs"):
            raise MetadataError(field_name, "Remove control characters")


def fingerprint(
    *,
    connection_id: uuid.UUID,
    edit_id: uuid.UUID,
    metadata: PublishMetadata,
    options: dict | None = None,
) -> str:
    """Identifies one publish request: the same connection, edit, metadata and platform
    options is the same job (requested twice, it is not uploaded twice). Options are part of
    it only when there are any, so every existing fingerprint is unchanged."""
    payload = {
        "connection": str(connection_id),
        "edit": str(edit_id),
        "title": metadata.title,
        "description": metadata.description,
        "tags": list(metadata.tags),
        "privacy": metadata.privacy.value,
        "made_for_kids": metadata.made_for_kids,
        "category": DEFAULT_CATEGORY_ID,
    }
    if options:
        payload["options"] = options
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def prefill(candidate_title: str | None, candidate_hook: str | None) -> dict:
    """The dialog's starting values, from the clip's candidate; private; no tags."""
    title = _clean(candidate_title) or "My short"
    if len(title) > TITLE_MAX_CHARS:  # a suggestion the user sees and can change
        title = title[:TITLE_MAX_CHARS].rsplit(" ", 1)[0].rstrip(" ,.;:-") or title[:100]
    description = _clean(candidate_hook, keep_newlines=True)
    if len(description.encode()) > DESCRIPTION_MAX_BYTES:
        description = ""
    return {
        "title": title,
        "description": description,
        "tags": [],
        "privacy": Privacy.PRIVATE.value,
        "made_for_kids": False,
    }


def _clean(text: str | None, *, keep_newlines: bool = False) -> str:
    """Model-written candidate text made acceptable to YouTube's rules (angle brackets and
    control characters removed) — used only to *suggest* values."""
    text = _ANGLE.sub("", text or "")
    allowed = "\n" if keep_newlines else ""
    text = "".join(
        ch for ch in text if ch in allowed or unicodedata.category(ch) not in ("Cc", "Cs")
    )
    return text.strip() if keep_newlines else " ".join(text.split())
