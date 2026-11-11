"""What an Auto Edit plan depends on, and the fingerprint that decides "same plan or new plan".

A plan is a function of its inputs: the clip (and which rendered file it is), the transcript,
the clip's word timing, its framing analysis, its B-roll suggestions, the project's visual and
audio assets as the planner can see them, and the request (recipe and version, planner and
version, an explicit music choice, generation). ``PlanSources`` lists exactly those facts —
values that change what a planner could choose — and nothing unstable: no timestamps, no
progress, no storage paths beyond the clip's artifact identity.

Equal sources and request → equal fingerprint → the existing plan is reused. Any meaningful
change (a new caption track, a tagged asset, a dismissed suggestion, a different recipe or a
deliberate regeneration) → a new fingerprint → a new plan; earlier plans are kept.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

SOURCE_FINGERPRINT_VERSION = "auto_edit_sources_v1"
_DECIMALS = 3


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), _DECIMALS)


@dataclass(frozen=True)
class SuggestionFacts:
    id: str
    start: float
    end: float
    query: str
    status: str  # suggested / accepted / dismissed: dismissed ones are never planned


@dataclass(frozen=True)
class VisualAssetFacts:
    id: str
    kind: str
    name: str
    description: str
    tags: tuple[str, ...]
    width: int
    height: int
    duration: float | None
    has_alpha: bool
    # V1.3: the asset's current visual-search index ("ready:<id>"), when one exists — a plan
    # made before an asset was searchable by what it shows is not reused afterwards.
    semantic: str | None = None
    # V1.8: the market the asset is local to, when it is local (a relabelled asset reorders
    # local-first matches, so the plan is not reused).
    market: str | None = None


@dataclass(frozen=True)
class AudioAssetFacts:
    id: str
    kind: str  # music / sfx
    name: str
    duration: float


@dataclass(frozen=True)
class PlanSources:
    clip_id: str
    # Which rendered clip file the plan was made for (a re-render is a new artifact).
    clip_artifact: str | None
    clip_duration: float
    transcript_fingerprint: str | None = None
    caption_track_id: str | None = None
    reframe_analysis_id: str | None = None
    reframe_confidence: str | None = None
    broll_analysis_id: str | None = None
    suggestions: tuple[SuggestionFacts, ...] = field(default_factory=tuple)
    visual_assets: tuple[VisualAssetFacts, ...] = field(default_factory=tuple)
    audio_assets: tuple[AudioAssetFacts, ...] = field(default_factory=tuple)
    # V1.3: the matching model and its thresholds version, when visual search is on.
    matching: str | None = None
    # V1.8: the project's local market (Morocco Mode), when it is not Global.
    market: str | None = None

    def canonical(self) -> dict[str, Any]:
        """Order-independent, rounded form: equal facts give equal JSON."""
        data = asdict(self)
        data["clip_duration"] = _round(self.clip_duration)
        data["suggestions"] = sorted(
            (
                {**asdict(s), "start": _round(s.start), "end": _round(s.end)}
                for s in self.suggestions
            ),
            key=lambda s: (s["start"], s["end"], s["id"]),
        )
        data["visual_assets"] = sorted(
            (
                _without_empty(
                    _without_empty(
                        {**asdict(a), "tags": sorted(a.tags), "duration": _round(a.duration)},
                        "semantic",
                    ),
                    "market",
                )
                for a in self.visual_assets
            ),
            key=lambda a: a["id"],
        )
        data["audio_assets"] = sorted(
            ({**asdict(a), "duration": _round(a.duration)} for a in self.audio_assets),
            key=lambda a: a["id"],
        )
        return _without_empty(_without_empty(data, "matching"), "market")


def _without_empty(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Facts added after V1.2 appear only when present, so earlier fingerprints are unchanged."""
    if data.get(key) is None:
        data.pop(key, None)
    return data


def source_fingerprint(sources: PlanSources, request: dict[str, Any]) -> str:
    """sha256 over the canonical sources and the plan request snapshot."""
    canonical = json.dumps(
        {"version": SOURCE_FINGERPRINT_VERSION, "sources": sources.canonical(), "request": request},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
