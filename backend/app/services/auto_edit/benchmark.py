"""A small, deterministic quality check for Auto Edit — descriptive QA, not a creativity score.

Six representative clips (synthetic transcripts and asset libraries, written for this check):
an energetic streamer story, an educational explainer with a matching asset, a podcast
exchange, quiet professional commentary, a clip with no useful B-roll, and a clip whose B-roll
suggestion has a strong matching asset. Each is planned with a planner and recipe, validated
by the server exactly as in production, and described with **objective** measures:

- ``valid``: the result is a real edit configuration (it fingerprints);
- ``degraded``: how many choices the server had to replace or leave out (notes);
- ``hallucinated``: handles the server never issued, plus real assets attached to a suggestion
  they do not match;
- ``hook`` and ``hook_grounded``: the hook, and whether it says what the clip says (the
  candidate's own hook counts as grounded);
- ``visuals`` / ``visual_relevance``: how many visuals, and the share whose asset really matches
  its suggestion (by tags, name or description);
- ``effect_density``: visuals plus sound effects per 10 seconds;
- ``planner`` and ``fallback_reason``: who planned it, and why the rules stood in.

Creative quality is judged by people looking at the result — never reported as a number here.
No "viral" or "quality" score exists or is implied.
"""

from dataclasses import asdict, dataclass

from app.services.auto_edit.contract import (
    MUSIC_HANDLE,
    AudioOption,
    AutoEditContext,
    AutoEditPlanner,
    BrollOption,
    Capabilities,
    TimedLine,
    VisualOption,
)
from app.services.auto_edit.planners import plan
from app.services.auto_edit.recipes import current_recipe
from app.services.auto_edit.validation import PlanRejected, hook_grounded, validate_plan
from app.services.broll.matching import MIN_SCORE, AssetTerms, match_score

ALL = Capabilities(True, "high", True, True, True, True)
PHRASES_ONLY = Capabilities(False, None, False, True, True, True)


@dataclass(frozen=True)
class AssetSpec:
    handle: str
    kind: str
    name: str
    description: str
    tags: tuple[str, ...]
    duration: float | None = None


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    description: str
    duration: float
    lines: tuple[tuple[float, float, str], ...]
    capabilities: Capabilities
    title: str
    candidate_hook: str
    suggestions: tuple[BrollOption, ...] = ()
    assets: tuple[AssetSpec, ...] = ()
    orientation: str = "landscape"
    music: bool = False
    #: What a good plan does here (checked objectively where possible).
    expects_visual: bool | None = None

    def context(self, recipe: str) -> AutoEditContext:
        visual_ids = {a.handle: f"00000000-0000-4000-8000-{index:012d}" for index, a in
                      enumerate(self.assets, start=1)}  # fmt: skip
        return AutoEditContext(
            clip_duration=self.duration,
            lines=tuple(TimedLine(*line) for line in self.lines),
            capabilities=self.capabilities,
            recipe=current_recipe(recipe).summary(),
            source_orientation=self.orientation,
            title=self.title,
            candidate_hook=self.candidate_hook,
            broll=self.suggestions,
            visual_assets=tuple(
                VisualOption(
                    a.handle, a.kind, a.name, a.description, a.tags, "landscape", a.duration
                )
                for a in self.assets
            ),  # fmt: skip
            music=AudioOption(MUSIC_HANDLE, "calm-bed.mp3", 45.0) if self.music else None,
            sound_effects=(AudioOption("sfx_1", "whoosh.wav", 0.8, transition=True),),
            reframe_analysis_id="00000000-0000-4000-8000-0000000000aa"
            if self.capabilities.smart_reframe
            else None,
            caption_track_id="00000000-0000-4000-8000-0000000000bb"
            if self.capabilities.word_timing
            else None,
            visual_ids=visual_ids,
            suggestion_ids={
                s.handle: f"00000000-0000-4000-9000-{i:012d}"
                for i, s in enumerate(self.suggestions, start=1)
            },  # fmt: skip
            audio_ids={
                MUSIC_HANDLE: "00000000-0000-4000-8000-0000000000cc",
                "sfx_1": "00000000-0000-4000-8000-0000000000dd",
            },  # fmt: skip
        )


CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        name="energetic_stream",
        description="Energetic streamer story, fast delivery, no matching asset",
        duration=18.0,
        lines=(
            (0.0, 3.2, "No way chat, I just clutched the final round with one HP!"),
            (3.2, 7.5, "Three of them were pushing me and my shield was already gone."),
            (7.5, 12.0, "I jumped off the bridge, turned around and hit every single shot."),
            (12.0, 18.0, "Fifty thousand people watched that live and I still can't believe it."),
        ),
        capabilities=ALL,
        title="The One HP Clutch",
        candidate_hook="I clutched it with one HP",
        suggestions=(
            BrollOption(
                "suggestion_1", 7.5, 10.5, "bridge jump", "Shows the jump off the bridge", ()
            ),  # fmt: skip
        ),
        expects_visual=False,
    ),
    BenchmarkCase(
        name="explainer",
        description="Educational explainer with a matching close-up image",
        duration=24.0,
        lines=(
            (0.0, 4.5, "Every green leaf is a tiny factory powered by sunlight."),
            (4.5, 9.8, "Inside each cell, chloroplasts capture light and split water."),
            (9.8, 15.0, "The plant keeps the hydrogen and releases the oxygen we breathe."),
            (15.0, 24.0, "So the next time you take a breath, thank a leaf."),
        ),
        capabilities=ALL,
        title="Why Leaves Are Factories",
        candidate_hook="Every leaf is a tiny factory",
        suggestions=(
            BrollOption(
                "suggestion_1",
                4.5,
                8.5,
                "leaf chloroplasts",
                "Shows the chloroplasts",
                ("visual_asset_1",),
                ("visual_asset_1",),
            ),  # fmt: skip
        ),
        assets=(
            AssetSpec(
                "visual_asset_1",
                "image",
                "leaf-chloroplast-closeup.jpg",
                "Microscope close-up of chloroplasts in a leaf cell",
                ("leaf", "chloroplast", "cell"),
            ),  # fmt: skip
        ),
        expects_visual=True,
    ),
    BenchmarkCase(
        name="podcast",
        description="Podcast exchange, two voices, nothing to illustrate",
        duration=30.0,
        lines=(
            (0.0, 5.0, "So tell me, how did you actually get started?"),
            (5.0, 13.0, "Honestly, I was terrible at it for the first two years."),
            (13.0, 21.0, "Everyone thinks it was overnight, but nobody saw the bad episodes."),
            (21.0, 30.0, "That is the part I wish people talked about more."),
        ),
        capabilities=PHRASES_ONLY,
        title="Nobody Saw the Bad Episodes",
        candidate_hook="Nobody saw the bad episodes",
        expects_visual=False,
    ),
    BenchmarkCase(
        name="quiet_commentary",
        description="Quiet professional commentary, suggestion without an asset",
        duration=26.0,
        lines=(
            (0.0, 6.0, "Interest rates stayed flat this quarter, as most analysts expected."),
            (6.0, 13.0, "What matters more is that hiring slowed for the third month in a row."),
            (13.0, 20.0, "That usually shows up in consumer spending about six months later."),
            (20.0, 26.0, "So watch the spending numbers, not the headlines."),
        ),
        capabilities=Capabilities(True, "mixed", True, True, True, True),
        title="Watch Spending, Not Headlines",
        candidate_hook="Watch the spending numbers, not the headlines",
        suggestions=(
            BrollOption("suggestion_1", 6.0, 10.0, "hiring chart", "The hiring slowdown", ()),
        ),
        expects_visual=False,
    ),
    BenchmarkCase(
        name="no_useful_broll",
        description="Abstract advice, no B-roll suggestions at all",
        duration=20.0,
        lines=(
            (0.0, 5.0, "Motivation is not something you wait for."),
            (5.0, 11.0, "It shows up after you start, not before."),
            (11.0, 20.0, "So start badly, and let the motivation catch up."),
        ),
        capabilities=ALL,
        title="Start Badly",
        candidate_hook="Start badly, then improve",
        expects_visual=False,
    ),
    BenchmarkCase(
        name="useful_broll_with_asset",
        description="Workshop story whose B-roll suggestion has a strong matching asset",
        duration=16.4,
        lines=(
            (0.0, 3.0, "Then she added the second weight and the entire thing folded."),
            (3.0, 7.0, "Here is the lesson I learned about every bridge we build."),
            (7.0, 12.7, "A structure is only as strong as its weakest joint."),
            (12.7, 16.4, "We had reinforced the middle and forgotten the corners."),
        ),
        capabilities=ALL,
        title="The Weakest Link",
        candidate_hook="Our bridge collapsed",
        suggestions=(
            BrollOption(
                "suggestion_1",
                10.2,
                12.7,
                "bridge joint",
                "Shows the weak joint",
                ("visual_asset_1",),
                ("visual_asset_1",),
            ),  # fmt: skip
        ),
        assets=(
            AssetSpec(
                "visual_asset_1",
                "image",
                "toothpick-bridge.jpg",
                "Toothpick bridge model with its corner joints",
                ("bridge", "joint"),
            ),
        ),  # fmt: skip
        music=True,
        expects_visual=True,
    ),
)


@dataclass(frozen=True)
class CaseReport:
    case: str
    recipe: str
    planner: str
    fallback_reason: str | None
    valid: bool
    layout: str | None
    captions: str | None
    hook: str | None
    hook_grounded: bool | None
    visuals: int
    visual_relevance: float | None
    sound_effects: int
    music: bool
    effect_density: float
    degraded: int
    hallucinated: int

    def row(self) -> dict:
        return asdict(self)


def evaluate(case: BenchmarkCase, recipe: str, planner: AutoEditPlanner, *,
             fallback_enabled: bool = True) -> CaseReport:  # fmt: skip
    context = case.context(recipe)
    outcome = plan(context, planner, fallback_enabled=fallback_enabled)
    try:
        validated = validate_plan(outcome.result.proposal, context, current_recipe(recipe))
    except PlanRejected:
        return CaseReport(case.name, recipe, outcome.result.provider, outcome.fallback_reason,
                          False, None, None, None, None, 0, None, 0, False, 0.0, 0, 0)  # fmt: skip
    config = validated.configuration
    sources = " ".join(filter(None, (context.transcript, case.candidate_hook, case.title)))
    hook = config.hook.text if config.hook else None
    elements = config.visuals.elements if config.visuals else ()
    by_id = {context.visual_ids[a.handle]: a for a in case.assets}
    by_time = {(s.start, s.end): s for s in case.suggestions}
    relevant = 0
    for element in elements:
        spec = by_id.get(element.asset_id)
        suggestion = by_time.get((element.start, element.end))
        if spec and suggestion:
            terms = AssetTerms.of(_AssetRow(spec))
            relevant += match_score(suggestion.query, terms) >= MIN_SCORE
    sfx = len(config.audio.sfx) if config.audio else 0
    return CaseReport(
        case=case.name,
        recipe=recipe,
        planner=outcome.result.provider,
        fallback_reason=outcome.fallback_reason,
        valid=bool(config.fingerprint()),
        layout=config.layout.value,
        captions=_captions(config),
        hook=hook,
        hook_grounded=_grounded(hook, case.candidate_hook, sources),
        visuals=len(elements),
        visual_relevance=round(relevant / len(elements), 2) if elements else None,
        sound_effects=sfx,
        music=bool(config.audio and config.audio.music),
        effect_density=round((len(elements) + sfx) / case.duration * 10, 2),
        degraded=len(validated.report.degraded),
        hallucinated=validated.report.unknown_handles + validated.report.unmatched_assets,
    )


def _captions(config) -> str | None:
    if not config.captions_enabled:
        return None
    timing = config.caption_timing.value if config.caption_timing else "phrase_fallback"
    return f"{config.caption_style.value}/{timing}"


def _grounded(hook: str | None, candidate: str, sources: str) -> bool | None:
    if not hook:
        return None
    return hook == candidate or hook_grounded(hook, sources)


class _AssetRow:
    """The few asset fields matching reads, from a benchmark asset spec."""

    def __init__(self, spec: AssetSpec) -> None:
        self.id = spec.handle
        self.display_name = spec.name
        self.description = spec.description
        self.tags = list(spec.tags)
