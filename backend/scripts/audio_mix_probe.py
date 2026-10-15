"""Audio mix probe: the short's audio pipeline, rendered on this FFmpeg and measured.

Generates deterministic test signals (a 1 kHz "speech" proxy that alternates 1.5 s on / 1.5 s
off, a 200 Hz "music" tone, a 3 kHz "effect" beep — test signals, not product assets), then:

- **matrix**: source only, music only (no source), source + music, source + ducked music,
  source + effect, music + effect, everything, mono source, stereo source — each mixed and
  finished; every result must have exactly the short's length;
- **ducking**: the music component must dip by at least 6 dB while the source is active
  (medium; about 10 dB at this source level) and recover to within 1 dB when it is quiet;
- **loudness**: the finished full mix must measure -14 ± 1 LUFS with a true peak of at most
  -1.0 dBTP;
- **short**: the full mix composed into a 1080 x 1920 short must carry AAC stereo 48 kHz
  audio as long as the video.

Used by CI and the acceptance checklist; no network, no model, temporary files only.

    python scripts/audio_mix_probe.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services.audio_mix.config import DuckingStrength, MusicConfig, SfxCue  # noqa: E402
from app.services.audio_mix.loudness import TARGET_I, finish_audio, measure_loudness  # noqa: E402
from app.services.audio_mix.mixer import render_mix  # noqa: E402
from app.services.audio_mix.plan import MixPlanRequest, MusicInput, SfxInput  # noqa: E402
from app.services.clip_edit.composition import compose_short  # noqa: E402
from app.services.clip_edit.config import Layout  # noqa: E402
from app.services.clip_render.pipeline import render_options_from  # noqa: E402
from app.services.ffprobe import probe_audio  # noqa: E402

SECONDS = 9.0
RATE = 48000
SPEECH = "0.2*sin(2*PI*1000*t)*lt(mod(t\\,3)\\,1.5)"


def generate(ffmpeg: str, path: Path, expression: str, seconds: float, *, stereo=False) -> Path:
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-f", "lavfi",
         "-i", f"aevalsrc={expression}:s=44100:d={seconds}",
         "-ac", "2" if stereo else "1", "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


def decode(ffmpeg: str, path: Path) -> np.ndarray:
    raw = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-"],
        check=True, capture_output=True, timeout=60,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, "<f4")


def amplitude(samples: np.ndarray, start: float, end: float, frequency: float) -> float:
    seg = samples[int(start * RATE) : int(end * RATE)]
    spectrum = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) * 4 / len(seg)
    freqs = np.fft.rfftfreq(len(seg), 1 / RATE)
    return float(spectrum[np.abs(freqs - frequency) <= max(3.0, RATE / len(seg))].max())


def main() -> int:
    settings = get_settings()
    options = render_options_from(settings)
    ffmpeg = settings.ffmpeg_path
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="peaksift-audio-probe-") as tmp:
        work = Path(tmp)
        mono = generate(ffmpeg, work / "speech-mono.wav", SPEECH, SECONDS)
        stereo = generate(ffmpeg, work / "speech-stereo.wav", SPEECH, SECONDS, stereo=True)
        track = generate(ffmpeg, work / "music.wav", "0.5*sin(2*PI*200*t)", 20, stereo=True)
        beep = generate(ffmpeg, work / "beep.wav", "0.6*sin(2*PI*3000*t)", 0.25)

        def music(ducking: DuckingStrength) -> MusicInput:
            config = MusicConfig(asset_id="probe", gain_db=-14, fade_in_seconds=0,
                                 fade_out_seconds=0, ducking=ducking)  # fmt: skip
            return MusicInput(track, 20.0, config)

        effect = (SfxInput(beep, 0.25, SfxCue(at_seconds=4.0, asset_id="probe", gain_db=0)),)
        off, medium = DuckingStrength.OFF, DuckingStrength.MEDIUM
        matrix = {
            "source only": MixPlanRequest(SECONDS, mono),
            "music only": MixPlanRequest(SECONDS, None, music=music(off)),
            "source + music": MixPlanRequest(SECONDS, mono, music=music(off)),
            "source + ducked music": MixPlanRequest(SECONDS, mono, music=music(medium)),
            "source + effect": MixPlanRequest(SECONDS, mono, sfx=effect),
            "music + effect": MixPlanRequest(SECONDS, None, music=music(off), sfx=effect),
            "everything": MixPlanRequest(SECONDS, mono, music=music(medium), sfx=effect),
            "stereo source": MixPlanRequest(SECONDS, stereo, music=music(medium)),
        }
        finished: dict[str, Path] = {}
        for name, request in matrix.items():
            slug = name.replace(" ", "-").replace("+", "and")
            mixed = render_mix(request, work / f"{slug}-mix.wav", options)
            final = work / f"{slug}-final.wav"
            finish_audio(mixed, final, normalize=True, options=options)
            samples = decode(ffmpeg, final)
            if len(samples) != int(SECONDS * RATE):
                problems.append(f"{name}: {len(samples) / RATE:.3f}s instead of {SECONDS}s")
            finished[name] = final

        # Ducking: compare the music component with and without ducking, relative to its level.
        plain = decode(ffmpeg, work / "source-and-music-mix.wav")
        ducked = decode(ffmpeg, work / "source-and-ducked-music-mix.wav")
        dip = 20 * np.log10(amplitude(ducked, 0.5, 1.4, 200) / amplitude(plain, 0.5, 1.4, 200))
        recovered = 20 * np.log10(
            amplitude(ducked, 2.4, 2.95, 200) / amplitude(plain, 2.4, 2.95, 200)
        )
        if dip > -6:
            problems.append(f"ducking dipped only {dip:.1f} dB")
        if abs(recovered) > 1:
            problems.append(f"ducking did not recover ({recovered:.1f} dB)")

        loudness = measure_loudness(finished["everything"], options)
        if loudness is None or abs(loudness.integrated - TARGET_I) > 1 or loudness.true_peak > -1.0:
            problems.append(f"loudness off target: {loudness}")

        # The full mix composed into a short.
        source_clip = work / "clip.mp4"
        subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=c=0x203040:s=640x360:r=25:d={SECONDS}", "-i", str(mono),
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-shortest", str(source_clip)],
            check=True, capture_output=True, timeout=120,
        )  # fmt: skip
        short = compose_short(
            source_clip, work / "short.mp4", layout=Layout.CENTER_CROP, options=options,
            audio=finished["everything"],
        )  # fmt: skip
        info = probe_audio(short.path, ffprobe_path=settings.ffprobe_path)
        if (short.audio_codec, info.channels, info.sample_rate) != ("aac", 2, RATE):
            problems.append(
                f"short audio is {short.audio_codec} {info.channels}ch {info.sample_rate} Hz"
            )
        if abs((info.duration_seconds or 0) - short.duration_seconds) > 0.25:
            problems.append("short audio and video lengths differ")

    if problems:
        print("audio mix probe FAILED: " + "; ".join(problems))
        return 1
    print(
        f"audio mix probe: {len(matrix)} mixes at exact length, ducking {dip:.1f} dB "
        f"(recovered {recovered:+.1f} dB), loudness {loudness.integrated:.1f} LUFS / "
        f"{loudness.true_peak:.1f} dBTP, short AAC stereo 48 kHz"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
