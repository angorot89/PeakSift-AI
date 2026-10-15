"""The audio part of an edit: levels, background music, sound-effect cues and normalization.

All values are validated numbers, booleans and allow-listed enums — never filter strings,
paths or URLs — rounded so that slider noise does not create new renders. Gains are in dB
(the canonical unit; the editor may show friendlier labels), times in seconds of the edited
short (clip-local time). Audio assets are referenced by id and re-checked (same project,
right kind, still present) before every render. An audio section that changes nothing
(no music, no effects, original level, no normalization) normalizes to "no audio section",
so it shares the plain render of the same visual settings.
"""

import math
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

AUDIO_MIX_VERSION = "audio_mix_v1"
# PeakSift's internal social-video mix target (see loudness.py): not any platform's spec.
LOUDNESS_PROFILE = "social_v1"

SOURCE_GAIN_DB = (-24.0, 6.0)
MUSIC_GAIN_DB = (-40.0, 0.0)
SFX_GAIN_DB = (-30.0, 6.0)
MAX_FADE_SECONDS = 10.0
MAX_SFX_CUES = 12
GAIN_DECIMALS = 1  # 0.1 dB
TIME_DECIMALS = 2  # 10 ms

DEFAULT_MUSIC_GAIN_DB = -16.0
DEFAULT_SFX_GAIN_DB = -6.0
DEFAULT_FADE_IN_SECONDS = 0.5
DEFAULT_FADE_OUT_SECONDS = 1.0


class DuckingStrength(StrEnum):
    """How far background music dips while the original audio is active."""

    OFF = "off"
    LIGHT = "light"
    MEDIUM = "medium"
    STRONG = "strong"


DEFAULT_DUCKING = DuckingStrength.MEDIUM


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _gain(value: object, bounds: tuple[float, float], name: str) -> float:
    number = _number(value, name)
    low, high = bounds
    if not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g} dB")
    return round(number, GAIN_DECIMALS) + 0.0  # + 0.0 turns -0.0 into 0.0


def _seconds(value: object, name: str, *, maximum: float | None = None) -> float:
    number = _number(value, name)
    if number < 0 or (maximum is not None and number > maximum):
        limit = f" and {maximum:g}" if maximum is not None else ""
        raise ValueError(f"{name} must be between 0{limit} seconds")
    return round(number, TIME_DECIMALS) + 0.0


def _asset_id(value: object, name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an audio asset id") from None


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


@dataclass(frozen=True)
class MusicConfig:
    asset_id: str
    gain_db: float = DEFAULT_MUSIC_GAIN_DB
    # Where playback starts inside the track (checked against the asset's duration later).
    source_start_seconds: float = 0.0
    loop: bool = True
    fade_in_seconds: float = DEFAULT_FADE_IN_SECONDS
    fade_out_seconds: float = DEFAULT_FADE_OUT_SECONDS
    ducking: DuckingStrength = DEFAULT_DUCKING

    @classmethod
    def create(cls, data: dict[str, Any]) -> "MusicConfig":
        if not isinstance(data, dict):
            raise ValueError("music must be an object")
        return cls(
            asset_id=_asset_id(data.get("asset_id"), "music.asset_id"),
            gain_db=_gain(
                data.get("gain_db", DEFAULT_MUSIC_GAIN_DB), MUSIC_GAIN_DB, "Music volume"
            ),
            source_start_seconds=_seconds(data.get("source_start_seconds", 0.0), "Music start"),
            loop=_bool(data.get("loop", True), "loop"),
            fade_in_seconds=_seconds(
                data.get("fade_in_seconds", DEFAULT_FADE_IN_SECONDS), "Fade in",
                maximum=MAX_FADE_SECONDS,
            ),
            fade_out_seconds=_seconds(
                data.get("fade_out_seconds", DEFAULT_FADE_OUT_SECONDS), "Fade out",
                maximum=MAX_FADE_SECONDS,
            ),
            ducking=DuckingStrength(data.get("ducking", DEFAULT_DUCKING)),
        )  # fmt: skip

    def snapshot(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "gain_db": self.gain_db,
            "source_start_seconds": self.source_start_seconds,
            "loop": self.loop,
            "fade_in_seconds": self.fade_in_seconds,
            "fade_out_seconds": self.fade_out_seconds,
            "ducking": self.ducking.value,
        }


@dataclass(frozen=True, order=True)
class SfxCue:
    at_seconds: float  # first, so cues sort by time
    asset_id: str
    gain_db: float = DEFAULT_SFX_GAIN_DB

    @classmethod
    def create(cls, data: dict[str, Any]) -> "SfxCue":
        if not isinstance(data, dict):
            raise ValueError("Each sound effect must be an object")
        return cls(
            at_seconds=_seconds(data.get("at_seconds"), "Sound effect time"),
            asset_id=_asset_id(data.get("asset_id"), "sfx.asset_id"),
            gain_db=_gain(data.get("gain_db", DEFAULT_SFX_GAIN_DB), SFX_GAIN_DB, "Effect volume"),
        )

    def snapshot(self) -> dict[str, Any]:
        return {"asset_id": self.asset_id, "at_seconds": self.at_seconds, "gain_db": self.gain_db}


@dataclass(frozen=True)
class AudioMix:
    source_gain_db: float = 0.0
    normalize: bool = True
    music: MusicConfig | None = None
    sfx: tuple[SfxCue, ...] = field(default_factory=tuple)

    @classmethod
    def create(cls, data: dict[str, Any] | None) -> "AudioMix | None":
        """Validate and normalize; ``None`` when the section changes nothing."""
        if data is None:
            return None
        if not isinstance(data, dict):
            raise ValueError("audio must be an object")
        cues = data.get("sfx") or []
        if not isinstance(cues, list):
            raise ValueError("sfx must be a list")
        if len(cues) > MAX_SFX_CUES:
            raise ValueError(f"An edit can have at most {MAX_SFX_CUES} sound effects")
        music = data.get("music")
        mix = cls(
            source_gain_db=_gain(
                data.get("source_gain_db", 0.0), SOURCE_GAIN_DB, "Original volume"
            ),
            normalize=_bool(data.get("normalize", True), "normalize"),
            music=MusicConfig.create(music) if music is not None else None,
            sfx=tuple(sorted(SfxCue.create(cue) for cue in cues)),
        )
        if mix.music is None and not mix.sfx and mix.source_gain_db == 0 and not mix.normalize:
            return None  # identical to the plain render of the same visual settings
        return mix

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any] | None) -> "AudioMix | None":
        if snapshot is None:
            return None
        if not isinstance(snapshot, dict) or snapshot.get("version") != AUDIO_MIX_VERSION:
            raise ValueError("Unsupported audio configuration version")
        return cls.create({k: v for k, v in snapshot.items() if k not in ("version", "loudness")})

    @property
    def asset_ids(self) -> list[str]:
        ids = [self.music.asset_id] if self.music else []
        return ids + [cue.asset_id for cue in self.sfx]

    def snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "version": AUDIO_MIX_VERSION,
            "source_gain_db": self.source_gain_db,
            "normalize": self.normalize,
            "music": self.music.snapshot() if self.music else None,
            "sfx": [cue.snapshot() for cue in self.sfx],
        }
        if self.normalize:
            snapshot["loudness"] = LOUDNESS_PROFILE
        return snapshot
