"""Validation, inspection, thumbnails and storage of creator-supplied images and videos.

An upload is accepted only when its contents really are what its name says:

- **Images** (JPEG, PNG, WebP) are opened with Pillow, which identifies the format from the
  bytes (never the name). The pixel count is checked from the header *before* anything is
  decoded (decompression bombs), animated images are refused, and the decoded picture is
  normalized: rotated upright from its EXIF orientation, converted to RGB (or RGBA when any
  pixel is transparent — CMYK, palette and 16-bit images included), bounded to
  ``IMAGE_MAX_SIDE`` and re-encoded (PNG with alpha, otherwise JPEG). An embedded colour
  profile (a phone's Display P3, a print CMYK profile) is converted to sRGB first, so colours
  render as the creator saw them; a multi-picture JPEG (MPO, written by some phones and
  cameras) keeps its primary picture. The stored file is that
  rendition, so EXIF metadata such as GPS positions is never kept, and every later step sees
  exactly the pixels the creator saw.
- **Videos** (MP4, MOV, WebM) are probed with ffprobe: the container must match the
  extension and a real video stream with an allow-listed codec, positive dimensions and a
  positive duration within the limit must exist. Rotation and sample aspect ratio give the
  display size. A representative frame is decoded for the thumbnail, which also proves the
  stream really decodes. The original file is stored unchanged; its sound is never used
  (B-roll renders muted).

The upload is hashed while it is spooled; the same file uploaded again to the same project
returns the existing asset. Every refusal removes what was written: nothing corrupt or
rejected is kept.
"""

import hashlib
import io
import json
import logging
import math
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import numpy as np
from fastapi import UploadFile
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Project, VisualAsset, VisualAssetKind
from app.services.ffprobe import ProbeError, parse_frame_rate, run_ffprobe
from app.services.storage import FileTooLarge, StorageProvider, copy_limited
from app.services.video_upload import (
    GENERIC_CONTENT_TYPES,
    UploadValidationError,
    sanitize_filename,
    too_large_message,
)
from app.services.workspace import scratch_directory

logger = logging.getLogger(__name__)

# Extension -> (kind, format family, MIME types a browser may send). For images the family is
# Pillow's format name; for videos one of the names in ffprobe's ``format_name``.
ALLOWED_VISUAL_TYPES: dict[str, tuple[VisualAssetKind, str, tuple[str, ...]]] = {
    ".jpg": (VisualAssetKind.IMAGE, "JPEG", ("image/jpeg", "image/jpg", "image/pjpeg")),
    ".jpeg": (VisualAssetKind.IMAGE, "JPEG", ("image/jpeg", "image/jpg", "image/pjpeg")),
    ".png": (VisualAssetKind.IMAGE, "PNG", ("image/png", "image/x-png")),
    ".webp": (VisualAssetKind.IMAGE, "WEBP", ("image/webp",)),
    ".mp4": (VisualAssetKind.VIDEO, "mp4", ("video/mp4",)),
    ".m4v": (VisualAssetKind.VIDEO, "mp4", ("video/mp4", "video/x-m4v")),
    ".mov": (VisualAssetKind.VIDEO, "mov", ("video/quicktime",)),
    ".webm": (VisualAssetKind.VIDEO, "webm", ("video/webm",)),
}
ACCEPTED_EXTENSIONS = tuple(sorted(ALLOWED_VISUAL_TYPES))
# Video codecs FFmpeg decodes reliably in PeakSift's builds; anything else is refused.
ALLOWED_VIDEO_CODECS = frozenset({"h264", "hevc", "vp8", "vp9", "av1", "mpeg4", "prores"})

DESCRIPTION_MAX_LENGTH = 500
TAG_MAX_LENGTH = 32
TAGS_MAX = 20
IMAGE_MAX_SIDE = 3840  # the stored rendition: more than enough for a 1080 × 1920 short
MIN_SIDE = 16  # anything smaller is not a usable visual
MAX_ASPECT = 20.0  # longer side / shorter side; beyond this, nothing fits a 9:16 frame
MAX_PLAUSIBLE_FPS = 240.0  # higher reported rates are metadata noise; stored as unknown
THUMBNAIL_SIDE = 480
THUMBNAIL_TIMEOUT_SECONDS = 60.0
JPEG_QUALITY = 92
THUMBNAIL_JPEG_QUALITY = 82


@dataclass(frozen=True)
class Inspection:
    """What a validated upload turned out to be, plus the files to store."""

    kind: VisualAssetKind
    media_path: Path
    media_extension: str
    content_type: str
    width: int
    height: int
    codec: str
    container: str
    has_alpha: bool = False
    has_audio: bool = False
    duration_seconds: float | None = None
    fps: float | None = None
    thumbnail_path: Path | None = None
    thumbnail_extension: str = "jpg"


def validate_visual_upload(
    filename: str | None, content_type: str | None
) -> tuple[str, str, VisualAssetKind]:
    """Return (safe_display_name, extension, kind) or raise 415."""
    safe_name = sanitize_filename(filename, fallback="visual")
    extension = PurePosixPath(safe_name).suffix.lower()
    if extension not in ALLOWED_VISUAL_TYPES:
        raise UploadValidationError(
            415, f"Unsupported file type. Use one of: {', '.join(ACCEPTED_EXTENSIONS)}"
        )
    kind, _, accepted = ALLOWED_VISUAL_TYPES[extension]
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if declared not in accepted and declared not in GENERIC_CONTENT_TYPES:
        raise UploadValidationError(415, "The file's content type does not match its extension")
    return safe_name, extension, kind


def _check_geometry(width: int, height: int, pixel_limit: int, what: str) -> None:
    if width < MIN_SIDE or height < MIN_SIDE:
        raise UploadValidationError(422, f"The {what} is too small (at least {MIN_SIDE} pixels)")
    if max(width, height) / min(width, height) > MAX_ASPECT:
        raise UploadValidationError(422, f"The {what} is too narrow to place in a short")
    if width * height > pixel_limit:
        megapixels = pixel_limit / 1_000_000
        raise UploadValidationError(
            413, f"The {what} is too large (at most {megapixels:g} megapixels)"
        )


# --- images -------------------------------------------------------------------------------


def _to_8bit(image: Image.Image) -> Image.Image:
    """16-bit and 32-bit greyscale images (PNG) converted without clipping to white."""
    if image.mode in ("I;16", "I;16B", "I;16L", "I;16N"):
        return Image.fromarray((np.asarray(image, dtype=np.uint16) >> 8).astype(np.uint8), "L")
    if image.mode in ("I", "F"):
        values = np.asarray(image, dtype=np.float64)
        peak = values.max() if values.size and values.max() > 255 else 255.0
        return Image.fromarray(np.clip(values * 255.0 / peak, 0, 255).astype(np.uint8), "L")
    return image


def _transparent(image: Image.Image) -> bool:
    """Whether any pixel is not fully opaque (palette transparency included)."""
    if image.mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in image.info:
        alpha = image.convert("RGBA").getchannel("A")
        low, _ = alpha.getextrema()
        return low < 255
    return False


def _to_srgb(image: Image.Image, profile: bytes | None, alpha: bool) -> Image.Image:
    """Convert pixels described by an embedded ICC profile to sRGB. A missing, unusable or
    unsupported profile leaves the pixels as they are (never a refusal)."""
    if not profile or image.mode not in ("RGB", "RGBA", "CMYK"):
        return image
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        target = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        output = "RGBA" if alpha and image.mode == "RGBA" else "RGB"
        converted = ImageCms.profileToProfile(image, source, target, outputMode=output)
    except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
        logger.info("An image's colour profile could not be applied; keeping its pixels")
        return image
    return converted if converted is not None else image


def inspect_image(path: Path, extension: str, work: Path, settings: Settings) -> Inspection:
    """Decode, check and normalize an image. Raises UploadValidationError (never echoing it)."""
    family = ALLOWED_VISUAL_TYPES[extension][1]
    limit = settings.visual_asset_max_pixel_count
    try:
        with warnings.catch_warnings():
            # Pillow only *warns* between its bomb threshold and twice it; refuse instead.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # Pillow's JPEG opener also opens multi-picture JPEGs (MPO): their extra pictures
            # are previews or depth data, and the first picture is the photo.
            with Image.open(path, formats=[family]) as opened:
                width, height = opened.size
                _check_geometry(width, height, limit, "image")
                multi_picture = opened.format == "MPO"
                animated = (
                    getattr(opened, "is_animated", False) or getattr(opened, "n_frames", 1) > 1
                )
                if animated and not multi_picture:
                    raise UploadValidationError(415, "Animated images are not supported")
                if multi_picture:
                    opened.seek(0)
                profile = opened.info.get("icc_profile")
                opened.load()  # the full decode: truncated or corrupt data fails here
                image = ImageOps.exif_transpose(opened) or opened
                image = _to_8bit(image)
                alpha = _transparent(image)
                image = _to_srgb(image, profile, alpha)
                image = image.convert("RGBA" if alpha else "RGB")
    except UploadValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UploadValidationError(413, "The image is too large to process") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        # Wrong format for the extension, truncated, or otherwise undecodable.
        raise UploadValidationError(415, "The file is not a readable image of its type") from None
    if max(image.size) > IMAGE_MAX_SIDE:
        image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
    media_extension = "png" if alpha else "jpg"
    media = work / f"media.{media_extension}"
    if alpha:
        image.save(media, "PNG", compress_level=6)
    else:
        image.save(media, "JPEG", quality=JPEG_QUALITY, optimize=True)
    thumbnail = image.copy()
    thumbnail.thumbnail((THUMBNAIL_SIDE, THUMBNAIL_SIDE), Image.Resampling.LANCZOS)
    thumbnail_path = work / f"thumbnail.{media_extension}"
    if alpha:
        thumbnail.save(thumbnail_path, "PNG", compress_level=6)
    else:
        thumbnail.save(thumbnail_path, "JPEG", quality=THUMBNAIL_JPEG_QUALITY, optimize=True)
    return Inspection(
        kind=VisualAssetKind.IMAGE,
        media_path=media,
        media_extension=media_extension,
        content_type="image/png" if alpha else "image/jpeg",
        width=image.width,
        height=image.height,
        codec="png" if alpha else "jpeg",
        container=family.lower(),
        has_alpha=alpha,
        thumbnail_path=thumbnail_path,
        thumbnail_extension=media_extension,
    )


# --- videos -------------------------------------------------------------------------------


def _rotation(stream: dict[str, Any]) -> int:
    for item in stream.get("side_data_list") or []:
        if isinstance(item, dict) and "rotation" in item:
            try:
                return int(round(float(item["rotation"])))
            except (TypeError, ValueError):
                return 0
    try:
        return int((stream.get("tags") or {}).get("rotate", 0))
    except (TypeError, ValueError):
        return 0


def _sample_aspect(stream: dict[str, Any]) -> float:
    """The pixel aspect ratio (``1`` when absent, unknown or nonsensical)."""
    text = str(stream.get("sample_aspect_ratio") or "1:1")
    try:
        num, den = (int(part) for part in text.split(":", 1))
    except ValueError:
        return 1.0
    ratio = num / den if num > 0 and den > 0 else 1.0
    return ratio if 0.1 <= ratio <= 10 else 1.0


def _positive(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


@dataclass(frozen=True)
class VideoProbe:
    codec: str
    container: str
    width: int  # display (after rotation and sample aspect ratio)
    height: int
    coded_pixels: int
    duration_seconds: float
    fps: float | None
    has_audio: bool
    # VP8/VP9 with an alpha channel (WebM marks it with the ALPHA_MODE tag): a transparent
    # video that may be drawn as an overlay (decoded with libvpx, which keeps the alpha).
    has_alpha: bool = False


def _alpha_video(stream: dict[str, Any]) -> bool:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    mode = next((str(v) for k, v in tags.items() if str(k).lower() == "alpha_mode"), "")
    return stream.get("codec_name") in ("vp8", "vp9") and mode.strip() == "1"


def parse_video_probe(data: dict[str, Any], extension: str) -> VideoProbe:
    """Check ffprobe's view of the file against what a B-roll video must be."""
    streams = [s for s in data.get("streams", []) if isinstance(s, dict)]
    container = data.get("format") if isinstance(data.get("format"), dict) else {}
    family = ALLOWED_VISUAL_TYPES[extension][1]
    if family not in str(container.get("format_name") or "").split(","):
        raise UploadValidationError(415, "The file's contents do not match its extension")
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and (s.get("disposition") or {}).get("attached_pic") != 1
        ),
        None,
    )
    if video is None:
        raise UploadValidationError(415, "The file does not contain a video stream")
    codec = str(video.get("codec_name") or "")
    if codec not in ALLOWED_VIDEO_CODECS:
        raise UploadValidationError(415, "This video codec is not supported")
    coded_w, coded_h = video.get("width"), video.get("height")
    if not (isinstance(coded_w, int) and isinstance(coded_h, int) and coded_w > 0 and coded_h > 0):
        raise UploadValidationError(422, "The video has no usable picture size")
    width = max(1, round(coded_w * _sample_aspect(video)))
    height = coded_h
    if abs(_rotation(video)) % 180 == 90:
        width, height = height, width
    duration = _positive(container.get("duration")) or _positive(video.get("duration"))
    if duration is None:
        raise UploadValidationError(422, "The video has no duration")
    fps = parse_frame_rate(video.get("avg_frame_rate")) or parse_frame_rate(
        video.get("r_frame_rate")
    )
    if fps is not None and not 0 < fps <= MAX_PLAUSIBLE_FPS:
        fps = None
    return VideoProbe(
        codec=codec[:64],
        container=family,
        width=width,
        height=height,
        coded_pixels=coded_w * coded_h,
        duration_seconds=round(duration, 3),
        fps=round(fps, 3) if fps else None,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        has_alpha=_alpha_video(video),
    )


def video_thumbnail(source: Path, target: Path, duration: float, *, ffmpeg_path: str) -> None:
    """Decode one representative frame (a third in, at most one second) as a bounded JPEG.

    Falls back to the first frame when the seek lands past the decodable end. Raises
    UploadValidationError when no frame decodes at all (a corrupt or unsupported stream).
    """
    for offset in (min(1.0, duration / 3), 0.0):
        target.unlink(missing_ok=True)
        command = [
            ffmpeg_path, "-v", "error", "-nostdin", "-y", "-ss", f"{offset:.3f}", "-i", str(source),
            "-map", "0:v:0", "-frames:v", "1", "-an", "-sn", "-dn",
            "-vf", (
                "scale=trunc(iw*sar/2)*2:ih,setsar=1,"
                f"scale={THUMBNAIL_SIDE}:{THUMBNAIL_SIDE}:force_original_aspect_ratio=decrease"
            ),
            "-c:v", "mjpeg", "-q:v", "4", "-f", "image2", str(target),
        ]  # fmt: skip
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=THUMBNAIL_TIMEOUT_SECONDS, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            break
        if result.returncode == 0 and target.is_file() and target.stat().st_size > 0:
            return
    target.unlink(missing_ok=True)
    raise UploadValidationError(422, "The video could not be decoded")


def inspect_video(path: Path, extension: str, work: Path, settings: Settings) -> Inspection:
    try:
        data = json.loads(run_ffprobe(path, ffprobe_path=settings.ffprobe_path))
    except (ProbeError, ValueError):
        raise UploadValidationError(422, "The video file could not be read") from None
    if not isinstance(data, dict):
        raise UploadValidationError(422, "The video file could not be read")
    probed = parse_video_probe(data, extension)
    _check_geometry(probed.width, probed.height, 2**62, "video")
    if probed.coded_pixels > settings.visual_asset_max_video_pixel_count:
        megapixels = settings.visual_asset_max_video_pixel_count / 1_000_000
        raise UploadValidationError(
            413, f"The video resolution is too high (at most {megapixels:.1f} megapixels)"
        )
    limit = settings.visual_asset_max_video_duration_seconds
    if probed.duration_seconds > limit:
        raise UploadValidationError(413, f"Videos can be at most {limit:g} seconds long")
    thumbnail = work / "thumbnail.jpg"
    video_thumbnail(path, thumbnail, probed.duration_seconds, ffmpeg_path=settings.ffmpeg_path)
    return Inspection(
        kind=VisualAssetKind.VIDEO,
        media_path=path,
        media_extension=extension.lstrip("."),
        content_type=ALLOWED_VISUAL_TYPES[extension][2][0],
        width=probed.width,
        height=probed.height,
        codec=probed.codec,
        container=probed.container,
        has_audio=probed.has_audio,
        has_alpha=probed.has_alpha,
        duration_seconds=probed.duration_seconds,
        fps=probed.fps,
        thumbnail_path=thumbnail,
        thumbnail_extension="jpg",
    )


# --- storing --------------------------------------------------------------------------------


class _HashingReader:
    """Wrap an upload stream so spooling it also computes its sha256 (one pass)."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def _existing(db: Session, project: Project, digest: str) -> VisualAsset | None:
    return db.scalar(
        select(VisualAsset).where(
            VisualAsset.project_id == project.id, VisualAsset.sha256 == digest
        )
    )


def store_visual_upload(
    db: Session,
    storage: StorageProvider,
    project: Project,
    upload: UploadFile,
    settings: Settings,
) -> tuple[VisualAsset, bool]:
    """Validate, inspect, store and index an upload. Returns (asset, created).

    Leaves no file behind on any refusal or failure, and returns the project's existing asset
    (``created`` False) when the same file was already uploaded to it.
    """
    safe_name, extension, kind = validate_visual_upload(upload.filename, upload.content_type)
    with scratch_directory(settings, "uploads") as work:
        spool = work / f"upload{extension}"
        reader = _HashingReader(upload.file)
        try:
            with spool.open("wb") as target:
                size = copy_limited(reader, target, settings.visual_asset_max_bytes)  # type: ignore[arg-type]
        except FileTooLarge as error:
            raise UploadValidationError(413, too_large_message(error.limit)) from None
        if size == 0:
            raise UploadValidationError(400, "The uploaded file is empty")
        digest = reader.digest.hexdigest()
        existing = _existing(db, project, digest)
        if existing is not None:
            return existing, False
        inspect = inspect_image if kind == VisualAssetKind.IMAGE else inspect_video
        found = inspect(spool, extension, work, settings)
        return _persist(db, storage, project, found, safe_name, digest)


def _persist(
    db: Session,
    storage: StorageProvider,
    project: Project,
    found: Inspection,
    display_name: str,
    digest: str,
) -> tuple[VisualAsset, bool]:
    key = storage.generate_key(found.media_extension, category="visuals")
    thumbnail_key = (
        storage.generate_key(found.thumbnail_extension, category="visuals")
        if found.thumbnail_path is not None
        else None
    )
    keep = False
    try:
        storage.put_file(found.media_path, key)
        if thumbnail_key is not None:
            storage.put_file(found.thumbnail_path, thumbnail_key)  # type: ignore[arg-type]
        asset = VisualAsset(
            project_id=project.id,
            kind=found.kind.value,
            display_name=display_name,
            storage_key=key,
            content_type=found.content_type,
            file_size=found.media_path.stat().st_size,
            sha256=digest,
            width=found.width,
            height=found.height,
            duration_seconds=found.duration_seconds,
            fps=found.fps,
            codec=found.codec,
            container=found.container,
            has_alpha=found.has_alpha,
            has_audio=found.has_audio,
            thumbnail_storage_key=thumbnail_key,
        )
        db.add(asset)
        try:
            db.commit()
        except IntegrityError:  # the same file, uploaded concurrently, won the constraint
            db.rollback()
            winner = _existing(db, project, digest)
            if winner is None:
                raise
            return winner, False
        keep = True
        return asset, True
    finally:
        if not keep:
            for stored in (key, thumbnail_key):
                if stored is not None:
                    storage.delete(stored)


# --- the creator's words about an asset ---------------------------------------------------------


def clean_display_name(raw: str) -> str:
    """A safe display name (metadata only); refused when nothing printable remains."""
    name = sanitize_filename(raw, fallback="")
    if not name:
        raise UploadValidationError(422, "The name cannot be empty")
    return name


def clean_description(raw: str) -> str:
    text = " ".join("".join(ch for ch in raw if ch.isprintable()).split())
    if len(text) > DESCRIPTION_MAX_LENGTH:
        raise UploadValidationError(
            422, f"The description can be at most {DESCRIPTION_MAX_LENGTH} characters"
        )
    return text


def clean_tags(raw: list[str]) -> list[str]:
    """Lower-case, single-spaced, letters/digits/spaces/hyphens, unique, in order."""
    tags: list[str] = []
    for item in raw:
        tag = " ".join(
            "".join(ch if (ch.isalnum() or ch in " -") else " " for ch in item.lower()).split()
        ).strip(" -")
        if not tag or tag in tags:
            continue
        if len(tag) > TAG_MAX_LENGTH:
            raise UploadValidationError(422, f"A tag can be at most {TAG_MAX_LENGTH} characters")
        tags.append(tag)
    if len(tags) > TAGS_MAX:
        raise UploadValidationError(422, f"An asset can have at most {TAGS_MAX} tags")
    return tags
