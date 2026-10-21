"""Canonical pixels for embedding: what the creator sees, decoded safely, in plain RGB.

Every image or video frame reaches an embedding provider through ``canonical_rgb``:

- **upright**: EXIF orientation is applied (stored images are already normalized upright;
  applying it again is a no-op, and a frame from FFmpeg carries no EXIF);
- **transparency** is composited onto a fixed neutral mid-grey (``NEUTRAL_BACKGROUND``), never
  a random or content-dependent colour, so the same file always gives the same pixels; a logo
  on a transparent background is embedded as the logo, not as a black or white square;
- **RGB**: palette, greyscale, 16-bit and CMYK images are converted;
- **bounded**: images are downscaled (aspect kept) so neither side exceeds ``MAX_SIDE`` before
  they reach a model that works at 224 px anyway; tiny or degenerate images are refused.

Decoding is bounded by Pillow's decompression-bomb limit, which the upload validation already
applied to stored assets.
"""

from PIL import Image, ImageOps

NEUTRAL_BACKGROUND = (128, 128, 128)
MAX_SIDE = 1024
MIN_SIDE = 8


class UnusableImage(ValueError):
    """The pixels cannot be embedded (too small, degenerate). The message is safe to show."""


def canonical_rgb(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if min(image.size) < MIN_SIDE:
        raise UnusableImage("The image is too small to analyse")
    if image.mode in ("I;16", "I;16B", "I;16L", "I"):
        image = image.point(lambda value: value / 256).convert("L")
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (*NEUTRAL_BACKGROUND, 255))
        image = Image.alpha_composite(background, rgba)
    image = image.convert("RGB")
    if max(image.size) > MAX_SIDE:
        image = image.copy()
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return image
