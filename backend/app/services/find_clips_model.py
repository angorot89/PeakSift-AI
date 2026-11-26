"""Find Clips: related words from the local model, to widen a search — never to answer it.

"The funniest moment" is rarely said with the word "funniest". The local model is asked for a
few single words a speaker would plausibly *say* in the moment being described. Those words are
only extra search terms: the search still returns nothing but real transcript lines, a related
word counts for less than the creator's own, and every result says which words were heard.

Optional by design. No model, a slow model or a strange answer all mean "no related words";
the search then runs on the creator's own words alone.
"""

import json
import logging

import httpx

from app.core.config import Settings
from app.services.copilot.provider import assistant_available, configured_model

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8.0
MAX_WORDS = 12

_SYSTEM = (
    "You help search the transcript of a video. The user describes a moment they are looking "
    "for. Answer with up to 10 single words that a speaker would probably SAY OUT LOUD during "
    "that moment: synonyms and closely related everyday words, in the same language as the "
    "request. Single words only, no phrases, no explanations. "
    'Answer as JSON: {"words": ["...", "..."]}'
)
_SCHEMA = {
    "type": "object",
    "properties": {"words": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_WORDS}},
    "required": ["words"],
}


def related_words(
    query: str, settings: Settings, *, client: httpx.Client | None = None
) -> list[str]:
    """Up to ``MAX_WORDS`` raw suggestions (validated by ``find_clips.related_terms``), or []."""
    if settings.copilot_provider == "fake" or not assistant_available(settings):
        return []
    payload = {
        "model": configured_model(settings),
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": query[:200]},
        ],
        "stream": False,
        "format": _SCHEMA,
        "options": {"temperature": 0, "num_predict": 120},
    }
    owned = client is None
    client = client or httpx.Client(base_url=settings.ollama_base_url.rstrip("/"))
    try:
        response = client.post(
            "/api/chat",
            json=payload,
            timeout=httpx.Timeout(
                TIMEOUT_SECONDS,
                connect=min(settings.ollama_connect_timeout_seconds, TIMEOUT_SECONDS),
            ),
        )
        response.raise_for_status()
        answer = json.loads(response.json()["message"]["content"])
        suggested = answer["words"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.info("Find Clips: no related words from the local model")
        return []
    finally:
        if owned:
            client.close()
    if not isinstance(suggested, list):
        return []
    return [word for word in suggested if isinstance(word, str)][:MAX_WORDS]
