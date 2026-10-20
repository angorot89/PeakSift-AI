"""The Auto Edit planner contract: what a planner is told, what it must answer, and its errors.

A planner receives an ``AutoEditContext`` — application-level facts only, never database rows or
provider objects: the clip's timed transcript and candidate metadata, what PeakSift can render
for it (``Capabilities``), the recipe's bounds, the validated B-roll suggestions with the
project assets that match them, and the audio the creator made available. Everything a planner
can point at has a **symbolic handle** (``suggestion_1``, ``visual_asset_2``, ``music_1``,
``sfx_1``); the real ids stay in the context's handle maps and never reach a model. A handle
the server did not issue is simply unknown.

It answers an ``AutoEditProposal``: strict, typed JSON (unknown keys are refused) of
creator-level choices — a framing mode, a caption preset and position, a hook, visuals as
(suggestion, asset, mode) handles, a music level, ducking and whether to use transition
sounds — plus one short explanation per section. A proposal is still **untrusted**: the
server's plan validator maps handles to ids, enforces the recipe and checks every choice
against what exists before anything becomes an edit configuration. A planner never decides
FFmpeg syntax, storage, URLs, ids, coordinates or raw volumes.
"""

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PLANNER_VERSION = "auto_edit_planner_v1"

SUGGESTION_HANDLE = re.compile(r"^suggestion_[1-9][0-9]?$")
VISUAL_HANDLE = re.compile(r"^visual_asset_[1-9][0-9]{0,2}$")
MUSIC_HANDLE = "music_1"
EXPLANATION_MAX_CHARS = 200
RAW_HOOK_MAX_CHARS = 120  # the renderer's own limit (60) is enforced by the plan validator
MAX_PROPOSED_VISUALS = 8
STRONG_MATCH_SCORE = 0.9  # matching.match_score: (nearly) every subject word covered


# --- context ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TimedLine:
    """One transcript line in clip-local seconds (0 = the clip's first frame)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Capabilities:
    """What this server can render for this clip, stated explicitly (never guessed)."""

    smart_reframe: bool  # a completed framing analysis of this clip exists
    reframe_confidence: str | None  # high / mixed / fallback, when it exists
    word_timing: bool  # a completed word-timing track exists (word-synced captions)
    phrase_timing: bool  # a completed transcript exists (phrase captions)
    text_overlays: bool  # captions and the hook can be drawn on this server
    visuals: bool  # visual elements can be drawn on this server


@dataclass(frozen=True)
class VisualOption:
    handle: str
    kind: str  # image / video
    name: str
    description: str
    tags: tuple[str, ...]
    orientation: str  # landscape / portrait / square
    duration: float | None = None  # videos only


@dataclass(frozen=True)
class BrollOption:
    """A validated B-roll suggestion and the project assets that match it (strongest first)."""

    handle: str
    start: float
    end: float
    query: str
    reason: str
    matches: tuple[str, ...]  # visual handles
    # The matches whose tags, name or description cover (nearly) the whole query.
    strong_matches: tuple[str, ...] = ()


@dataclass(frozen=True)
class AudioOption:
    handle: str
    name: str
    duration: float
    transition: bool = False  # sound effects: the name says it is a transition sound


@dataclass(frozen=True)
class AutoEditContext:
    clip_duration: float
    lines: tuple[TimedLine, ...]
    capabilities: Capabilities
    recipe: dict[str, Any]  # Recipe.summary(): bounds only
    source_orientation: str  # landscape / portrait / square
    title: str | None = None
    candidate_hook: str | None = None
    broll: tuple[BrollOption, ...] = ()
    visual_assets: tuple[VisualOption, ...] = ()
    music: AudioOption | None = None  # only a track the creator explicitly chose
    sound_effects: tuple[AudioOption, ...] = ()
    # Server-side only (never part of planner_view()): the completed framing analysis and
    # word-timing track a plan may use, and every handle's real id.
    reframe_analysis_id: str | None = None
    caption_track_id: str | None = None
    visual_ids: dict[str, str] = field(default_factory=dict)
    suggestion_ids: dict[str, str] = field(default_factory=dict)
    audio_ids: dict[str, str] = field(default_factory=dict)

    @property
    def transcript(self) -> str:
        return " ".join(line.text for line in self.lines)

    def planner_view(self) -> dict[str, Any]:
        """Exactly what a planner may see: facts and handles, no ids, keys or paths."""
        caps = self.capabilities
        return {
            "clip": {
                "duration_seconds": round(self.clip_duration, 2),
                "title": self.title,
                "candidate_hook": self.candidate_hook,
                "source_orientation": self.source_orientation,
            },
            "recipe": self.recipe,
            "available": {
                "smart_reframe": caps.smart_reframe,
                "reframe_confidence": caps.reframe_confidence,
                "word_synced_captions": caps.word_timing,
                "phrase_captions": caps.phrase_timing,
                "hook_and_captions": caps.text_overlays,
                "visuals": caps.visuals,
                "music": self.music.handle if self.music else None,
                "transition_sounds": [s.handle for s in self.sound_effects if s.transition],
            },
            "transcript": [
                {"start": round(line.start, 1), "end": round(line.end, 1), "text": line.text}
                for line in self.lines
            ],
            "broll_suggestions": [
                {
                    "handle": option.handle,
                    "start": round(option.start, 2),
                    "end": round(option.end, 2),
                    "query": option.query,
                    "reason": option.reason,
                    "matching_assets": list(option.matches),
                    "strong_matches": list(option.strong_matches),
                }
                for option in self.broll
            ],
            "visual_assets": [
                {
                    "handle": asset.handle,
                    "kind": asset.kind,
                    "name": asset.name,
                    "description": asset.description,
                    "tags": list(asset.tags),
                    "orientation": asset.orientation,
                    **({"duration_seconds": round(asset.duration, 1)} if asset.duration else {}),
                }
                for asset in self.visual_assets
            ],
        }


def orientation(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "landscape"
    ratio = width / height
    if ratio > 1.1:
        return "landscape"
    if ratio < 0.9:
        return "portrait"
    return "square"


# --- proposal (the JSON a planner must return) ---------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LayoutChoice(_Strict):
    mode: Literal["smart_reframe", "blur_background", "center_crop", "fit"] = Field(
        description="Framing; smart_reframe only when available"
    )


class CaptionChoice(_Strict):
    enabled: bool
    preset: Literal["focus", "punch", "minimal", "boxed"] = Field(
        description="One of the recipe's caption presets"
    )
    position: Literal["top", "center", "bottom"] = Field(
        description="One of the recipe's caption positions"
    )


class HookChoice(_Strict):
    enabled: bool
    text: str = Field(
        max_length=RAW_HOOK_MAX_CHARS,
        description="Short opening line using the speaker's own words or the candidate hook",
    )
    style: Literal["headline", "boxed", "minimal"]
    duration_seconds: float = Field(ge=0, le=10)


class VisualChoice(_Strict):
    suggestion: str = Field(description="A broll_suggestions handle, e.g. suggestion_1")
    asset: str = Field(description="One of that suggestion's matching_assets handles")
    mode: Literal["cutaway", "pip"]


class AudioChoice(_Strict):
    use_music: bool = Field(description="Only when a music handle is available")
    music_level: Literal["quiet", "low", "medium"]
    ducking: Literal["light", "medium", "strong"]
    transition_sounds: bool = Field(description="Only when transition sounds are available")


class Explanations(_Strict):
    layout: str = Field(max_length=EXPLANATION_MAX_CHARS)
    captions: str = Field(max_length=EXPLANATION_MAX_CHARS)
    hook: str = Field(max_length=EXPLANATION_MAX_CHARS)
    visuals: str = Field(max_length=EXPLANATION_MAX_CHARS)
    audio: str = Field(max_length=EXPLANATION_MAX_CHARS)


class AutoEditProposal(_Strict):
    layout: LayoutChoice
    captions: CaptionChoice
    hook: HookChoice
    visuals: list[VisualChoice] = Field(max_length=MAX_PROPOSED_VISUALS)
    audio: AudioChoice
    explanations: Explanations


def _inline(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``$ref`` into ``$defs`` (some structured-output engines do not follow refs)."""
    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return resolve(copy.deepcopy(definitions[name]))
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def proposal_json_schema() -> dict[str, Any]:
    return _inline(AutoEditProposal.model_json_schema())


def parse_proposal(data: Any, *, provider: str) -> AutoEditProposal:
    """Decoded JSON → proposal, or PlannerOutputError naming only how many problems there
    were (never the values — they are untrusted model output)."""
    try:
        return AutoEditProposal.model_validate(data)
    except ValidationError as error:
        raise PlannerOutputError(
            f"{provider} returned a plan that does not match the expected schema "
            f"({error.error_count()} problem(s))"
        ) from error


# --- planners and errors ---------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerResult:
    proposal: AutoEditProposal
    provider: str
    model: str
    attempts: int = 1


@runtime_checkable
class AutoEditPlanner(Protocol):
    name: str
    model: str

    def plan(self, context: AutoEditContext) -> PlannerResult: ...


class PlannerError(Exception):
    """A planner failed. ``code`` is stable; ``message`` is safe to store and show.

    ``fallback_ok`` says whether the deterministic planner may stand in (the model could not
    answer: unreachable, timed out, malformed) — never for an operator's configuration error.
    """

    def __init__(self, code: str, message: str, *, fallback_ok: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fallback_ok = fallback_ok


class PlannerUnavailableError(PlannerError):
    def __init__(self, message: str, *, code: str = "planner_unavailable") -> None:
        super().__init__(code, message)


class PlannerTimeoutError(PlannerError):
    def __init__(self, message: str) -> None:
        super().__init__("planner_timeout", message)


class PlannerOutputError(PlannerError):
    def __init__(self, message: str) -> None:
        super().__init__("planner_output", message)


class PlannerConfigurationError(PlannerError):
    def __init__(self, message: str, *, code: str = "planner_configuration") -> None:
        super().__init__(code, message, fallback_ok=False)
