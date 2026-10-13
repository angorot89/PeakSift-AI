"""Vertical composition with real FFmpeg: dimensions, duration, audio, and actual frame pixels.

Sources are generated at test time (nothing committed). A 16:9 source with red | green |
blue thirds makes the layouts observable: centre crop must keep only the green centre,
blur background must keep all three thirds in the middle band over a blurred backdrop.
"""

import subprocess
from pathlib import Path

import pytest

from app.services.clip_edit.composition import (
    CAPTIONS_FILENAME,
    build_edit_command,
    compose_short,
    layout_filter,
)
from app.services.clip_edit.config import Layout
from app.services.clip_render.renderer import RenderError, RenderOptions
from app.services.ffprobe import probe
from tests.media_fixtures import FFMPEG, requires_ffmpeg

OPTIONS = RenderOptions(preset="ultrafast", timeout_seconds=120)
RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)


def thirds_video(
    target: Path, *, size=(162, 90), seconds=2.0, audio=True, extra: list[str] | None = None
) -> Path:
    w, h = size
    third = w // 3
    command = [FFMPEG, "-v", "error", "-y"]
    for colour in ("0xFF0000", "0x00FF00", "0x0000FF"):
        command += ["-f", "lavfi", "-i", f"color=c={colour}:s={third}x{h}:r=25:d={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += ["-filter_complex", "[0:v][1:v][2:v]hstack=inputs=3[v]", "-map", "[v]"]
    if audio:
        command += ["-map", "3:a", "-c:a", "aac"]
    command += [
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        *(extra or []),
        str(target),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return target


def solid_video(target: Path, size: tuple[int, int], colour: str = "0x00FF00", seconds=2.0) -> Path:
    w, h = size
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={colour}:s={w}x{h}:r=25:d={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return target


def pixel(path: Path, x: int, y: int, t: float = 0.5, box: int = 8) -> tuple[float, float, float]:
    """Average RGB of a small box of the frame at time t."""
    raw = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            str(t),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"crop={box}:{box}:{x}:{y}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout
    n = len(raw) // 3
    return tuple(sum(raw[i::3]) / n for i in range(3))  # type: ignore[return-value]


def close(actual, expected, tolerance=60) -> bool:
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected, strict=True))


# --- filtergraphs and command (no ffmpeg needed) ---------------------------------------------


def test_filtergraphs_come_only_from_constants():
    crop = layout_filter(Layout.CENTER_CROP)
    assert crop == (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[framed]"
    )
    blur = layout_filter(Layout.BLUR_BACKGROUND)
    assert "split=2" in blur and "gblur" in blur and "overlay=(W-w)/2:(H-h)/2" in blur
    assert "force_original_aspect_ratio=decrease" in blur  # foreground is fitted, never stretched
    fit = layout_filter(Layout.FIT)
    assert "pad=1080:1920" in fit and "force_original_aspect_ratio=decrease" in fit
    with pytest.raises(ValueError):
        layout_filter("stretch")  # type: ignore[arg-type]


def test_command_shape_with_and_without_captions():
    base = dict(layout=Layout.CENTER_CROP, preset="veryfast", crf=20, audio_bitrate="128k")
    plain = build_edit_command(
        "ffmpeg", Path("/m/clip.mp4"), Path("/m/out.mp4"), has_audio=True, captions=False, **base
    )
    assert plain[plain.index("-map") + 1] == "[framed]" and "0:a:0" in plain
    assert "subtitles" not in " ".join(plain)
    assert plain[plain.index("-c:v") + 1] == "libx264" and plain[plain.index("-c:a") + 1] == "aac"
    assert "+faststart" in plain and plain[-1] == "/m/out.mp4"

    captioned = build_edit_command(
        "ffmpeg", Path("/m/clip.mp4"), Path("/m/out.mp4"), has_audio=False, captions=True, **base
    )
    graph = captioned[captioned.index("-filter_complex") + 1]
    assert graph.endswith(f";[framed]subtitles=filename={CAPTIONS_FILENAME}[out]")
    assert "/m/" not in graph  # no filesystem path inside the filtergraph
    assert captioned[captioned.index("-map") + 1] == "[out]" and "0:a:0" not in captioned


# --- real renders -----------------------------------------------------------------------------


@requires_ffmpeg
def test_center_crop_fills_9x16_with_the_centre_of_a_landscape_source(tmp_path: Path):
    source = thirds_video(tmp_path / "wide.mp4")
    short = compose_short(source, tmp_path / "out.mp4", layout=Layout.CENTER_CROP, options=OPTIONS)

    assert (short.width, short.height) == (1080, 1920)
    assert short.video_codec == "h264" and short.audio_codec == "aac"
    assert abs(short.duration_seconds - 2.0) <= 0.5
    # Only the green middle third survives a centre crop of 16:9 → 9:16.
    for x, y in ((40, 40), (520, 950), (1030, 1870)):
        assert close(pixel(short.path, x, y), GREEN), (x, y, pixel(short.path, x, y))


@requires_ffmpeg
def test_blur_background_keeps_the_whole_frame_over_a_blurred_backdrop(tmp_path: Path):
    source = thirds_video(tmp_path / "wide.mp4")
    short = compose_short(
        source, tmp_path / "out.mp4", layout=Layout.BLUR_BACKGROUND, options=OPTIONS
    )

    assert (short.width, short.height) == (1080, 1920)
    mid = 960  # the fitted 1080×600 foreground is vertically centred
    assert close(pixel(short.path, 60, mid), RED)  # left third preserved
    assert close(pixel(short.path, 536, mid), GREEN)  # centre preserved
    assert close(pixel(short.path, 1010, mid), BLUE)  # right third preserved
    top = pixel(short.path, 536, 150)
    assert sum(top) > 60  # a real background exists (not black bars)
    assert top[1] > 100  # it is the (blurred, filled) green centre of the same video


@requires_ffmpeg
def test_fit_keeps_the_whole_frame_on_a_dark_background(tmp_path: Path):
    source = thirds_video(tmp_path / "wide.mp4")
    short = compose_short(source, tmp_path / "out.mp4", layout=Layout.FIT, options=OPTIONS)
    assert close(pixel(short.path, 60, 960), RED) and close(pixel(short.path, 1010, 960), BLUE)
    assert close(pixel(short.path, 536, 150), (17, 17, 19), tolerance=12)  # plain background


@requires_ffmpeg
def test_portrait_source_is_not_cropped_away(tmp_path: Path):
    source = solid_video(tmp_path / "tall.mp4", (360, 640), "0x0000FF")
    for layout in (Layout.CENTER_CROP, Layout.BLUR_BACKGROUND):
        short = compose_short(source, tmp_path / f"{layout}.mp4", layout=layout, options=OPTIONS)
        assert (short.width, short.height) == (1080, 1920)
        for x, y in ((40, 40), (1030, 1870), (536, 960)):
            assert close(pixel(short.path, x, y), BLUE), (layout, x, y)  # full frame, edge to edge


@requires_ffmpeg
def test_square_and_odd_sized_sources(tmp_path: Path):
    square = solid_video(tmp_path / "square.mp4", (200, 200), "0xFF0000")
    odd = solid_video(tmp_path / "odd.mp4", (162, 92), "0xFF0000")
    for source in (square, odd):
        for layout in Layout:
            short = compose_short(
                source, tmp_path / f"{source.stem}-{layout}.mp4", layout=layout, options=OPTIONS
            )
            assert (short.width, short.height) == (1080, 1920), (source.name, layout)
            assert close(pixel(short.path, 536, 960), RED)


@requires_ffmpeg
def test_source_without_audio_stays_without_audio(tmp_path: Path):
    source = thirds_video(tmp_path / "silent.mp4", audio=False)
    short = compose_short(
        source, tmp_path / "out.mp4", layout=Layout.BLUR_BACKGROUND, options=OPTIONS
    )
    assert short.audio_codec is None and probe(short.path).audio_codec is None


@requires_ffmpeg
def test_rotated_phone_footage_is_composed_upright(tmp_path: Path):
    """A 162x90 landscape recording tagged as rotated 90 degrees is a portrait 90x162 video
    when displayed. Fitted into 9:16 it must fill (almost) the whole height — if rotation were
    ignored it would be a landscape strip with dark bars above and below."""
    plain = thirds_video(tmp_path / "plain.mp4", audio=False)
    rotated = tmp_path / "rotated.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-display_rotation",
            "90",
            "-i",
            str(plain),
            "-c",
            "copy",
            str(rotated),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    short = compose_short(rotated, tmp_path / "out.mp4", layout=Layout.FIT, options=OPTIONS)
    top = pixel(short.path, 536, 150)
    assert not close(top, (17, 17, 19), tolerance=12)  # video content, not the empty background
    assert (short.width, short.height) == (1080, 1920)


@requires_ffmpeg
def test_captions_flag_requires_the_prepared_caption_file(tmp_path: Path):
    source = thirds_video(tmp_path / "wide.mp4")
    with pytest.raises(RenderError) as info:
        compose_short(
            source,
            tmp_path / "out.mp4",
            layout=Layout.FIT,
            options=OPTIONS,
            workspace=tmp_path,
            captions=True,
        )
    assert info.value.code == "captions_missing"


def test_missing_source_is_reported_safely(tmp_path: Path):
    with pytest.raises(RenderError) as info:
        compose_short(
            tmp_path / "nope.mp4", tmp_path / "out.mp4", layout=Layout.FIT, options=OPTIONS
        )
    assert info.value.code == "source_missing" and str(tmp_path) not in info.value.message


@requires_ffmpeg
def test_wrong_output_size_is_rejected_and_removed(tmp_path: Path):
    """A broken ffmpeg that ignores the layout produces the wrong size: validation refuses it."""
    import stat

    source = thirds_video(tmp_path / "wide.mp4")
    target = tmp_path / "out.mp4"
    fake = tmp_path / "fake-ffmpeg"
    fake.write_text(f"#!/bin/sh\ncp '{source}' '{target}'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(RenderError) as info:
        compose_short(
            source, target, layout=Layout.CENTER_CROP, options=RenderOptions(ffmpeg_path=str(fake))
        )
    assert info.value.code == "invalid_output" and "not 1080x1920" in info.value.message
    assert not target.exists()
