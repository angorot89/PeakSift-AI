"""``GET /caption-styles``: the dynamic caption presets, positions and safe area exactly as the
renderer uses them, so the editor preview never keeps its own (drifting) copy of the numbers."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.schemas.caption_style import (
    CaptionStylesRead,
    DynamicPresetRead,
    FontRead,
    HookSpecRead,
    HookStyleRead,
    PlacementRead,
    SafeAreaRead,
)
from app.services.clip_edit import hook
from app.services.clip_edit.caption_fonts import CAPTION_FONTS, em_per_size, font_file
from app.services.clip_edit.caption_metrics import EM_PER_SIZE
from app.services.clip_edit.caption_v2 import PRESETS_V2
from app.services.clip_edit.config import (
    CAPTION_RENDERER_V2,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    WORD_TIMED_PRESETS,
    CaptionPosition,
    DynamicPreset,
)
from app.services.clip_edit.emoji import emoji_font
from app.services.clip_edit.safe_area import GENERAL_SOCIAL, SAFE_AREA_VERSION, caption_placement

router = APIRouter(tags=["captions"])


def _creator_fields(preset: DynamicPreset, style, fonts_dir: str) -> dict:
    path = font_file(style.font, fonts_dir) if style.font else None
    return {
        "font": CAPTION_FONTS[style.font].family if style.font else None,
        "em_per_size": round(em_per_size(path), 4) if path is not None else EM_PER_SIZE,
        "available": style.font is None or path is not None,
        "one_word": style.one_word,
        "highlight": style.highlight,
        "marker": style.marker,
        "marker_outline": style.marker_outline,
        "pop": style.pop,
        "reveal": style.reveal,
        "glow": style.glow,
        "needs_word_timing": preset in WORD_TIMED_PRESETS,
        "scripts": list(style.scripts),
    }


@router.get("/caption-styles", response_model=CaptionStylesRead)
def caption_styles(_user: CurrentUser) -> CaptionStylesRead:
    settings = get_settings()
    margin_h = max(GENERAL_SOCIAL.px()["left"], GENERAL_SOCIAL.px()["right"])
    return CaptionStylesRead(
        renderer=CAPTION_RENDERER_V2,
        emoji="monochrome" if emoji_font(settings.ffmpeg_path) else "omitted",
        output_width=OUTPUT_WIDTH,
        output_height=OUTPUT_HEIGHT,
        font=FontRead(family=settings.caption_font_family, em_per_size=EM_PER_SIZE),
        safe_area=SafeAreaRead(
            version=SAFE_AREA_VERSION,
            top=GENERAL_SOCIAL.top,
            bottom=GENERAL_SOCIAL.bottom,
            left=GENERAL_SOCIAL.left,
            right=GENERAL_SOCIAL.right,
        ),
        positions={
            position.value: PlacementRead(**vars(caption_placement(position)))
            for position in CaptionPosition
        },
        presets=[
            DynamicPresetRead(
                name=preset.value,
                label=style.label,
                size=style.size,
                bold=style.bold,
                uppercase=style.uppercase,
                text=style.text,
                active=style.active,
                outline_colour=style.outline_colour,
                outline=style.outline,
                shadow=style.shadow,
                box=style.box,
                box_alpha=style.box_alpha,
                fade_ms=style.fade_ms,
                grow_from=style.grow_from,
                grow_ms=style.grow_ms,
                **_creator_fields(preset, style, settings.caption_fonts_dir),
            )
            for preset, style in PRESETS_V2.items()
        ],
        hook=HookSpecRead(
            max_chars=hook.MAX_HOOK_CHARS,
            max_lines=hook.MAX_HOOK_LINES,
            min_seconds=hook.MIN_HOOK_SECONDS,
            max_seconds=hook.MAX_HOOK_SECONDS,
            default_seconds=hook.DEFAULT_HOOK_SECONDS,
            fade_in_ms=hook.FADE_IN_MS,
            fade_out_ms=hook.FADE_OUT_MS,
            styles=[
                HookStyleRead(name=name.value, **vars(look))
                for name, look in hook.HOOK_STYLES.items()
            ],
            positions={
                "top": PlacementRead(
                    alignment=8, margin_v=GENERAL_SOCIAL.px()["top"], margin_h=margin_h
                ),
                "center": PlacementRead(alignment=5, margin_v=0, margin_h=margin_h),
            },
        ),
    )
