"""Entrances and exits of visual elements: none, or a short fade.

PeakSift's transitions are deliberately small: an element appears and disappears either at
once (``none``) or with a fade of 0.1–0.5 s (never longer than half the element). A fade is
an alpha ramp on the element's own layer, so it means the same thing in every mode:

- a **cutaway** cross-fades from the main picture to the B-roll and back (the original audio
  is untouched — only pictures change);
- a **picture-in-picture** box or **overlay** fades in over the main video and out again.

``opacity_at`` is the single definition of the ramp — the renderer's filter and the editor's
preview both follow it. Only module-formatted numbers reach the filtergraph.
"""

from app.services.visuals.config import VisualElement, VisualTransition


def _fmt(seconds: float) -> str:
    return f"{seconds:.3f}"


def opacity_at(element: VisualElement, t: float) -> float:
    """How visible the element is at short time ``t`` (0 hidden … 1 fully shown), before its
    own overlay opacity. Linear ramps; outside [start, end) the element is hidden."""
    if t < element.start or t >= element.end:
        return 0.0
    if element.transition != VisualTransition.FADE or not element.transition_seconds:
        return 1.0
    ramp = element.transition_seconds
    return max(0.0, min(1.0, (t - element.start) / ramp, (element.end - t) / ramp))


def fade_filter(element: VisualElement) -> str | None:
    """The alpha fades for a layer already shifted onto the short's timeline (its frames carry
    short-time timestamps), or ``None`` when the element has no transition. The layer must
    have an alpha channel (``format=yuva420p`` or ``rgba``) before this filter."""
    if element.transition != VisualTransition.FADE or not element.transition_seconds:
        return None
    ramp = element.transition_seconds
    return (
        f"fade=t=in:st={_fmt(element.start)}:d={_fmt(ramp)}:alpha=1,"
        f"fade=t=out:st={_fmt(element.end - ramp)}:d={_fmt(ramp)}:alpha=1"
    )
