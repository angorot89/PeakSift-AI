"""Caption presets, positions and the ASS document, plus real burned-in renders checked
against actual frames (the caption region must change while a cue is active, return to
the background afterwards, and sit where the position says)."""

import stat
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.services.clip_edit.caption_styles import (
    POSITIONS,
    PRESETS,
    ass_time,
    build_ass_document,
)
from app.services.clip_edit.captions import WORD_JOINER, Cue, SourceSegment, build_cues
from app.services.clip_edit.composition import (
    CAPTIONS_FILENAME,
    PROBE_SIZE,
    caption_text_renders,
    compose_short,
    ffmpeg_filters,
    require_caption_rendering,
    supports_captions,
)
from app.services.clip_edit.config import CaptionPosition, CaptionStyle, Layout
from app.services.clip_render.renderer import RenderError, RenderOptions
from tests.media_fixtures import FFMPEG, requires_ffmpeg, requires_libass


def options() -> RenderOptions:
    s = get_settings()
    return RenderOptions(
        ffmpeg_path=s.ffmpeg_path,
        ffprobe_path=s.ffprobe_path,
        preset="ultrafast",
        timeout_seconds=180,
    )


def doc(cues, style=CaptionStyle.BOLD, position=CaptionPosition.BOTTOM, font="Noto Sans") -> str:
    return build_ass_document(cues, style=style, position=position, font_family=font)


def style_fields(document: str) -> list[str]:
    """The comma-separated fields of the single ``Style: Caption,...`` line."""
    for line in document.splitlines():
        if line.startswith("Style: Caption,"):
            return line.removeprefix("Style: ").split(",")
    raise AssertionError("no caption style line")


# --- ASS document (no ffmpeg needed) -----


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00:00.00"),
        (4.2, "0:00:04.20"),
        (61.005, "0:01:01.00"),
        (3725.5, "1:02:05.50"),
        (-3, "0:00:00.00"),
    ],
)
def test_ass_time(seconds, expected):
    assert ass_time(seconds) == expected


def test_document_header_targets_the_vertical_canvas():
    text = doc([Cue(1.0, 2.0, "Hello")])
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    assert "ScaledBorderAndShadow: yes" in text and "WrapStyle: 0" in text
    assert "Dialogue: 0,0:00:01.00,0:00:02.00,Caption,,0,0,0,,Hello" in text


@pytest.mark.parametrize("style", list(CaptionStyle))
def test_each_preset_maps_to_a_fixed_style_line(style):
    preset = PRESETS[style]
    fields = style_fields(doc([], style=style))
    assert fields[1] == "Noto Sans" and fields[2] == str(preset.size)
    assert fields[3] == preset.primary and fields[15] == str(preset.border_style)
    assert fields[7] == ("-1" if preset.bold else "0")


@pytest.mark.parametrize("position", list(CaptionPosition))
def test_positions_set_alignment_and_safe_margins(position):
    alignment, margin_v = POSITIONS[position]
    fields = style_fields(doc([], position=position))
    assert fields[18] == str(alignment) and fields[21] == str(margin_v)
    assert int(fields[19]) >= 60 and int(fields[20]) >= 60  # side margins
    if position != CaptionPosition.CENTER:
        assert margin_v >= 200  # never against the edge of the frame


def test_presets_and_positions_are_closed_sets():
    assert set(PRESETS) == set(CaptionStyle) and set(POSITIONS) == set(CaptionPosition)


def test_dialogue_text_is_always_escaped():
    text = doc([Cue(0.5, 1.5, "{\\fs300}huge\\N and C:\\new")])
    line = text.splitlines()[-1]
    assert line.endswith(
        f"\\{{\\{WORD_JOINER}fs300\\}}huge\\{WORD_JOINER}N and C:\\{WORD_JOINER}new"
    )


def test_invalid_cues_are_skipped_and_rounding_never_empties_a_cue():
    text = doc(
        [Cue(2.0, 1.0, "inverted"), Cue(float("nan"), 1.0, "nan"), Cue(1.001, 1.004, "tiny")]
    )
    dialogues = [line for line in text.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 1 and dialogues[0].startswith("Dialogue: 0,0:00:01.00,0:00:01.01,")


@pytest.mark.parametrize("font", ["Noto Sans,Bold", "../../etc/fonts", "Font\nStyle: Evil", ""])
def test_font_family_must_be_a_plain_name(font):
    with pytest.raises(ValueError):
        doc([], font=font)


# --- real renders -----


def plain_source(target: Path, seconds: float = 4.0, audio: bool = True) -> Path:
    command = [
        FFMPEG,
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x203040:s=640x360:r=25:d={seconds}",
    ]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-c:a", "aac"]
    command += [
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-shortest",
        str(target),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return target


def region(path: Path, t: float, y: int, h: int) -> bytes:
    return crop(path, t, 0, y, 1080, h)


def crop(path: Path, t: float, x: int, y: int, w: int, h: int) -> bytes:
    return subprocess.run(
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
            f"crop={w}:{h}:{x}:{y}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def difference(a: bytes, b: bytes) -> float:
    """Percentage of pixels whose grey level differs clearly (> 40) between two crops."""
    changed = sum(1 for x, y in zip(a, b, strict=True) if abs(x - y) > 40)
    return 100 * changed / len(a)


def render(
    tmp_path: Path,
    cues,
    *,
    style=CaptionStyle.BOLD,
    position=CaptionPosition.BOTTOM,
    name="out",
    audio=True,
):
    source = plain_source(tmp_path / f"{name}-src.mp4", audio=audio)
    workspace = tmp_path / f"{name}-ws"
    workspace.mkdir()
    (workspace / CAPTIONS_FILENAME).write_text(
        doc(cues, style=style, position=position), encoding="utf-8"
    )
    return compose_short(
        source,
        workspace / "short.mp4",
        layout=Layout.CENTER_CROP,
        options=options(),
        workspace=workspace,
        captions=True,
    )


BOTTOM_BAND = (1920 - 320 - 140, 140)  # where a bottom caption sits
TOP_BAND = (260, 140)
MIDDLE_BAND = (890, 140)


@requires_ffmpeg
@requires_libass
def test_burned_in_caption_appears_only_while_its_cue_is_active(tmp_path: Path):
    short = render(tmp_path, [Cue(1.0, 2.0, "Hello captions")])

    assert (short.width, short.height) == (1080, 1920)
    assert short.audio_codec == "aac" and abs(short.duration_seconds - 4.0) <= 0.5
    active = region(short.path, 1.5, *BOTTOM_BAND)
    before = region(short.path, 0.5, *BOTTOM_BAND)
    after = region(short.path, 3.0, *BOTTOM_BAND)
    assert difference(active, after) > 1  # text is drawn during the cue
    assert difference(before, after) < 0.05  # and does not persist before or after it
    assert difference(region(short.path, 1.5, *TOP_BAND), region(short.path, 3.0, *TOP_BAND)) < 0.05


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize(
    ("position", "band"),
    [
        (CaptionPosition.TOP, TOP_BAND),
        (CaptionPosition.CENTER, MIDDLE_BAND),
        (CaptionPosition.BOTTOM, BOTTOM_BAND),
    ],
)
def test_caption_is_drawn_at_the_chosen_position(tmp_path: Path, position, band):
    short = render(
        tmp_path, [Cue(0.5, 3.5, "Positioned text")], position=position, name=position.value
    )
    bands = {"top": TOP_BAND, "center": MIDDLE_BAND, "bottom": BOTTOM_BAND}
    for name, other in bands.items():
        changed = difference(region(short.path, 2.0, *other), region(short.path, 3.8, *other)) > 1
        assert changed == (other == band), (position, name)


@requires_ffmpeg
@requires_libass
@pytest.mark.parametrize("style", list(CaptionStyle))
def test_every_preset_renders(tmp_path: Path, style):
    short = render(tmp_path, [Cue(0.5, 2.5, "Preset check")], style=style, name=style.value)
    assert (
        difference(region(short.path, 1.5, *BOTTOM_BAND), region(short.path, 3.5, *BOTTOM_BAND)) > 1
    )


@requires_ffmpeg
@requires_libass
def test_unicode_arabic_french_emoji_and_hostile_text_render(tmp_path: Path):
    cues = [
        Cue(0.2, 1.0, "Bonjour à tous, ça va ? C'est l'été !"),
        Cue(1.0, 2.0, "مرحبا بكم في الفيديو، كيف حالكم؟"),
        Cue(2.0, 2.8, 'Rock & roll — "quotes" 🙂'),
        Cue(2.8, 3.6, "{\\fs400\\c&H0000FF&}\\N\\h C:\\new {x}"),
    ]
    short = render(tmp_path, cues, audio=False)
    assert (short.width, short.height) == (1080, 1920) and short.audio_codec is None
    for t in (0.6, 1.5, 2.4, 3.2):
        assert (
            difference(region(short.path, t, *BOTTOM_BAND), region(short.path, 3.9, *BOTTOM_BAND))
            > 1
        )
    # The hostile override ({\fs400}) must not have blown the text up past the bottom band.
    assert difference(region(short.path, 3.2, *TOP_BAND), region(short.path, 3.9, *TOP_BAND)) < 0.05


@requires_ffmpeg
def test_missing_libass_is_a_clear_failure(tmp_path: Path):
    fake = tmp_path / "ffmpeg-without-libass"
    fake.write_text("#!/bin/sh\necho ' .. scale  V->V  Scale the input video.'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    assert supports_captions(str(fake)) is False
    source = plain_source(tmp_path / "src.mp4")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / CAPTIONS_FILENAME).write_text(doc([Cue(0.5, 1.0, "x")]))
    s = get_settings()
    with pytest.raises(RenderError) as info:
        compose_short(
            source,
            workspace / "short.mp4",
            layout=Layout.FIT,
            options=RenderOptions(ffmpeg_path=str(fake), ffprobe_path=s.ffprobe_path),
            workspace=workspace,
            captions=True,
        )
    assert info.value.code == "captions_unavailable" and "libass" in info.value.message


# --- hardening: unbreakable lines, missing renderer, missing fonts -----

EDGE = 24  # outer columns a caption must never reach (the side margin is 90 px)


def edges(path: Path, t: float, band) -> bytes:
    y, h = band
    return crop(path, t, 0, y, EDGE, h) + crop(path, t, 1080 - EDGE, y, EDGE, h)


@requires_ffmpeg
@requires_libass
def test_long_unspaced_caption_is_split_and_stays_inside_the_frame(tmp_path: Path):
    token = "https://example.com/watch/this/very/long/link/that/never/wraps"
    # Control: drawn as one cue, libass cannot wrap it and it runs off both sides.
    raw = render(tmp_path, [Cue(0.2, 3.6, token)], name="unsplit")
    assert difference(edges(raw.path, 1.0, BOTTOM_BAND), edges(raw.path, 3.9, BOTTOM_BAND)) > 1

    cues = build_cues([SourceSegment(0.0, 3.6, token)], clip_start=0.0, clip_end=4.0)
    assert len(cues) > 1 and "".join(c.text for c in cues) == token
    short = render(tmp_path, cues, name="split")
    background = region(short.path, 3.9, *BOTTOM_BAND)
    for cue in cues:
        t = (cue.start + cue.end) / 2
        assert difference(region(short.path, t, *BOTTOM_BAND), background) > 1  # text drawn
        assert (
            difference(edges(short.path, t, BOTTOM_BAND), edges(short.path, 3.9, BOTTOM_BAND))
            < 0.05
        )


def fake_ffmpeg(path: Path, *, filters: str, frame: str = "") -> str:
    path.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f"  *-filters*) echo '{filters}' ;;\n"
        f"  *) {frame or 'exit 1'} ;;\n"
        "esac\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_missing_ffmpeg_is_not_reported_as_missing_libass(tmp_path: Path):
    missing = str(tmp_path / "not-installed" / "ffmpeg")
    assert ffmpeg_filters(missing) is None and supports_captions(missing) is False
    with pytest.raises(RenderError) as info:
        require_caption_rendering(missing, "Noto Sans")
    assert info.value.code == "ffmpeg_missing" and "libass" not in info.value.message
    assert missing not in info.value.message


def test_caption_renderer_that_draws_nothing_is_refused(tmp_path: Path):
    """libass present, but no usable font: the probe frame stays black."""
    width, height = (int(v) for v in PROBE_SIZE.split("x"))
    fake = fake_ffmpeg(
        tmp_path / "ffmpeg-no-fonts",
        filters=" .. subtitles  V->V  Render text subtitles onto input video using libass.",
        frame=f"head -c {width * height} /dev/zero",
    )
    assert supports_captions(fake) is True
    assert caption_text_renders(fake, "Noto Sans") is False
    with pytest.raises(RenderError) as info:
        require_caption_rendering(fake, "Noto Sans")
    assert info.value.code == "caption_font_unavailable"
    assert "font" in info.value.message and str(tmp_path) not in info.value.message
    assert caption_text_renders(fake, "Noto Sans") is False  # failures are not cached


@requires_ffmpeg
@requires_libass
def test_real_caption_probe_draws_text():
    assert caption_text_renders(get_settings().ffmpeg_path, "Noto Sans") is True


@requires_ffmpeg
@requires_libass
@pytest.mark.skipif(sys.platform != "linux", reason="fontconfig-only check (CI runs Linux)")
def test_a_server_without_any_font_is_detected(tmp_path: Path, monkeypatch):
    conf = tmp_path / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?>\n'
        f"<fontconfig><cachedir>{tmp_path / 'cache'}</cachedir></fontconfig>\n"
    )
    monkeypatch.setenv("FONTCONFIG_FILE", str(conf))
    # A family name of its own, so no earlier successful probe is reused from the cache.
    assert caption_text_renders(get_settings().ffmpeg_path, "No Font Probe") is False
