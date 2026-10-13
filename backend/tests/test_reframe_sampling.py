"""Frame sampling with real FFmpeg on tiny generated sources (nothing committed)."""

import subprocess
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.reframe.sampling import (
    SampledFrame,
    SamplingError,
    SourceGeometry,
    analysis_size,
    expected_samples,
    probe_geometry,
    sample_frames,
)
from tests.media_fixtures import FFMPEG, requires_ffmpeg

S = get_settings()


def ramp_video(target: Path, *, size=(640, 360), seconds=4.0, fps=25, audio=False, rate="") -> Path:
    """Grey level grows with time (40 per second) so a frame's mean reveals its timestamp."""
    command = [
        FFMPEG,
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={size[0]}x{size[1]}:r={fps}:d={seconds}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    command += [
        "-vf",
        "geq=lum='min(250,40*T)':cb=128:cr=128",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
    ]
    if rate:
        command += ["-fps_mode", "vfr", "-vf", rate]
    if audio:
        command += ["-c:a", "aac", "-shortest"]
    command.append(str(target))
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return target


def run(path: Path, *, fps=2.0, width=320, timeout=60.0) -> list[SampledFrame]:
    geometry = probe_geometry(path, ffprobe_path=S.ffprobe_path)
    return list(
        sample_frames(
            path,
            geometry,
            ffmpeg_path=S.ffmpeg_path,
            sample_fps=fps,
            analysis_width=width,
            timeout_seconds=timeout,
        )
    )


def mean(frame: SampledFrame) -> float:
    return sum(frame.rgb[::3]) / (frame.width * frame.height)


@requires_ffmpeg
def test_landscape_count_size_and_timestamps(tmp_path: Path):
    frames = run(ramp_video(tmp_path / "l.mp4"))
    assert len(frames) == expected_samples(4.0, 2.0) == 8
    assert [f.timestamp for f in frames] == [i * 0.5 for i in range(8)]
    assert all((f.width, f.height, len(f.rgb)) == (320, 180, 320 * 180 * 3) for f in frames)


def frame_at(path: Path, t: float) -> float:
    """Mean grey of the picture FFmpeg shows at exactly ``t`` (same scaling), for comparison."""
    raw = subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:180:flags=area,format=rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout
    return sum(raw[::3]) / (320 * 180)


@requires_ffmpeg
def test_timestamps_align_with_clip_local_time(tmp_path: Path):
    """Each sample shows the picture at its timestamp: same content as a direct seek to t
    (within one source frame, ~2 grey levels), and brightness rises steadily with time."""
    source = ramp_video(tmp_path / "ramp.mp4")
    frames = run(source, fps=2.0)
    for frame in frames:
        assert abs(mean(frame) - frame_at(source, frame.timestamp)) <= 3, frame.timestamp
    means = [mean(f) for f in frames]
    assert all(b - a > 15 for a, b in zip(means[1:], means[2:], strict=False))


@requires_ffmpeg
@pytest.mark.parametrize(("size", "expected"), [((360, 640), (320, 568)), ((480, 480), (320, 320))])
def test_portrait_and_square_keep_their_aspect(tmp_path: Path, size, expected):
    frames = run(ramp_video(tmp_path / "v.mp4", size=size, seconds=2))
    assert {(f.width, f.height) for f in frames} == {expected}


@requires_ffmpeg
def test_small_sources_are_never_upscaled(tmp_path: Path):
    frames = run(ramp_video(tmp_path / "small.mp4", size=(160, 90), seconds=1), width=640)
    assert {(f.width, f.height) for f in frames} == {(160, 90)}


@requires_ffmpeg
def test_rotation_metadata_gives_display_oriented_frames(tmp_path: Path):
    plain = ramp_video(tmp_path / "plain.mp4", size=(640, 360), seconds=2)
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
    geometry = probe_geometry(rotated, ffprobe_path=S.ffprobe_path)
    assert (geometry.width, geometry.height) == (360, 640)
    frames = run(rotated)
    assert {(f.width, f.height) for f in frames} == {(320, 568)}


@requires_ffmpeg
def test_audio_and_variable_frame_rate_do_not_matter(tmp_path: Path):
    with_audio = run(ramp_video(tmp_path / "a.mp4", seconds=3, audio=True))
    assert len(with_audio) == 6
    vfr = run(
        ramp_video(tmp_path / "vfr.mp4", seconds=3, rate=r"select='lt(n\,10)+not(mod(n\,4))'")
    )
    assert len(vfr) == 6 and [f.timestamp for f in vfr] == [i * 0.5 for i in range(6)]


@requires_ffmpeg
def test_short_clip_gives_at_least_one_frame(tmp_path: Path):
    frames = run(ramp_video(tmp_path / "s.mp4", seconds=0.3))
    assert len(frames) == 1 and frames[0].timestamp == 0


def test_analysis_size_math():
    assert analysis_size(SourceGeometry(3840, 2160, 10), 640) == (640, 360)
    assert analysis_size(SourceGeometry(1920, 1080, 10), 640) == (640, 360)
    assert analysis_size(SourceGeometry(1081, 1921, 10), 640) == (640, 1136)
    assert analysis_size(SourceGeometry(100, 50, 10), 640) == (100, 50)
    assert expected_samples(30, 2) == 60 and expected_samples(0.1, 2) == 1


def test_missing_clip_is_reported(tmp_path: Path):
    with pytest.raises(SamplingError) as info:
        list(
            sample_frames(
                tmp_path / "gone.mp4",
                SourceGeometry(640, 360, 1),
                ffmpeg_path=S.ffmpeg_path,
                sample_fps=2,
                analysis_width=320,
                timeout_seconds=10,
            )
        )
    assert info.value.code == "source_missing" and str(tmp_path) not in info.value.message


@requires_ffmpeg
def test_corrupt_source_is_reported_safely(tmp_path: Path):
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 40)
    with pytest.raises(SamplingError) as info:
        probe_geometry(corrupt, ffprobe_path=S.ffprobe_path)
    assert info.value.code == "source_unreadable" and str(tmp_path) not in info.value.message
    with pytest.raises(SamplingError) as info:
        list(
            sample_frames(
                corrupt,
                SourceGeometry(640, 360, 1),
                ffmpeg_path=S.ffmpeg_path,
                sample_fps=2,
                analysis_width=320,
                timeout_seconds=10,
            )
        )
    assert info.value.code == "sampling_failed"


def test_hung_ffmpeg_times_out_and_is_killed(tmp_path: Path):
    source = tmp_path / "x.mp4"
    source.write_bytes(b"x")
    fake = tmp_path / "ffmpeg-hangs"
    pidfile = tmp_path / "pid"
    fake.write_text(f"#!/bin/sh\necho $$ > {pidfile}\nexec sleep 30\n")
    fake.chmod(0o755)
    with pytest.raises(SamplingError) as info:
        list(
            sample_frames(
                source,
                SourceGeometry(64, 36, 1),
                ffmpeg_path=str(fake),
                sample_fps=2,
                analysis_width=64,
                timeout_seconds=1,
            )
        )
    assert info.value.code == "sampling_timeout"
    pid = int(pidfile.read_text())
    assert subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode != 0  # gone


@requires_ffmpeg
def test_stopping_early_kills_ffmpeg_and_leaves_no_files(tmp_path: Path):
    source = ramp_video(tmp_path / "long.mp4", seconds=6)
    before = sorted(p.name for p in tmp_path.iterdir())
    geometry = probe_geometry(source, ffprobe_path=S.ffprobe_path)
    frames = sample_frames(
        source,
        geometry,
        ffmpeg_path=S.ffmpeg_path,
        sample_fps=2,
        analysis_width=320,
        timeout_seconds=60,
    )
    first = next(frames)
    frames.close()  # e.g. a detector failure stops the analysis
    assert first.timestamp == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_missing_ffmpeg_and_ffprobe_are_reported(tmp_path: Path):
    source = tmp_path / "x.mp4"
    source.write_bytes(b"x")
    with pytest.raises(SamplingError) as info:
        list(
            sample_frames(
                source,
                SourceGeometry(64, 36, 1),
                ffmpeg_path=str(tmp_path / "nope"),
                sample_fps=2,
                analysis_width=64,
                timeout_seconds=5,
            )
        )
    assert info.value.code == "ffmpeg_missing"
    with pytest.raises(SamplingError) as info:
        probe_geometry(source, ffprobe_path=str(tmp_path / "nope"))
    assert info.value.code == "ffprobe_missing"


def test_invalid_sample_rate_is_refused(tmp_path: Path):
    with pytest.raises(ValueError):
        list(
            sample_frames(
                tmp_path / "x.mp4",
                SourceGeometry(64, 36, 1),
                ffmpeg_path="ffmpeg",
                sample_fps=0,
                analysis_width=64,
                timeout_seconds=5,
            )
        )
