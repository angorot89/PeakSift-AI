"""``GET /caption-styles``: the dynamic caption presets, positions and safe area exactly as the
renderer uses them, so the editor preview never keeps its own (drifting) copy of the numbers."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.config import get_settings
from app.schemas.caption_style import (
    CaptionStylesRead,
    DynamicPresetRead,
    FontRead,
    PlacementRead,
    SafeAreaRead,
)
from app.services.clip_edit.caption_metrics import EM_PER_SIZE
from app.services.clip_edit.caption_v2 import PRESETS_V2
from app.services.clip_edit.config import (
    CAPTION_RENDERER_V2,
    OUTPUT_HEIGHT,
    OUTPUT_WIDTH,
    CaptionPosition,
)
from app.services.clip_edit.emoji import emoji_font
from app.services.clip_edit.safe_area import GENERAL_SOCIAL, SAFE_AREA_VERSION, caption_placement

router = APIRouter(tags=["captions"])


@router.get("/caption-styles", response_model=CaptionStylesRead)
def caption_styles(_user: CurrentUser) -> CaptionStylesRead:
    settings = get_settings()
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
            )
            for preset, style in PRESETS_V2.items()
        ],
    )
