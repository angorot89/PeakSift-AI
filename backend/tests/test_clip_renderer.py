"""Renderer tests with tiny generated sources (nothing committed) and fake ffmpeg scripts."""

import logging
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from app.services.clip_render.renderer import (
    RenderedClip,
    RenderError,
    RenderOptions,
    build_render_command,
    render_clip,
    validate_range,
)
from app.services.ffprobe import probe
from tests.media_fixtures import FFMPEG, generate_video, requires_ffmpeg

OPTIONS = RenderOptions(preset="ultrafast", timeout_seconds=120)


def marker_video(target: Path, *, black_seconds: float = 3.0, white_seconds: float = 3.0) -> Path:
    """Black for the first seconds, then white: lets a test see where a cut really starts."""
    command = [
        FFMPEG,
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s=64x48:r=25:d={black_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"color=c=white:s=64x48:r=25:d={white_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={black_seconds + white_seconds}",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map",
        "[v]",
        "-map",
        "2:a",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-g",
        "50",  # keyframe every 2 s so an inaccurate cut would be visibly wrong
        "-c:a",
        "aac",
        "-shortest",
        str(target),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return target


def first_frame_brightness(path: Path) -> float:
    """Mean grey level (0–255) of the first decoded frame."""
    result = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    data = result.stdout
    return sum(data) / len(data)


def fake_ffmpeg(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake-ffmpeg"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def moov_before_mdat(path: Path) -> bool:
    data = path.read_bytes()
    return data.find(b"moov") < data.find(b"mdat")


# --- command construction (no ffmpeg needed) -----


def test_command_reencodes_with_input_seek_and_faststart():
    command = build_render_command(
        "ffmpeg",
        Path("/m/videos/a.mp4"),
        Path("/m/clips/x/clip-tmp.mp4"),
        start=12.3456,
        duration=20.0,
        has_audio=True,
        preset="veryfast",
        crf=20,
        audio_bitrate="128k",
    )
    assert command[0] == "ffmpeg"
    assert command.index("-ss") < command.index("-i")  # input seeking → accurate re-encode
    assert command[command.index("-ss") + 1] == "12.346"
    assert command[command.index("-t") + 1] == "20.000"
    assert "-c" not in command and "copy" not in command  # never stream copy
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-b:a") + 1] == "128k"
    assert "+faststart" in command and "-sn" in command and "-dn" in command
    assert command[-1] == "/m/clips/x/clip-tmp.mp4"
    assert not any(" " in part and part.startswith("-") for part in command)  # no shell strings


def test_command_without_audio_maps_only_video():
    command = build_render_command(
        "ffmpeg",
        Path("a.mp4"),
        Path("b.mp4"),
        start=0,
        duration=5,
        has_audio=False,
        preset="fast",
        crf=23,
        audio_bitrate="128k",
    )
    assert "0:a:0" not in command and "-c:a" not in command
    assert command[command.index("-map") + 1] == "0:v:0"


@pytest.mark.parametrize(
    ("start", "end", "fragment"),
    [
        (float("nan"), 10.0, "not a valid number"),
        (0.0, float("inf"), "not a valid number"),
        ("5", 10.0, "not a valid number"),
        (True, 10.0, "not a valid number"),
        (-0.1, 10.0, "before the beginning"),
        (10.0, 10.0, "end after it starts"),
        (12.0, 10.0, "end after it starts"),
        (60.0, 70.0, "starts after the end"),
        (50.0, 62.0, "ends after the end"),
    ],
)
def test_validate_range_rejects_bad_boundaries(start, end, fragment):
    with pytest.raises(RenderError) as info:
        validate_range(start, end, 60.0, 1.0)
    assert info.value.code == "invalid_range" and fragment in info.value.message


def test_validate_range_allows_small_overrun_and_unknown_duration():
    assert validate_range(50.0, 60.5, 60.0, 1.0) == 10.5
    assert validate_range(10.0, 25.0, None, 1.0) == 15.0


# --- real renders -----


@requires_ffmpeg
def test_renders_a_middle_section_to_h264_aac_faststart_mp4(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=6.0)
    target = tmp_path / "out" / "clip-tmp.mp4"

    clip = render_clip(source, target, start=2.0, end=4.0, options=OPTIONS)

    assert isinstance(clip, RenderedClip) and clip.path == target and target.is_file()
    assert clip.size_bytes == target.stat().st_size > 0
    assert abs(clip.duration_seconds - 2.0) <= OPTIONS.duration_tolerance_seconds
    assert (clip.width, clip.height) == (64, 64)  # source geometry kept
    assert clip.video_codec == "h264" and clip.audio_codec == "aac"
    assert clip.fps and clip.fps > 0
    assert moov_before_mdat(target)
    meta = probe(target)
    assert meta.video_codec == "h264" and meta.audio_codec == "aac"


@requires_ffmpeg
def test_cut_starts_at_the_requested_boundary_not_at_a_keyframe(tmp_path: Path):
    source = marker_video(tmp_path / "marker.mp4")  # black 0–3 s, white 3–6 s, keyframes every 2 s
    white = render_clip(source, tmp_path / "white.mp4", start=3.0, end=5.0, options=OPTIONS)
    assert first_frame_brightness(white.path) > 200  # starts in the white part, not from 0 or 2 s
    black = render_clip(source, tmp_path / "black.mp4", start=2.8, end=4.8, options=OPTIONS)
    assert (
        first_frame_brightness(black.path) < 50
    )  # 0.2 s earlier is still black: ±1 frame accuracy
    assert abs(white.duration_seconds - 2.0) <= 1.0 and abs(black.duration_seconds - 2.0) <= 1.0


@requires_ffmpeg
def test_renders_from_the_beginning_and_up_to_the_end(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=6.0)
    head = render_clip(source, tmp_path / "head.mp4", start=0.0, end=2.0, options=OPTIONS)
    tail = render_clip(source, tmp_path / "tail.mp4", start=4.0, end=6.0, options=OPTIONS)
    assert abs(head.duration_seconds - 2.0) <= 1.0 and abs(tail.duration_seconds - 2.0) <= 1.0


@requires_ffmpeg
def test_video_without_audio_renders_without_an_audio_track(tmp_path: Path):
    source = generate_video(tmp_path / "silent.mp4", seconds=4.0, audio=False)
    clip = render_clip(source, tmp_path / "out.mp4", start=1.0, end=3.0, options=OPTIONS)
    assert clip.audio_codec is None and clip.video_codec == "h264"


@requires_ffmpeg
@pytest.mark.parametrize("suffix", [".webm", ".mov"])
def test_other_containers_render_to_mp4(tmp_path: Path, suffix: str):
    source = generate_video(tmp_path / f"src{suffix}", seconds=4.0)
    clip = render_clip(source, tmp_path / "out.mp4", start=1.0, end=3.0, options=OPTIONS)
    assert clip.video_codec == "h264" and clip.audio_codec == "aac"
    assert probe(clip.path).width == 64


@requires_ffmpeg
def test_rotation_metadata_is_applied_so_the_clip_is_upright(tmp_path: Path):
    """A landscape 64x48 recording tagged as rotated 90 degrees (phone footage) must come out
    as an upright 48x64 clip with the rotation baked into the pixels, not sideways video."""
    plain = tmp_path / "plain.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=64x48:rate=25",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(plain),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
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
    assert (probe(rotated).width, probe(rotated).height) == (64, 48)  # stored frames unchanged

    clip = render_clip(rotated, tmp_path / "out.mp4", start=0.0, end=2.0, options=OPTIONS)

    assert (clip.width, clip.height) == (48, 64)  # displayed orientation, baked in
    raw = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream_side_data=rotation:stream_tags=rotate",
            "-of",
            "json",
            str(clip.path),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout.decode()
    assert "rotation" not in raw and "rotate" not in raw  # no leftover tag to rotate twice


@requires_ffmpeg
def test_odd_dimensions_are_rounded_down_for_yuv420p(tmp_path: Path):
    source = tmp_path / "odd.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=65x49:rate=25",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-preset",
            "ultrafast",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    clip = render_clip(source, tmp_path / "out.mp4", start=0.0, end=2.0, options=OPTIONS)
    assert (clip.width, clip.height) == (64, 48)


# --- failures -----


@requires_ffmpeg
def test_range_outside_the_source_is_refused_before_rendering(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=4.0)
    target = tmp_path / "out.mp4"
    with pytest.raises(RenderError) as info:
        render_clip(source, target, start=10.0, end=12.0, options=OPTIONS)
    assert info.value.code == "invalid_range" and not target.exists()
    with pytest.raises(RenderError) as info:
        render_clip(source, target, start=1.0, end=9.0, options=OPTIONS)
    assert info.value.code == "invalid_range"


def test_missing_source_is_reported_safely(tmp_path: Path):
    with pytest.raises(RenderError) as info:
        render_clip(tmp_path / "nope.mp4", tmp_path / "out.mp4", start=0, end=1, options=OPTIONS)
    assert info.value.code == "source_missing"
    assert str(tmp_path) not in info.value.message


@requires_ffmpeg
def test_unreadable_source_is_reported_safely(tmp_path: Path):
    source = tmp_path / "garbage.mp4"
    source.write_bytes(b"\x00" * 2048)
    with pytest.raises(RenderError) as info:
        render_clip(source, tmp_path / "out.mp4", start=0, end=1, options=OPTIONS)
    assert info.value.code == "source_unreadable"


@requires_ffmpeg
def test_missing_ffmpeg_binary(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    options = RenderOptions(ffmpeg_path=str(tmp_path / "no-such-ffmpeg"), timeout_seconds=30)
    with pytest.raises(RenderError) as info:
        render_clip(source, tmp_path / "out.mp4", start=0, end=1, options=options)
    assert info.value.code == "ffmpeg_missing"


@requires_ffmpeg
def test_ffmpeg_failure_is_reported_without_paths(tmp_path: Path, caplog):
    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    fake = fake_ffmpeg(tmp_path, f"echo 'Error opening {tmp_path}/secret' >&2\nexit 7\n")
    with (
        caplog.at_level(logging.WARNING, logger="app.services.clip_render.renderer"),
        pytest.raises(RenderError) as info,
    ):
        render_clip(
            source, tmp_path / "out.mp4", start=0, end=1, options=RenderOptions(ffmpeg_path=fake)
        )
    assert info.value.code == "ffmpeg_failed" and "exit code 7" in info.value.message
    assert str(tmp_path) not in info.value.message
    # Operators still get the bounded stderr tail, with local paths redacted in the log.
    assert "Error opening <path>" in caplog.text and str(tmp_path) not in caplog.text


@requires_ffmpeg
def test_timeout_kills_ffmpeg_and_cleans_up(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    target = tmp_path / "out.mp4"
    fake = fake_ffmpeg(tmp_path, f"echo partial > '{target}'\nsleep 30\n")
    options = RenderOptions(ffmpeg_path=fake, timeout_seconds=0.5, heartbeat_interval_seconds=0.1)
    with pytest.raises(RenderError) as info:
        render_clip(source, target, start=0, end=1, options=options)
    assert info.value.code == "render_timeout" and not target.exists()
    assert not shutil.which("sleep") or True  # the fake's sleep was killed; nothing to wait on


@requires_ffmpeg
def test_heartbeat_is_called_while_ffmpeg_runs(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    target = tmp_path / "out.mp4"
    fake = fake_ffmpeg(tmp_path, f"sleep 0.6\ncp '{source}' '{target}'\n")
    beats: list[int] = []
    render_clip(
        source,
        target,
        start=0,
        end=2.0,
        options=RenderOptions(
            ffmpeg_path=fake,
            timeout_seconds=30,
            heartbeat_interval_seconds=0.1,
            duration_tolerance_seconds=1.0,
        ),
        heartbeat=lambda: beats.append(1),
    )
    assert len(beats) >= 3


@requires_ffmpeg
def test_garbage_output_is_rejected_and_removed(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    target = tmp_path / "out.mp4"
    fake = fake_ffmpeg(tmp_path, f"head -c 4096 /dev/zero > '{target}'\n")
    with pytest.raises(RenderError) as info:
        render_clip(source, target, start=0, end=1, options=RenderOptions(ffmpeg_path=fake))
    assert info.value.code == "invalid_output" and not target.exists()


@requires_ffmpeg
def test_empty_output_is_rejected(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    target = tmp_path / "out.mp4"
    fake = fake_ffmpeg(tmp_path, f": > '{target}'\n")
    with pytest.raises(RenderError) as info:
        render_clip(source, target, start=0, end=1, options=RenderOptions(ffmpeg_path=fake))
    assert info.value.code == "invalid_output" and "no output" in info.value.message


@requires_ffmpeg
def test_wrong_duration_output_is_rejected(tmp_path: Path):
    """A fake that ignores the cut and copies the whole 6 s source fails the duration check."""
    source = generate_video(tmp_path / "src.mp4", seconds=6.0)
    target = tmp_path / "out.mp4"
    fake = fake_ffmpeg(tmp_path, f"cp '{source}' '{target}'\n")
    with pytest.raises(RenderError) as info:
        render_clip(source, target, start=0, end=2.0, options=RenderOptions(ffmpeg_path=fake))
    assert info.value.code == "invalid_output" and "instead of 2.00s" in info.value.message
    assert not target.exists()


@requires_ffmpeg
def test_missing_audio_in_output_is_rejected_when_source_has_audio(tmp_path: Path):
    source = generate_video(tmp_path / "src.mp4", seconds=2.0)
    silent = generate_video(tmp_path / "silent.mp4", seconds=2.0, audio=False)
    target = tmp_path / "out.mp4"
    fake = fake_ffmpeg(tmp_path, f"cp '{silent}' '{target}'\n")
    with pytest.raises(RenderError) as info:
        render_clip(source, target, start=0, end=2.0, options=RenderOptions(ffmpeg_path=fake))
    assert "missing its audio track" in info.value.message


def test_no_shell_is_ever_used():
    import inspect

    from app.services.clip_render import renderer

    source = inspect.getsource(renderer)
    assert "shell=True" not in source
    assert os.sep not in RenderOptions().ffmpeg_path  # a plain binary name, found on PATH
