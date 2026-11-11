"""The V1.1 word matcher: a B-roll suggestion against an asset's name, description and tags.

Since V1.3 this is one of the two signals of the hybrid matcher
(``app/services/semantic/matching.py``), which adds what each asset *shows* (local embeddings);
on its own it still answers when visual search is off or not ready. No internet, ever.

A suggestion says *what* would help ("toothpick bridge model"); the project's library may
already hold it. Each asset is described by its name (without the extension, split on
``-``, ``_``, ``.`` and spaces), its optional description and its tags (since V1.8 with the
category and place the creator labelled it with). A suggestion's
subject words (``validation.query_words``) are compared with those words on the same short
stems grounding uses (``bridge`` ↔ "bridges", ``launch`` ↔ "launched"):

    score = Σ weight(matched subject word) / number of subject words

with tags weighing most (``TAG_WEIGHT``), then the name, then the description. An asset is a
likely match only when at least ``MIN_SCORE`` of the suggestion is covered; at most
``MAX_MATCHES`` are returned, strongest first (ties: newest first). The creator still decides:
matches are offered, never placed automatically.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.models import VisualAsset
from app.services.asset_labels import VISUAL_CATEGORIES
from app.services.broll.grounding import stem
from app.services.broll.validation import query_words
from app.services.language import fold

TAG_WEIGHT = 1.0
NAME_WEIGHT = 0.9
DESCRIPTION_WEIGHT = 0.7
MIN_SCORE = 0.5
MAX_MATCHES = 3
_SPLIT = re.compile(r"[\s_.\-/]+")
_WORD = re.compile(r"[^\W\d_][\w'’]*", re.UNICODE)


def _stems(text: str) -> set[str]:
    # Compared folded ("café" ↔ "cafe", Arabic letter variants unified); never stored.
    return {stem(word) for word in _WORD.findall(fold(text)) if len(word) > 1}


@dataclass(frozen=True)
class AssetTerms:
    asset_id: str
    tags: frozenset[str]
    name: frozenset[str]
    description: frozenset[str]

    @classmethod
    def of(cls, asset: VisualAsset) -> "AssetTerms":
        name = PurePosixPath(asset.display_name).stem
        # V1.8: the category and place the creator chose are their own labels, so they count
        # like tags ("Casablanca café" finds a photo labelled Café · Casablanca). Unlabelled
        # assets match exactly as before.
        category = getattr(asset, "category", None)
        labels = [VISUAL_CATEGORIES.get(category, ""), getattr(asset, "location", None) or ""]
        return cls(
            asset_id=str(asset.id),
            tags=frozenset(s for tag in [*(asset.tags or []), *labels] for s in _stems(str(tag))),
            name=frozenset(_stems(" ".join(_SPLIT.split(name)))),
            description=frozenset(_stems(asset.description or "")),
        )


def match_score(query: str, terms: AssetTerms) -> float:
    words = {stem(word) for word in query_words(fold(query))}
    if not words:
        return 0.0
    total = 0.0
    for word in words:
        if word in terms.tags:
            total += TAG_WEIGHT
        elif word in terms.name:
            total += NAME_WEIGHT
        elif word in terms.description:
            total += DESCRIPTION_WEIGHT
    return round(total / len(words), 3)


def likely_matches(query: str, assets: list[VisualAsset]) -> list[str]:
    """The ids of the assets that likely show ``query``, strongest first (newest on ties)."""
    ordered = sorted(assets, key=lambda a: (a.created_at is None, a.created_at), reverse=True)
    scored = [
        (match_score(query, AssetTerms.of(asset)), index, asset)
        for index, asset in enumerate(ordered)
    ]
    good = [item for item in scored if item[0] >= MIN_SCORE]
    good.sort(key=lambda item: (-item[0], item[1]))
    return [str(asset.id) for _, _, asset in good[:MAX_MATCHES]]
