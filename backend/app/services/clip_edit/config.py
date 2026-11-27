"""The editing options a user may choose, their normalized snapshot and its fingerprint.

Only allow-listed values exist here — never filter strings, fonts, paths, URLs or FFmpeg
arguments. A configuration is normalized before it is stored or compared, so equivalent
requests (for example captions off with different style choices) get the same fingerprint
and therefore the same edit.
"""

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.services.audio_mix.config import AudioMix
from app.services.clip_edit.cuts import CutsConfig
from app.services.visuals.config import VisualsConfig

if TYPE_CHECKING:
    from app.services.clip_edit.brand import BrandConfig
    from app.services.clip_edit.hook import HookConfig

CONFIG_VERSION = 1

# The canonical V0.6 output: 9:16 at 1080 × 1920.
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
RENDER_PROFILE_VERTICAL_V1 = "vertical_1080x1920_v1"


class AspectRatio(StrEnum):
    VERTICAL = "9:16"


class Layout(StrEnum):
    CENTER_CROP = "center_crop"  # fill the frame, crop the centre
    BLUR_BACKGROUND = "blur_background"  # whole frame over a blurred, filled copy
    FIT = "fit"  # whole frame on a plain dark background
    SMART_REFRAME = "smart_reframe"  # 9:16 crop following a completed face-tracking path
    MANUAL_CROP = "manual_crop"  # fixed 9:16 crop around a focal point the user chose


class CaptionStyle(StrEnum):
    CLEAN = "clean"
    BOLD = "bold"
    CREATOR = "creator"


class DynamicPreset(StrEnum):
    """Word-aware caption presets of the dynamic renderer (``caption_v2``)."""

    FOCUS = "focus"
    PUNCH = "punch"
    MINIMAL = "minimal"
    BOXED = "boxed"
    # Creator styles (V2.0)
    POP = "pop"
    COMIC = "comic"
    BUBBLE = "bubble"
    ONE_WORD = "one_word"
    NEON = "neon"
    UNDERLINE = "underline"
    REVEAL = "reveal"
    HEADLINE = "headline"
    MARKER = "marker"
    BOLD_ARABIC = "bold_arabic"


# Styles that show words as they are spoken need real word timing (never estimated).
WORD_TIMED_PRESETS = frozenset({DynamicPreset.ONE_WORD, DynamicPreset.REVEAL})


class CaptionTiming(StrEnum):
    ALIGNED_WORD = "aligned_word"  # real word timestamps from a completed CaptionTrack
    PHRASE_FALLBACK = "phrase_fallback"  # transcript segment timing; never per-word emphasis


CAPTION_RENDERER_V1 = "caption_v1"  # V0.6 phrase captions (Clean / Bold / Creator)
CAPTION_RENDERER_V2 = "caption_v2"  # V0.8 dynamic word-aware captions


class CaptionPosition(StrEnum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


DEFAULT_CAPTION_STYLE = CaptionStyle.BOLD
DEFAULT_CAPTION_POSITION = CaptionPosition.BOTTOM


FOCUS_DECIMALS = 3  # 0.1 % of the frame: finer slider noise must not create a new render


def _focus(value: float | None) -> float:
    """A focal coordinate in [0, 1], rounded so near-identical choices share one render."""
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Manual crop needs a focal point (x and y between 0 and 1)")
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("The focal point must lie inside the frame (0 to 1)")
    return round(float(value), FOCUS_DECIMALS)


def _brand_from_snapshot(snapshot: dict[str, Any] | None) -> "BrandConfig | None":
    from app.services.clip_edit.brand import BrandConfig

    return BrandConfig.from_snapshot(snapshot)


@dataclass(frozen=True)
class EditConfig:
    """A validated, normalized edit configuration."""

    aspect_ratio: AspectRatio
    layout: Layout
    captions_enabled: bool
    caption_style: CaptionStyle | None
    caption_position: CaptionPosition | None
    # Smart reframe only: the completed ReframeAnalysis whose crop path the render follows.
    reframe_analysis_id: str | None = None
    # Manual crop only: the focal point, as fractions of the display-oriented source frame.
    focus_x: float | None = None
    focus_y: float | None = None
    # The optional opening hook overlay (see hook.py); None = no hook.
    hook: "HookConfig | None" = None
    # Dynamic captions only: how words are timed, and the exact CaptionTrack used (aligned).
    caption_timing: CaptionTiming | None = None
    caption_track_id: str | None = None
    # The optional audio finishing (music, sound effects, levels, normalization); None keeps
    # the clip's own audio exactly as earlier versions rendered it.
    audio: AudioMix | None = None
    # Optional B-roll cutaways, picture-in-picture and image overlays; None draws only the
    # clip itself, exactly as earlier versions did.
    visuals: VisualsConfig | None = None
    # Optional brand identity (logo, caption emphasis, hook accent, appended end card), copied
    # from the creator's brand when the Short was made; None renders exactly as before.
    brand: "BrandConfig | None" = None
    # Optional parts of the clip left out (Tighten: pauses, deleted segments); None renders
    # the whole clip exactly as before.
    cuts: CutsConfig | None = None

    @property
    def caption_renderer(self) -> str | None:
        if not self.captions_enabled:
            return None
        return (
            CAPTION_RENDERER_V2
            if isinstance(self.caption_style, DynamicPreset)
            else CAPTION_RENDERER_V1
        )

    @classmethod
    def create(
        cls,
        *,
        aspect_ratio: str = AspectRatio.VERTICAL,
        layout: str,
        captions_enabled: bool,
        caption_style: str | None = None,
        caption_position: str | None = None,
        reframe_analysis_id: str | uuid.UUID | None = None,
        focus_x: float | None = None,
        focus_y: float | None = None,
        hook_enabled: bool = False,
        hook_text: str | None = None,
        hook_style: str | None = None,
        hook_position: str | None = None,
        hook_duration: float | None = None,
        caption_timing: str | None = None,
        caption_track_id: str | uuid.UUID | None = None,
        audio: dict[str, Any] | AudioMix | None = None,
        visuals: dict[str, Any] | VisualsConfig | None = None,
        brand: "dict[str, Any] | BrandConfig | None" = None,
        cuts: "dict[str, Any] | list | CutsConfig | None" = None,
    ) -> "EditConfig":
        """Validate against the allow-lists (ValueError otherwise) and normalize."""
        from app.services.clip_edit.brand import BrandConfig
        from app.services.clip_edit.hook import HookConfig, HookStyle

        branded = brand if isinstance(brand, BrandConfig) or brand is None else None
        if isinstance(brand, dict):
            branded = BrandConfig.create(brand)

        if not isinstance(hook_enabled, bool):
            raise ValueError("hook_enabled must be a boolean")
        hook = (
            HookConfig.create(
                text=hook_text, style=hook_style, position=hook_position, duration=hook_duration
            )
            if hook_enabled
            else None
        )
        mix = audio if isinstance(audio, AudioMix) else AudioMix.create(audio)
        removed = CutsConfig.create(cuts)
        shown = visuals if isinstance(visuals, VisualsConfig) else VisualsConfig.create(visuals)
        ratio = AspectRatio(aspect_ratio)
        chosen_layout = Layout(layout)
        if not isinstance(captions_enabled, bool):
            raise ValueError("captions_enabled must be a boolean")
        analysis: str | None = None
        if chosen_layout == Layout.SMART_REFRAME:
            if reframe_analysis_id is None:
                raise ValueError("Smart reframe needs a completed framing analysis")
            analysis = str(uuid.UUID(str(reframe_analysis_id)))
        focus = (None, None)
        if chosen_layout == Layout.MANUAL_CROP:
            focus = (_focus(focus_x), _focus(focus_y))
        if branded is not None and (hook is None or hook.style != HookStyle.BOXED):
            branded = branded.without(accent=True)  # only the Boxed hook has a label colour
        if not captions_enabled:
            # Style and position are meaningless without captions: drop them so equivalent
            # requests share one fingerprint (and one render).
            if branded is not None:
                branded = branded.without(emphasis=True)
            return cls(
                ratio, chosen_layout, False, None, None, analysis, *focus, hook, audio=mix,
                visuals=shown, brand=branded, cuts=removed,
            )  # fmt: skip
        style: CaptionStyle | DynamicPreset
        if not caption_style:
            style = DEFAULT_CAPTION_STYLE
        elif caption_style in DynamicPreset.__members__.values():
            style = DynamicPreset(caption_style)
        else:
            style = CaptionStyle(caption_style)
        position = (
            CaptionPosition(caption_position) if caption_position else DEFAULT_CAPTION_POSITION
        )
        if hook is not None and hook.position.value == position.value:
            raise ValueError("The hook and the captions cannot share the same position")
        if branded is not None and not isinstance(style, DynamicPreset):
            branded = branded.without(emphasis=True)  # phrase captions have no spoken word
        timing, track = None, None
        if isinstance(style, DynamicPreset):  # caption_v2: timing (and its track) are explicit
            timing = CaptionTiming(caption_timing) if caption_timing else CaptionTiming.ALIGNED_WORD
            if style in WORD_TIMED_PRESETS and timing != CaptionTiming.ALIGNED_WORD:
                raise ValueError("This caption style needs word timing; generate word sync first")
            if timing == CaptionTiming.ALIGNED_WORD:
                if caption_track_id is None:
                    raise ValueError("Word-synced captions need a completed word timing track")
                track = str(uuid.UUID(str(caption_track_id)))
        return cls(
            ratio, chosen_layout, True, style, position, analysis, *focus, hook, timing, track,
            audio=mix, visuals=shown, brand=branded, cuts=removed,
        )  # fmt: skip

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> "EditConfig":
        if not isinstance(snapshot, dict) or snapshot.get("version") != CONFIG_VERSION:
            raise ValueError("Unsupported edit configuration version")
        captions = snapshot.get("captions") or {}
        hook = snapshot.get("hook")
        return cls.create(
            aspect_ratio=snapshot.get("aspect_ratio", AspectRatio.VERTICAL),
            layout=snapshot.get("layout"),
            captions_enabled=bool(captions.get("enabled", False)),
            caption_style=captions.get("style"),
            caption_position=captions.get("position"),
            reframe_analysis_id=(snapshot.get("reframe") or {}).get("analysis_id"),
            focus_x=(snapshot.get("focus") or {}).get("x"),
            focus_y=(snapshot.get("focus") or {}).get("y"),
            hook_enabled=hook is not None,
            hook_text=(hook or {}).get("text"),
            hook_style=(hook or {}).get("style"),
            hook_position=(hook or {}).get("position"),
            hook_duration=(hook or {}).get("duration"),
            caption_timing=captions.get("timing"),
            caption_track_id=captions.get("track_id"),
            audio=AudioMix.from_snapshot(snapshot.get("audio")),
            visuals=VisualsConfig.from_snapshot(snapshot.get("visuals")),
            brand=_brand_from_snapshot(snapshot.get("brand")),
            cuts=CutsConfig.from_snapshot(snapshot.get("cuts")),
        )

    def snapshot(self) -> dict[str, Any]:
        """The exact parameters a render uses, stored on the edit (never future defaults).

        The ``reframe``, ``focus``, ``hook``, ``audio``, ``visuals``, ``brand`` and ``cuts``
        keys — and the dynamic-caption keys (renderer, timing, track, safe area) — exist only
        when used, so every earlier configuration keeps exactly its previous snapshot and
        fingerprint
        (repeat requests still deduplicate).
        """
        snapshot: dict[str, Any] = {
            "version": CONFIG_VERSION,
            "aspect_ratio": self.aspect_ratio.value,
            "layout": self.layout.value,
            "output": {"width": OUTPUT_WIDTH, "height": OUTPUT_HEIGHT},
            "captions": {
                "enabled": self.captions_enabled,
                "style": self.caption_style.value if self.caption_style else None,
                "position": self.caption_position.value if self.caption_position else None,
            },
        }
        if self.layout == Layout.SMART_REFRAME:
            snapshot["reframe"] = {"analysis_id": self.reframe_analysis_id}
        if self.layout == Layout.MANUAL_CROP:
            snapshot["focus"] = {"x": self.focus_x, "y": self.focus_y}
        if self.hook is not None:
            snapshot["hook"] = self.hook.snapshot()
        if self.caption_renderer == CAPTION_RENDERER_V2:
            from app.services.clip_edit.safe_area import SAFE_AREA_VERSION

            captions = snapshot["captions"]
            captions["renderer"] = CAPTION_RENDERER_V2
            captions["timing"] = self.caption_timing.value
            captions["safe_area"] = SAFE_AREA_VERSION
            if self.caption_track_id is not None:
                captions["track_id"] = self.caption_track_id
        if self.audio is not None:
            snapshot["audio"] = self.audio.snapshot()
        if self.visuals is not None:
            snapshot["visuals"] = self.visuals.snapshot()
        if self.brand is not None:
            snapshot["brand"] = self.brand.snapshot()
        if self.cuts is not None:
            snapshot["cuts"] = self.cuts.snapshot()
        return snapshot

    def output_seconds(self, clip_seconds: float) -> float:
        """How long the Short's own timeline is (before an appended end card)."""
        return self.cuts.output_duration(clip_seconds) if self.cuts else clip_seconds

    def fingerprint(self) -> str:
        """sha256 of the canonical JSON snapshot: equal configurations, equal fingerprints."""
        canonical = json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
