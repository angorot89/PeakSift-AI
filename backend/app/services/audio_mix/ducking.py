"""Automatic music ducking: music dips while the clip's own audio is active.

The control signal is the clip's audio (after its gain) as a whole — overall source energy,
not an isolated voice: PeakSift does no speech separation. FFmpeg's ``sidechaincompress``
compresses the music by that signal. Users choose only a strength; the parameters below are
server-side and were tuned by measurement (see ``tests/test_audio_ducking.py``) with a
speech proxy peaking around -12 dBFS over music at -16 dB:

=========  =========  =====  ======  =======  ==================================
strength   threshold  ratio  attack  release  measured music dip while active
=========  =========  =====  ======  =======  ==================================
light      0.05       2      20 ms   400 ms   about 7 dB
medium     0.03       4      20 ms   500 ms   about 13 dB
strong     0.02       8      20 ms   600 ms   about 19 dB
=========  =========  =====  ======  =======  ==================================

A quieter source ducks the music less (it is energy-based). The release is long enough that
the music does not flutter between syllables and recovers smoothly within about a second of
the source going quiet. Detection is RMS, no make-up gain.
"""

from dataclasses import dataclass

from app.services.audio_mix.config import DuckingStrength


@dataclass(frozen=True)
class DuckingPreset:
    threshold: float  # linear level of the control signal where ducking starts
    ratio: float
    attack_ms: float
    release_ms: float


DUCKING_PRESETS: dict[DuckingStrength, DuckingPreset] = {
    DuckingStrength.LIGHT: DuckingPreset(threshold=0.05, ratio=2, attack_ms=20, release_ms=400),
    DuckingStrength.MEDIUM: DuckingPreset(threshold=0.03, ratio=4, attack_ms=20, release_ms=500),
    DuckingStrength.STRONG: DuckingPreset(threshold=0.02, ratio=8, attack_ms=20, release_ms=600),
}


def ducking_filter(strength: DuckingStrength) -> str | None:
    """The ``sidechaincompress`` options for a strength (constants only), or None for off."""
    preset = DUCKING_PRESETS.get(strength)
    if preset is None:
        return None
    return (
        f"sidechaincompress=threshold={preset.threshold:g}:ratio={preset.ratio:g}"
        f":attack={preset.attack_ms:g}:release={preset.release_ms:g}"
        ":knee=2.82843:detection=rms:makeup=1"
    )
