"""Deterministic audio signals and measurements for mix tests (generated at test time).

Test signals are sine tones at known frequencies and levels — never product assets: a
"speech" proxy at 1 kHz, "music" at 200/400/600 Hz, short "effect" beeps at 3 kHz. Measuring
a frequency's amplitude in a time window separates the parts of a mix.
"""

import subprocess
from pathlib import Path

import numpy as np

from app.core.config import get_settings

RATE = 48000


def ffmpeg() -> str:
    return get_settings().ffmpeg_path


def tone(path: Path, expression: str, seconds: float, *, rate: int = 48000, mono: bool = True):
    """Render ``aevalsrc`` ``expression`` (amplitude × sin …) to an audio file."""
    codec = {".mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], ".m4a": ["-c:a", "aac"]}.get(
        path.suffix, ["-c:a", "pcm_s16le"]
    )
    subprocess.run(
        [
            ffmpeg(), "-v", "error", "-y", "-f", "lavfi",
            "-i", f"aevalsrc={expression}:s={rate}:d={seconds}",
            "-ac", "1" if mono else "2", *codec, str(path),
        ],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


def decode(path: Path, *, channels: int = 1) -> np.ndarray:
    """Float samples at 48 kHz (interleaved when ``channels`` is 2)."""
    raw = subprocess.run(
        [ffmpeg(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", str(channels),
         "-ar", str(RATE), "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, "<f4")


def window(samples: np.ndarray, start: float, end: float) -> np.ndarray:
    return samples[int(start * RATE) : int(end * RATE)]


def amplitude(samples: np.ndarray, start: float, end: float, frequency: float) -> float:
    """Peak amplitude of one frequency in a window (Hann-windowed DFT bin)."""
    seg = window(samples, start, end)
    spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) * 4 / len(seg)
    freqs = np.fft.rfftfreq(len(seg), 1 / RATE)
    near = np.abs(freqs - frequency) <= 3
    return float(spectrum[near].max())


def dominant(samples: np.ndarray, start: float, end: float) -> float:
    seg = window(samples, start, end)
    spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    return float(np.fft.rfftfreq(len(seg), 1 / RATE)[int(np.argmax(spectrum))])


def rms_db(samples: np.ndarray, start: float, end: float) -> float:
    seg = window(samples, start, end)
    return float(20 * np.log10(np.sqrt(np.mean(np.square(seg))) + 1e-12))


def db(ratio: float) -> float:
    return float(20 * np.log10(max(ratio, 1e-12)))
