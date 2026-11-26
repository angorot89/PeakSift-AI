"""Quick start: the project's name when the creator dropped a video without naming anything."""

import re
from pathlib import PurePosixPath

MAX_NAME_LENGTH = 200
FALLBACK_NAME = "New project"

_SEPARATORS = re.compile(r"[\s_\-.]+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def project_name(given: str | None, filename: str | None) -> str:
    """The creator's own name if they typed one; otherwise a readable one from the file name.

    ``Friday_stream-2026.09.28.mp4`` becomes ``Friday stream 2026 09 28``. The file name is
    only ever text here — never a path (the upload itself is stored under a generated key).
    """
    typed = _CONTROL.sub(" ", given or "").strip()
    if typed:
        return typed[:MAX_NAME_LENGTH].strip()
    # Browsers send a bare name, but be safe about either kind of separator.
    base = (filename or "").replace("\\", "/")
    stem = PurePosixPath(base).stem if base else ""
    readable = _SEPARATORS.sub(" ", _CONTROL.sub(" ", stem)).strip()
    return readable[:MAX_NAME_LENGTH].strip() or FALLBACK_NAME
