"""Frame-level render quality of visual elements, measured on every decoded frame of the short:
no black or one-frame flashes at boundaries, the B-roll's last frame not dropped, the video
B-roll showing exactly the frame its offset says, fades ramping on time, no distortion, PiP
boxes fully inside the frame, the hook staying visible over a cutaway, and the short's
duration and frame count unchanged.

Fixtures carry their own clocks: the main clip has a white marker moving 8 source pixels per
frame (its position gives the main frame number), and the B-roll video's grey level is 8 × its
frame number (its brightness gives the B-roll frame number)."""

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.core.config import get_settings
from app.services.clip_edit.caption_styles import build_ass_document
from app.services.clip_edit.composition import CAPTIONS_FILENAME, compose_short
from app.services.clip_edit.config import CaptionPosition, CaptionStyle, Layout
from app.services.clip_edit.hook import HookConfig, hook_ass
from app.services.ffprobe import probe
from app.services.visuals.compositor import VisualLayer
from app.services.visuals.config import VisualElement, VisualSize
from app.services.visuals.layout import inset_box
from tests.media_fixtures import requires_ffmpeg, requires_libass
from tests.test_visual_render import OPTIONS

pytestmark = requires_ffmpeg

FPS, SECONDS = 25, 3.0
SMALL_W, SMALL_H = 108, 192  # frames are compared at 1/10 scale
FFMPEG = get_settings().ffmpeg_path


def run(*args: str) -> None:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", *args], check=True, capture_output=True, timeout=120
    )


def marker_clip(path: Path) -> Path:
    """640×360 dark clip with a white bar at x = 8 × frame number (fit layout keeps it whole)."""
    run("-f", "lavfi", "-i", f"color=c=0x202020:s=640x360:r={FPS}:d={SECONDS}",
        "-f", "lavfi", "-i", f"color=c=white:s=8x360:r={FPS}:d={SECONDS}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
        "-filter_complex", f"[0:v][1:v]overlay=x='{8 * FPS}*t':y=0[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "10",
        "-c:a", "aac", "-shortest", str(path))  # fmt: skip
    return path


def counting_broll(path: Path, fps: int = 15, seconds: float = 4.0) -> Path:
    """A grey B-roll whose luma is 16 + 8 × its own frame number (lossless, inside the 16-235
    limited range so no frame clips; frame numbers repeat every 27 frames)."""
    run("-f", "lavfi", "-i", f"color=c=black:s=320x180:r={fps}:d={seconds}",
        "-vf", "geq=lum='16+mod(8*N\\,216)':cb=128:cr=128",
        "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
        str(path))  # fmt: skip
    return path


def layer(path: Path, kind: str = "image", asset_size=(400, 300), alpha=False, **element):
    data = {"asset_id": "00000000-0000-4000-8000-000000000000", "mode": "cutaway",
            "start_seconds": 1.0, "end_seconds": 2.0, **element}  # fmt: skip
    return VisualLayer(VisualElement.create(data), path, kind, alpha, *asset_size)


def frames(path: Path, size=(SMALL_W, SMALL_H), crop: str | None = None) -> np.ndarray:
    """Every frame (optionally a cropped band first), scaled down, as an int16 array."""
    chain = (f"crop={crop}," if crop else "") + f"scale={size[0]}:{size[1]}:flags=area"
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vf", chain, "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True, timeout=120,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, np.uint8).reshape(-1, size[1], size[0], 3).astype(np.int16)


def frame_at(path: Path, t: float, size=(1080, 1920)) -> np.ndarray:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
         "-vf", f"scale={size[0]}:{size[1]}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True, timeout=120,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, np.uint8).reshape(size[1], size[0], 3).astype(np.int16)


# The centre band of the short (fit layout: the source clip spans y 656..1263), at half width.
BAND = "1080:40:0:940"
BAND_SIZE = (540, 20)


def render(tmp_path: Path, layers, *, name="out.mp4", layout=Layout.FIT, captions=False) -> Path:
    source = tmp_path / "main.mp4"
    if not source.exists():
        marker_clip(source)
    out = tmp_path / name
    compose_short(source, out, layout=layout, options=OPTIONS, workspace=tmp_path,
                  captions=captions, visuals=layers)  # fmt: skip
    return out


def marker_frame(band: np.ndarray) -> int | None:
    """The main clip's frame number from the marker's position in the centre band (fit layout:
    source x maps to output x × 1080 / 640; the band is at half width)."""
    row = band.mean(axis=(0, 2))
    bright = np.flatnonzero(row > 180)
    if not bright.size or bright.size > 20:  # no marker, or a bright picture rather than a bar
        return None
    out_x = (bright.mean() + 0.5) * 2
    return int(round((out_x * 640 / 1080 - 4) / 8))


def broll_frame(frame: np.ndarray) -> int:
    """The B-roll frame number (mod 27): its luma was written as 16 + 8 × N in limited range, so
    the decoded RGB grey is (Y - 16) × 255 / 219."""
    luma = frame[40:150, 20:90].mean() * 219 / 255 + 16
    return int(round((luma - 16) / 8))


def test_a_video_cutaway_shows_the_exact_frames_its_offset_says_without_flashes(tmp_path):
    broll = counting_broll(tmp_path / "count.mp4")
    cut = layer(broll, "video", asset_size=(320, 180), start_seconds=1.0, end_seconds=2.0,
                asset_offset_seconds=0.4, fit="fill")  # fmt: skip
    out = render(tmp_path, [cut])
    video = frames(out)
    band = frames(out, size=BAND_SIZE, crop=BAND)
    assert len(video) == len(band) == FPS * SECONDS  # 75 frames: duration and rate unchanged
    meta = probe(out)
    assert abs(meta.duration_seconds - SECONDS) <= 0.05 and round(meta.fps) == FPS
    for index in range(len(video)):
        t = index / FPS
        if 1.0 <= t < 2.0:
            expected = int((0.4 + t - 1.0) * 15 + 1e-6)
            assert abs(broll_frame(video[index]) - expected) <= 1, (
                index,
                broll_frame(video[index]),
                expected,
            )
        else:  # the main picture, at its own frame (no freeze, no jump)
            assert marker_frame(band[index]) == index, (index, marker_frame(band[index]))
    # The boundaries: the last main frame, the first and last B-roll frames, the main again.
    assert marker_frame(band[24]) == 24 and marker_frame(band[25]) is None
    assert marker_frame(band[49]) is None and marker_frame(band[50]) == 50
    assert all(frame.mean() > 20 for frame in video)  # never a black frame


def test_fades_ramp_on_time_in_and_out(tmp_path):
    red = tmp_path / "red.png"
    Image.new("RGB", (400, 300), (255, 0, 0)).save(red)
    out = render(tmp_path, [layer(red, start_seconds=1.0, end_seconds=2.0, fit="fill",
                                  transition="fade", transition_seconds=0.2)])  # fmt: skip
    video = frames(out)
    red_share = [frame[..., 0].mean() / 255 for frame in video]
    ramp_in = red_share[25:31]  # t = 1.00 .. 1.20
    ramp_out = red_share[44:51]  # t = 1.76 .. 2.00
    assert all(b >= a - 0.02 for a, b in zip(ramp_in, ramp_in[1:], strict=False))
    assert all(b <= a + 0.02 for a, b in zip(ramp_out, ramp_out[1:], strict=False))
    # Opacity 0.4 at t = 1.08 (two frames in) and 0.4 at t = 1.92: the expected mix of red.
    expected = lambda alpha: alpha * 1.0 + (1 - alpha) * (video[10][..., 0].mean() / 255)  # noqa: E731
    assert red_share[27] == pytest.approx(expected(0.4), abs=0.08)
    assert red_share[48] == pytest.approx(expected(0.4), abs=0.08)
    assert red_share[35] > 0.95 and all(frame.mean() > 20 for frame in video)


def circle_image(path: Path, size=(400, 300)) -> Path:
    image = Image.new("RGB", size, (20, 40, 160))
    r = min(size) // 2 - 10
    cx, cy = size[0] // 2, size[1] // 2
    ImageDraw.Draw(image).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255))
    image.save(path)
    return path


def white_box(frame: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(frame.mean(axis=2) > 220)
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_nothing_is_stretched(tmp_path):
    circle = circle_image(tmp_path / "circle.png")
    fit = render(
        tmp_path, [layer(circle, start_seconds=0.5, end_seconds=2.5, fit="fit")], name="fit.mp4"
    )
    # Fit: the sharp image spans the full width and y 555..1365 (277..682 at half scale); only
    # that band is measured (the blurred copy behind it is white too).
    x0, y0, x1, y1 = white_box(frame_at(fit, 1.5, size=(540, 960))[280:680])
    assert (x1 - x0) == pytest.approx(y1 - y0, rel=0.04)  # a circle stays a circle
    pip = render(tmp_path, [layer(circle, mode="pip", size="large", position="top_left",
                                  start_seconds=0.5, end_seconds=2.5)], name="pip.mp4")  # fmt: skip
    frame = frame_at(pip, 1.5, size=(540, 960))
    inner = frame[102:326, 54:350]  # inside the large PiP's white frame (half scale)
    ys, xs = np.nonzero(inner.mean(axis=2) > 220)
    circle_w, circle_h = xs.max() - xs.min(), ys.max() - ys.min()
    assert circle_w == pytest.approx(circle_h, rel=0.06)


@pytest.mark.parametrize("position", ["top_left", "top_right", "bottom_left", "bottom_right"])
def test_large_picture_in_picture_stays_inside_the_safe_area(tmp_path, position):
    yellow = tmp_path / "wide.png"
    Image.new("RGB", (1600, 900), (255, 230, 0)).save(yellow)
    out = render(tmp_path, [layer(yellow, mode="pip", size="large", position=position,
                                  start_seconds=0.5, end_seconds=2.5)])  # fmt: skip
    frame = frame_at(out, 1.5)
    ys, xs = np.nonzero((frame[..., 0] > 200) & (frame[..., 2] < 80))  # the yellow picture
    width, _ = inset_box(VisualSize.LARGE)
    assert xs.max() - xs.min() + 1 == pytest.approx(width, abs=4)  # fitted to the box width
    assert xs.min() >= 97 and xs.max() <= 1080 - 97  # inside the side margins
    assert ys.min() >= 192 and ys.max() <= 1920 - 422  # below the top and above the bottom margin


@requires_libass
def test_the_hook_stays_visible_over_a_cutaway(tmp_path):
    config = HookConfig.create(text="WAIT FOR IT", style="headline", position="top", duration=2.5)
    hook = hook_ass(config, font_family=get_settings().caption_font_family)
    (tmp_path / CAPTIONS_FILENAME).write_text(
        build_ass_document([], style=CaptionStyle.BOLD, position=CaptionPosition.BOTTOM,
                           font_family=get_settings().caption_font_family,
                           extra_styles=[hook[0]], extra_events=[hook[1]]),
        encoding="utf-8",
    )  # fmt: skip
    red = tmp_path / "red.png"
    Image.new("RGB", (400, 300), (255, 0, 0)).save(red)
    cut = [layer(red, start_seconds=0.2, end_seconds=2.8, fit="fill")]
    with_hook = frame_at(
        render(tmp_path, cut, name="hook.mp4", captions=True), 1.0, size=(540, 960)
    )
    without = frame_at(render(tmp_path, cut, name="plain.mp4"), 1.0, size=(540, 960))
    changed = np.abs(with_hook - without).sum(axis=2) > 150
    assert changed[:480].sum() > 500  # the hook's text is drawn over the B-roll, top half


def test_a_looping_broll_wraps_to_its_start_like_the_preview(tmp_path):
    """Offset 0.5 s into a 1 s video, looped over 1.8 s: the frame shown is
    (offset + elapsed) mod duration — the rule the editor's preview follows."""
    broll = counting_broll(tmp_path / "short.mp4", fps=15, seconds=1.0)
    looped = layer(broll, "video", asset_size=(320, 180), start_seconds=1.0, end_seconds=2.8,
                   asset_offset_seconds=0.5, loop=True)  # fmt: skip
    out = render(tmp_path, [looped])
    video = frames(out)
    for index in range(25, 70):  # t = 1.00 .. 2.76
        t = index / FPS
        expected = int((((0.5 + t - 1.0) % 1.0) * 15) + 1e-6)
        measured = broll_frame(video[index])
        distance = abs(measured - expected) % 15  # on the loop's 15-frame cycle
        assert min(distance, 15 - distance) <= 1, (index, measured, expected)
    assert len(video) == FPS * SECONDS


@pytest.mark.parametrize("broll_fps", [15, 60])
def test_the_shorts_frame_rate_and_duration_never_follow_the_broll(tmp_path, broll_fps):
    broll = counting_broll(tmp_path / f"b{broll_fps}.mp4", fps=broll_fps, seconds=2.0)
    out = render(tmp_path, [layer(broll, "video", asset_size=(320, 180), start_seconds=0.5,
                                  end_seconds=2.5)], name=f"out{broll_fps}.mp4")  # fmt: skip
    meta = probe(out)
    assert round(meta.fps) == FPS and abs(meta.duration_seconds - SECONDS) <= 0.05
    assert len(frames(out)) == FPS * SECONDS
