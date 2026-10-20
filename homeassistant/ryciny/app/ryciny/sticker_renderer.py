"""Deterministic warm-ivory backing shared by pack preparation and runtime."""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
from PIL import Image, __version__ as PILLOW_VERSION

from . import animation, sticker_contour

TOOL_VERSION = 1
ALGORITHM = "alpha-silhouette-disk-dilation-smooth-v4-ivory"
BACKING_RGB = (242, 237, 227)
ALPHA_THRESHOLD = sticker_contour.ALPHA_THRESHOLD
RADIUS_FACTOR = 0.018
PADDING_EXTRA = sticker_contour.PADDING_EXTRA
SMOOTH_RADIUS_FACTOR = sticker_contour.SMOOTH_RADIUS_FACTOR
SMOOTH_THRESHOLD = sticker_contour.SMOOTH_THRESHOLD
BLUR_RADIUS = sticker_contour.BLUR_RADIUS
FRAME_COUNT = animation.FRAME_COUNT


class StickerError(ValueError):
    """Raised when a pack, receipt, or sticker operation is invalid."""


def render_sticker_frame(image: Image.Image, radius: int | None = None) -> tuple[bytes, dict[str, Any]]:
    """Render one RGBA frame on a warm-ivory rounded silhouette backing."""

    if image.mode != "RGBA":
        raise StickerError("sticker input frame must be RGBA")
    width, height = image.size
    if min(width, height) < 1:
        raise StickerError("sticker input frame must have positive dimensions")
    if radius is None:
        radius = math.ceil(RADIUS_FACTOR * max(width, height))
    if not isinstance(radius, int) or radius < 1:
        raise StickerError("sticker radius must be a positive integer")
    padding = radius + PADDING_EXTRA
    alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
    try:
        mask, component_threshold = sticker_contour.contour_mask(alpha, radius, padding)
    except ValueError as error:
        raise StickerError(str(error)) from error
    backing = Image.new("RGBA", mask.size, (*BACKING_RGB, 0))
    backing.putalpha(mask)
    output = backing.copy()
    output.alpha_composite(image, (padding, padding))
    encoded = io.BytesIO()
    output.save(encoded, format="PNG", optimize=True)
    data = encoded.getvalue()
    animation._image_info(data, "sticker frame", rgba=True)
    return data, {
        "input_size": [width, height],
        "output_size": [output.width, output.height],
        "radius": radius,
        "padding": padding,
        "alpha_threshold": ALPHA_THRESHOLD,
        "blur_radius": BLUR_RADIUS,
        "component_threshold": component_threshold,
    }


def recipe_parameters() -> dict[str, Any]:
    return {
        "algorithm": ALGORITHM,
        "alpha_threshold": ALPHA_THRESHOLD,
        "blur_radius": BLUR_RADIUS,
        "component_connectivity": 8,
        "component_minimum_factor": sticker_contour.COMPONENT_MINIMUM_FACTOR,
        "component_minimum_floor": sticker_contour.COMPONENT_MINIMUM_FLOOR,
        "fill_enclosed_holes": True,
        "hole_connectivity": 4,
        "backing_rgb": list(BACKING_RGB),
        "pillow_version": PILLOW_VERSION,
        "radius_factor": RADIUS_FACTOR,
        "padding_extra": PADDING_EXTRA,
        "smooth_radius_factor": SMOOTH_RADIUS_FACTOR,
        "smooth_threshold": SMOOTH_THRESHOLD,
    }


