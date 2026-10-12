"""Provider-agnostic prompt for one analysis window.

The same wording is sent to every provider so that results stay comparable and so that
prompt changes are reviewed in one place. Timestamps are rendered as plain seconds, which
models copy back far more reliably than clock formats.
"""

from app.models.clip_detection import CANDIDATE_CATEGORIES
from app.services.clip_detection.contract import AnalysisWindow, ClipAnalysisRequest

SYSTEM_PROMPT = (
    "You are an experienced short-form video editor. You read a timestamped transcript "
    "excerpt from a long recording and pick the moments that would work as standalone "
    "short clips for TikTok, YouTube Shorts or Instagram Reels.\n\n"
    "Strong moments usually have: an unexpected outcome, humor, a surprising reaction, "
    "tension or conflict, an emotional peak, a clear narrative payoff, an interesting "
    "explanation, a strong opening statement, a self-contained story, or memorable "
    "dialogue. These are editorial heuristics, not promises about performance.\n\n"
    "Rules:\n"
    "- Use ONLY the transcript provided. Never invent speech, events or quotes.\n"
    "- start_seconds and end_seconds are absolute seconds from the start of the video and "
    "must align with the line timestamps you were given: start at the beginning of a line "
    "and end at the end of a line.\n"
    "- A clip must be a complete thought: it should make sense to someone who has not "
    "seen the rest of the recording.\n"
    "- Respect the duration limits exactly.\n"
    "- Scores are integers from 0 to 100 and reflect your editorial judgement.\n"
    "- Return fewer candidates, or none, rather than weak ones.\n"
    "- Respond with JSON only, matching the schema you were given."
)


def render_window(window: AnalysisWindow) -> str:
    """One transcript line per row: ``[start → end] text`` with one-decimal seconds."""
    return "\n".join(f"[{line.start:.1f} → {line.end:.1f}] {line.text}" for line in window.lines)


def user_prompt(request: ClipAnalysisRequest) -> str:
    window = request.window
    parts = [
        f"Video duration: {request.video_duration:.1f} seconds.",
        f"This excerpt covers {window.start:.1f}s to {window.end:.1f}s.",
        (
            f"Each clip must last between {request.min_clip_seconds:.0f} and "
            f"{request.max_clip_seconds:.0f} seconds."
        ),
        f"Propose at most {request.max_candidates} clips from this excerpt.",
        "Allowed categories: " + ", ".join(CANDIDATE_CATEGORIES) + ".",
    ]
    if request.language:
        parts.append(
            f"The transcript language is '{request.language}'. Write title, hook and "
            "rationale in that language."
        )
    if request.instructions:
        parts.append(request.instructions)
    parts.append("Transcript:\n" + render_window(window))
    return "\n".join(parts)
