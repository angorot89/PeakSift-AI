"""Drawing a Short's brand with FFmpeg and libass — inside the one existing renderer.

The picture is built in this order (``composition.py``):

    clip → framing → [framed] → visual elements → corner logo → (+ end card) → captions + hook

- **Corner logo**: the logo image is one more input (looped for the Short's length), fitted
  into its square box (``force_original_aspect_ratio=decrease`` — never stretched; RGBA keeps
  transparency) and overlaid in its corner inside the safe area, only when ``logo_plan`` says
  (after a top hook, never under an inset in the same corner). It is drawn under the captions
  and hook, so text always stays on top.
- **End card**: a plain frame in the brand colour lasting ``seconds``, with the logo centred
  if chosen, is *appended* after the clip with ``concat`` — so the Short is exactly that much
  longer, and nothing covers the clip itself. Its brand name and line are ASS events from the
  same subtitle file (escaped like captions), shown only over the card. The audio is padded
  with silence for the card (``apad``): the clip's sound is never repeated or stretched.

Only module-formatted numbers, validated ``#RRGGBB`` colours and allow-listed corners reach the
graph; the logo file is an input (an argument-list path), never part of a filter.
"""

from dataclasses import dataclass
from pathlib import Path

from app.services.branding.colors import normalize_color, text_on
from app.services.clip_edit.brand import (
    CARD_LOGO_CENTER_Y,
    CARD_NAME_Y,
    CARD_TEXT_Y,
    EndCard,
    LogoPlan,
    card_logo_box,
    corner_xy,
    enable_expression,
)
from app.services.clip_edit.caption_metrics import text_width
from app.services.clip_edit.caption_v2 import ass_colour, ass_time, escape_ass_text_v2
from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH

W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
CARD_NAME_SIZE = 84
CARD_TEXT_SIZE = 58
CARD_FADE_MS = 200
CARD_TEXT_WIDTH = 920  # the card's text stays inside the frame and its side margins
CARD_MIN_SIZE = 40


def _fitted(text: str, size: int, *, bold: bool) -> int:
    """The largest size (≤ ``size``) at which ``text`` fits on one line of the card."""
    while size > CARD_MIN_SIZE and text_width(text, bold=bold, size=size) > CARD_TEXT_WIDTH:
        size -= 2
    return size


@dataclass(frozen=True)
class BrandLayers:
    """What the renderer needs for one Short's brand."""

    clip_seconds: float
    logo_path: Path | None = None
    plan: LogoPlan | None = None  # the corner logo (None: not shown)
    end_card: EndCard | None = None

    @property
    def extra_seconds(self) -> float:
        return self.end_card.seconds if self.end_card else 0.0

    @property
    def uses_logo(self) -> bool:
        return self.logo_path is not None and (
            self.plan is not None or bool(self.end_card and self.end_card.show_logo)
        )


def _t(seconds: float) -> str:
    return f"{seconds:.3f}"


def _rate(fps: float) -> str:
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def brand_inputs(layers: BrandLayers, fps: float) -> list[str]:
    """The logo input (looped image for the whole Short), or nothing."""
    if not layers.uses_logo:
        return []
    total = layers.clip_seconds + layers.extra_seconds + 1.0
    return ["-loop", "1", "-framerate", _rate(fps), "-t", _t(total), "-i", str(layers.logo_path)]


def brand_graph(
    layers: BrandLayers, logo_input: int | None, fps: float, base: str
) -> tuple[str, str]:
    """Filtergraph segment drawing the brand over ``base``; returns (graph, output label)."""
    graph: list[str] = []
    current = base
    card_logo = bool(layers.end_card and layers.end_card.show_logo and layers.uses_logo)
    corner = layers.plan is not None and layers.uses_logo
    if logo_input is not None and (corner or card_logo):
        source = f"[{logo_input}:v]format=rgba,setsar=1"
        if corner and card_logo:
            graph.append(f"{source},split=2[lga][lgb]")
        else:
            graph.append(f"{source}[{'lga' if corner else 'lgb'}]")
    if corner:
        plan = layers.plan
        x, y = corner_xy(plan.corner)
        box = plan.box
        graph.append(
            f"[lga]scale={box}:{box}:force_original_aspect_ratio=decrease:force_divisible_by=2[lgc]"
        )
        graph.append(
            f"{current}[lgc]overlay=x={x}:y={y}:enable='{enable_expression(plan)}'"
            f":eof_action=pass:format=auto[brandv]"
        )
        current = "[brandv]"
    if layers.end_card is not None:
        card = layers.end_card
        colour = normalize_color(card.background).replace("#", "0x")
        graph.append(
            f"color=c={colour}:s={W}x{H}:r={_rate(fps)}:d={_t(card.seconds)},"
            f"format=yuv420p,setsar=1[cardbg]"
        )
        card_label = "[cardbg]"
        if card_logo:
            box = card_logo_box()
            centre = round(H * CARD_LOGO_CENTER_Y)
            graph.append(
                f"[lgb]scale={box}:{box}:force_original_aspect_ratio=decrease"
                f":force_divisible_by=2[lgk]"
            )
            graph.append(
                f"[cardbg][lgk]overlay=x=(W-w)/2:y={centre}-h/2:shortest=1:format=auto,"
                f"format=yuv420p[card]"
            )
            card_label = "[card]"
        graph.append(f"{current}format=yuv420p,setsar=1[mainf]")
        graph.append(f"[mainf]{card_label}concat=n=2:v=1:a=0[branded]")
        current = "[branded]"
    return ";".join(graph), current


def end_card_ass(
    card: EndCard, *, name: str, start: float, font_family: str
) -> tuple[list[str], list[str]]:
    """(Style lines, Dialogue lines) for the end card's name and line, over the card only."""
    colour = ass_colour(text_on(normalize_color(card.background)))
    styles = [
        f"Style: CardName,{font_family},{CARD_NAME_SIZE},{colour},{colour},&H00000000,"
        f"&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,60,60,0,-1",
        f"Style: CardText,{font_family},{CARD_TEXT_SIZE},{colour},{colour},&H00000000,"
        f"&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,60,60,0,-1",
    ]
    begin, end = ass_time(start), ass_time(start + card.seconds)
    fade = f"\\fad({CARD_FADE_MS},0)"
    name_size = _fitted(name, CARD_NAME_SIZE, bold=True)
    events = [
        f"Dialogue: 2,{begin},{end},CardName,,0,0,0,,"
        f"{{{fade}\\fs{name_size}\\pos({W // 2},{round(H * CARD_NAME_Y)})}}"
        f"{escape_ass_text_v2(name)}"
    ]
    if card.text:
        text_size = _fitted(card.text, CARD_TEXT_SIZE, bold=False)
        events.append(
            f"Dialogue: 2,{begin},{end},CardText,,0,0,0,,"
            f"{{{fade}\\fs{text_size}\\pos({W // 2},{round(H * CARD_TEXT_Y)})}}"
            f"{escape_ass_text_v2(card.text)}"
        )
    return styles, events
