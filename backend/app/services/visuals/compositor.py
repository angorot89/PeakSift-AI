"""Drawing visual elements into the short with FFmpeg: inputs and a filtergraph segment.

The edit's picture is built in this order (``composition.py``):

    clip → layout / smart reframe → [framed] → visual elements → [visual] → captions + hook

so captions and the hook are burned in *after* every cutaway and inset — they stay on top and
readable — and the main video keeps driving the timeline: each element is a layer overlaid
only during its interval (``enable``) and released when it ends (``eof_action=pass``), so the
short's duration and frame rate are the clip's, whatever the assets are.

Each element is its own input, trimmed at the input (``-ss`` / ``-t``), so nothing outside
its interval is decoded:

- an **image** is looped at the short's frame rate for the element's duration;
- a **video** starts at the element's video offset and lasts the element's duration
  (``-stream_loop -1`` only when looping was chosen); its sound is never decoded (``-an``) —
  B-roll is always silent, and the edit's audio stays exactly as configured.

Per layer: pixel aspect ratio is squared, the frame rate is the short's, transparent images
are flattened onto the background for cutaways and picture-in-picture (overlays keep their
transparency), the geometry is fill/fit (cutaway) or a bounded box (inset) — never stretched —
and the layer is shifted onto the short's timeline before the optional alpha fade. Only
module-formatted numbers and allow-listed values reach the graph; asset files are inputs
(argument-list paths), never part of a filter.
"""

from dataclasses import dataclass
from pathlib import Path

from app.services.clip_edit.config import OUTPUT_HEIGHT, OUTPUT_WIDTH
from app.services.visuals.config import VisualElement, VisualFit, VisualMode
from app.services.visuals.layout import BACKGROUND, PIP_BORDER, inset_box, inset_position
from app.services.visuals.transitions import fade_filter

W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
BLUR_DIVISOR = 4
BLUR_SIGMA = 12


@dataclass(frozen=True)
class VisualLayer:
    """One element ready to render: its validated configuration and its local file."""

    element: VisualElement
    path: Path
    kind: str  # "image" | "video"
    has_alpha: bool = False
    width: int = 0  # display size of the asset (needed to flatten transparent images)
    height: int = 0
    codec: str | None = None  # videos: the stream codec (a transparent one needs libvpx)


def _t(seconds: float) -> str:
    return f"{seconds:.3f}"


def _rate(fps: float) -> str:
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def layer_inputs(layers: list[VisualLayer], fps: float) -> list[str]:
    """FFmpeg input arguments for every layer, in order."""
    args: list[str] = []
    for layer in layers:
        element = layer.element
        if layer.kind == "image":
            args += ["-loop", "1", "-framerate", _rate(fps), "-t", _t(element.duration)]
        else:
            if element.loop:
                args += ["-stream_loop", "-1"]
            args += ["-ss", _t(element.asset_offset_seconds), "-t", _t(element.duration), "-an"]
            if layer.has_alpha:
                # FFmpeg's own VP8/VP9 decoders drop the alpha channel; libvpx keeps it.
                codec = "libvpx-vp9" if layer.codec == "vp9" else "libvpx"
                args += ["-c:v", codec]
        args += ["-i", str(layer.path)]
    return args


def _flatten(source: str, index: int, layer: VisualLayer, fps: float) -> tuple[str, str]:
    """Transparent image pixels composed onto the background colour (opaque result)."""
    size = f"{layer.width}x{layer.height}"
    graph = (
        f"{source}format=rgba[a{index}];"
        f"color=c={BACKGROUND}:s={size}:r={_rate(fps)}[c{index}];"
        f"[c{index}][a{index}]overlay=0:0:shortest=1:format=auto,format=yuv420p[s{index}];"
    )
    return graph, f"[s{index}]"


def _cutaway(source: str, index: int, fit: VisualFit) -> tuple[str, str]:
    if fit == VisualFit.FILL:
        return (
            f"{source}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
            f"[g{index}];",
            f"[g{index}]",
        )
    small_w, small_h = W // BLUR_DIVISOR, H // BLUR_DIVISOR
    return (
        f"{source}split=2[gb{index}][gf{index}];"
        f"[gb{index}]scale={small_w}:{small_h}:force_original_aspect_ratio=increase,"
        f"crop={small_w}:{small_h},gblur=sigma={BLUR_SIGMA},scale={W}:{H}[gbb{index}];"
        f"[gf{index}]scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2"
        f"[gff{index}];"
        f"[gbb{index}][gff{index}]overlay=(W-w)/2:(H-h)/2,setsar=1[g{index}];",
        f"[g{index}]",
    )


def _inset(source: str, index: int, element: VisualElement) -> tuple[str, str]:
    box_w, box_h = inset_box(element.size)
    chain = f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    if element.mode == VisualMode.PIP:
        border = PIP_BORDER
        chain += f",pad=iw+{2 * border}:ih+{2 * border}:{border}:{border}:color=white"
    else:
        chain = "format=rgba," + chain
        if element.opacity is not None and element.opacity < 1:
            chain += f",colorchannelmixer=aa={element.opacity:.2f}"
    return f"{source}{chain},setsar=1[g{index}];", f"[g{index}]"


def drawing_order(layers: list[VisualLayer]) -> list[VisualLayer]:
    """Cutaways first, then insets (each in time order): a picture-in-picture or overlay that
    overlaps a cutaway is drawn on top of it, never hidden under it."""
    return sorted(layers, key=lambda layer: (layer.element.is_inset, layer.element.start))


def layers_graph(
    layers: list[VisualLayer], first_input: int, fps: float, base: str = "[framed]"
) -> tuple[str, str]:
    """Filtergraph segment drawing every layer over ``base``; returns (graph, output label).
    ``layers`` must be in drawing order (see ``drawing_order``), like their inputs."""
    graph = ""
    current = base
    for index, layer in enumerate(layers):
        element = layer.element
        source = f"[{first_input + index}:v]"
        prep = "setpts=PTS-STARTPTS,"
        if layer.kind == "video":
            prep += f"fps={_rate(fps)},scale=trunc(iw*sar/2)*2:ih,setsar=1,"
        graph += f"{source}{prep.rstrip(',')}[p{index}];"
        source = f"[p{index}]"
        if layer.has_alpha and element.mode != VisualMode.OVERLAY:
            flat, source = _flatten(source, index, layer, fps)
            graph += flat
        if element.mode == VisualMode.CUTAWAY:
            part, source = _cutaway(source, index, element.fit or VisualFit.FILL)
            x, y = "0", "0"
        else:
            part, source = _inset(source, index, element)
            x, y = inset_position(element.position)
        graph += part
        timing = f"setpts=PTS+{_t(element.start)}/TB"
        fade = fade_filter(element)
        if fade:  # overlays are already RGBA; other layers gain an alpha plane for the ramp
            alpha = "" if element.mode == VisualMode.OVERLAY else "format=yuva420p,"
            timing += f",{alpha}{fade}"
        graph += f"{source}{timing}[l{index}];"
        output = f"[v{index}]"
        graph += (
            f"{current}[l{index}]overlay=x={x}:y={y}"
            f":enable='between(t,{_t(element.start)},{_t(element.end)})'"
            f":eof_action=pass:format=auto{output};"
        )
        current = output
    return graph.rstrip(";"), current
