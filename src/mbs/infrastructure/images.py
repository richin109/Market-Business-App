from __future__ import annotations

import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from mbs.domain.media_assets import _SIGNATURES, THUMBNAIL_TARGET_BYTES


def validate_receipt_image(source: bytes, max_dimension_px: int) -> None:
    try:
        with Image.open(BytesIO(source)) as image:
            image.verify()
        with Image.open(BytesIO(source)) as image:
            if max(image.size) > max_dimension_px:
                raise ValueError("Receipt image dimensions exceed the configured limit")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("Receipt image is invalid") from error


def sanitize_image(
    source: bytes,
    media_type: str,
    allowed_image_types: frozenset[str],
    max_file_bytes: int,
    max_dimension_px: int,
) -> tuple[bytes, Image.Image, int, int]:
    if media_type not in allowed_image_types:
        raise ValueError(f"Unsupported image media type: {media_type}")
    if not source or len(source) > max_file_bytes:
        raise ValueError("Image is empty or exceeds the configured size limit")
    if not source.startswith(_SIGNATURES[media_type]):
        raise ValueError("Image signature does not match its media type")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(source)) as probe:
                probe.verify()
            with Image.open(BytesIO(source)) as opened:
                oriented = ImageOps.exif_transpose(opened)
                normalized_image = _normalized_mode(oriented, media_type)
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError("Image is invalid or exceeds Pillow's safety limits") from error
    if max(normalized_image.size) > max_dimension_px:
        normalized_image.close()
        raise ValueError("Image dimensions exceed the configured limit")
    output = BytesIO()
    image_format = "JPEG" if media_type == "image/jpeg" else "PNG"
    normalized_image.save(output, format=image_format, optimize=True)
    clean_bytes = output.getvalue()
    if len(clean_bytes) > max_file_bytes:
        normalized_image.close()
        raise ValueError("Sanitized image exceeds the configured size limit")
    return clean_bytes, normalized_image, normalized_image.width, normalized_image.height


def _normalized_mode(image: Image.Image, media_type: str) -> Image.Image:
    if media_type == "image/jpeg":
        return image.convert("RGB")
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def _encode_derivative(image: Image.Image, max_side: int) -> tuple[bytes, str]:
    resized = _resize_without_upscale(image, max_side)
    buffer = BytesIO()
    try:
        resized.save(buffer, format="WEBP", quality=80, method=6)
        return buffer.getvalue(), "image/webp"
    except (OSError, ValueError):
        return _encode_jpeg(resized), "image/jpeg"
    finally:
        if resized is not image:
            resized.close()


def _encode_thumbnail(image: Image.Image) -> tuple[bytes, str]:
    last_result = b""
    last_media_type = "image/webp"
    for max_side in (320, 256, 192, 128, 96, 64, 32, 16, 8, 4, 2, 1):
        resized = _resize_without_upscale(image, max_side)
        try:
            for quality in (80, 70, 60, 50, 40):
                buffer = BytesIO()
                try:
                    resized.save(buffer, format="WEBP", quality=quality, method=6)
                    result, media_type = buffer.getvalue(), "image/webp"
                except (OSError, ValueError):
                    result, media_type = _encode_jpeg(resized, quality), "image/jpeg"
                last_result, last_media_type = result, media_type
                if len(result) <= THUMBNAIL_TARGET_BYTES:
                    return result, media_type
        finally:
            if resized is not image:
                resized.close()
    return last_result, last_media_type


def _resize_without_upscale(image: Image.Image, max_side: int) -> Image.Image:
    longest_side = max(image.size)
    if longest_side <= max_side:
        return image.copy()
    ratio = max_side / longest_side
    dimensions = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(dimensions, Image.Resampling.LANCZOS)


def _encode_jpeg(image: Image.Image, quality: int = 80) -> bytes:
    if image.mode in {"RGBA", "LA"}:
        background = Image.new("RGB", image.size, "white")
        alpha = image.getchannel("A")
        background.paste(image.convert("RGB"), mask=alpha)
        image = background
    else:
        image = image.convert("RGB")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
