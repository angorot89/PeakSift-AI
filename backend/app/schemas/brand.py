import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

LogoPosition = Literal["top_left", "top_right", "bottom_left", "bottom_right"]
LogoSize = Literal["small", "medium", "large"]


class BrandCreate(BaseModel):
    name: str = Field(max_length=200)
    primary_color: str = Field(max_length=16)
    secondary_color: str | None = Field(default=None, max_length=16)
    accent_color: str | None = Field(default=None, max_length=16)
    caption_emphasis_color: str | None = Field(default=None, max_length=16)
    logo_asset_id: uuid.UUID | None = None
    logo_position: LogoPosition = "top_right"
    logo_size: LogoSize = "small"
    end_card_text: str | None = Field(default=None, max_length=200)
    is_default: bool = False


class BrandUpdate(BaseModel):
    """Only the fields sent change; ``null`` clears an optional one."""

    name: str | None = Field(default=None, max_length=200)
    primary_color: str | None = Field(default=None, max_length=16)
    secondary_color: str | None = Field(default=None, max_length=16)
    accent_color: str | None = Field(default=None, max_length=16)
    caption_emphasis_color: str | None = Field(default=None, max_length=16)
    logo_asset_id: uuid.UUID | None = None
    logo_position: LogoPosition | None = None
    logo_size: LogoSize | None = None
    end_card_text: str | None = Field(default=None, max_length=200)
    is_default: bool | None = None


class LogoRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    name: str
    width: int
    height: int
    transparent: bool
    has_thumbnail: bool


class BrandRead(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    primary_color: str
    secondary_color: str | None
    accent_color: str | None
    caption_emphasis_color: str | None
    # Whether the emphasis colour is readable as caption text (WCAG AA on the presets' dark
    # outline); when not, captions keep their own colour and the brand colour stays an accent.
    caption_emphasis_readable: bool | None
    logo: LogoRead | None
    logo_position: LogoPosition
    logo_size: LogoSize
    end_card_text: str | None
    created_at: datetime
    updated_at: datetime


TemplateRecipe = Literal["clean", "punchy", "story", "minimal"]


class TemplateCreate(BaseModel):
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=1000)
    recipe: TemplateRecipe | None = None
    brand_profile_id: uuid.UUID | None = None
    # The settings (see branding/template_config.py); omitted → the recipe's defaults.
    config: dict[str, Any] | None = None
    is_default: bool = False
    # V1.8: the market the template is made for ("global", or e.g. "ma" for a Morocco format).
    market: str = "global"


class TemplateUpdate(BaseModel):
    """Only the fields sent change; settings, recipe or brand changes make a new version."""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    recipe: TemplateRecipe | None = None
    brand_profile_id: uuid.UUID | None = None
    config: dict[str, Any] | None = None
    is_default: bool | None = None


class TemplateBrandRead(BaseModel):
    id: uuid.UUID
    name: str
    primary_color: str
    has_logo: bool


class TemplateRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    recipe: TemplateRecipe | None
    brand: TemplateBrandRead | None
    config: dict[str, Any]
    version: int
    is_default: bool
    market: str = "global"
    created_at: datetime
    updated_at: datetime


class TemplateStarterRead(BaseModel):
    recipe: TemplateRecipe
    label: str
    description: str
    config: dict[str, Any]
    # V1.8: the starter's key (a recipe's name, or a curated market format such as
    # "ma_vox_pop") and the market it was curated for.
    key: str = ""
    market: str = "global"
