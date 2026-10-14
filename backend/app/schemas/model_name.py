"""Model names as users see them.

``FASTER_WHISPER_MODEL`` may name a model size ("small") or a local model directory; a
directory is server internals, so responses show it as "custom" instead of the path.
"""

import re
from typing import Annotated

from pydantic import PlainSerializer

_PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def public_model_name(value: str) -> str:
    return value if _PLAIN_NAME.fullmatch(value) and ".." not in value else "custom"


PublicModelName = Annotated[str, PlainSerializer(public_model_name, return_type=str)]
