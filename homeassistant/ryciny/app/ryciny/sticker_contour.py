"""Pure NumPy and Pillow contour-mask construction for sticker backing."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageFilter


ALPHA_THRESHOLD = 16
COMPONENT_MINIMUM_FLOOR = 16
COMPONENT_MINIMUM_FACTOR = 0.002
PADDING_EXTRA = 3
SMOOTH_RADIUS_FACTOR = 0.35
SMOOTH_THRESHOLD = 127
BLUR_RADIUS = 0.5


def _remove_tiny_components(mask: np.ndarray, radius: int) -> tuple[np.ndarray, int]:
    """Keep substantial 8-connected foreground components for backing only."""

    foreground_count = int(mask.sum())
    minimum = max(
        COMPONENT_MINIMUM_FLOOR,
        radius * radius,
        math.ceil(foreground_count * COMPONENT_MINIMUM_FACTOR),
    )
    parents: list[int] = []
    sizes: list[int] = []
    previous: list[tuple[int, int, int]] = []
    runs: list[tuple[int, int, int, int]] = []

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = root(first), root(second)
        if first_root == second_root:
            return
        if sizes[first_root] < sizes[second_root]:
            first_root, second_root = second_root, first_root
        parents[second_root] = first_root
        sizes[first_root] += sizes[second_root]

    for y, row in enumerate(mask):
        edges = np.diff(np.pad(row, (1, 1), constant_values=False).astype(np.int8))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        current: list[tuple[int, int, int]] = []
        previous_index = 0
        for start_value, end_value in zip(starts, ends):
            start, end = int(start_value), int(end_value)
            index = len(parents)
            parents.append(index)
            sizes.append(end - start)
            while previous_index < len(previous) and previous[previous_index][1] < start:
                previous_index += 1
            overlap_index = previous_index
            while overlap_index < len(previous) and previous[overlap_index][0] <= end:
                union(index, previous[overlap_index][2])
                overlap_index += 1
            current.append((start, end, index))
            runs.append((y, start, end, index))
        previous = current
    kept = {root(index) for index in range(len(parents)) if sizes[root(index)] >= minimum}
    result = np.zeros_like(mask)
    for y, start, end, index in runs:
        if root(index) in kept:
            result[y, start:end] = True
    return result, minimum


def _fill_enclosed_holes(mask: np.ndarray) -> np.ndarray:
    """Fill transparent components enclosed by the alpha silhouette."""

    height, width = mask.shape
    parents: list[int] = []
    borders: list[bool] = []
    previous: list[tuple[int, int, int]] = []
    runs: list[tuple[int, int, int, int]] = []

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for y, row in enumerate(mask):
        edges = np.diff(np.pad(~row, (1, 1), constant_values=False).astype(np.int8))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        current: list[tuple[int, int, int]] = []
        previous_index = 0
        for start_value, end_value in zip(starts, ends):
            start, end = int(start_value), int(end_value)
            index = len(parents)
            parents.append(index)
            borders.append(y == 0 or y == height - 1 or start == 0 or end == width)
            while previous_index < len(previous) and previous[previous_index][1] <= start:
                previous_index += 1
            overlap_index = previous_index
            while overlap_index < len(previous) and previous[overlap_index][0] < end:
                old, new = root(previous[overlap_index][2]), root(index)
                if old != new:
                    parents[old] = new
                    borders[new] = borders[new] or borders[old]
                overlap_index += 1
            current.append((start, end, index))
            runs.append((y, start, end, index))
        previous = current
    result = mask.copy()
    for y, start, end, index in runs:
        if not borders[root(index)]:
            result[y, start:end] = True
    return result


def _disk_dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Dilate a binary mask by a Euclidean disk using row prefix sums."""

    height, width = mask.shape
    prefix = np.pad(mask.astype(np.int32).cumsum(axis=1, dtype=np.int32), ((0, 0), (1, 0)))
    x_values = np.arange(width)
    output = np.zeros_like(mask)
    intervals: dict[int, np.ndarray] = {}
    for dy in range(-radius, radius + 1):
        dx = math.isqrt(radius * radius - dy * dy)
        if dx not in intervals:
            intervals[dx] = (
                prefix[:, np.minimum(x_values + dx + 1, width)]
                - prefix[:, np.maximum(x_values - dx, 0)]
            ) > 0
        horizontal = intervals[dx]
        if dy < 0:
            output[:dy] |= horizontal[-dy:]
        elif dy > 0:
            output[dy:] |= horizontal[:-dy]
        else:
            output |= horizontal
    return output


def contour_mask(alpha: np.ndarray, radius: int, padding: int) -> tuple[Image.Image, int]:
    """Build a blurred, round-dilated mask and return its component threshold."""

    foreground = alpha >= ALPHA_THRESHOLD
    if not np.any(foreground):
        raise ValueError("frame has no visible pixels at the alpha threshold")
    retained, component_threshold = _remove_tiny_components(foreground, radius)
    if not np.any(retained):
        raise ValueError("frame has no retained foreground component for backing")
    filled = _fill_enclosed_holes(retained)
    padded = np.pad(filled, ((padding, padding), (padding, padding)))
    dilated = _disk_dilate(padded, radius)
    smooth = Image.fromarray(dilated.astype(np.uint8) * 255).filter(
        ImageFilter.GaussianBlur(radius * SMOOTH_RADIUS_FACTOR)
    )
    smooth = smooth.point(lambda value: 255 if value >= SMOOTH_THRESHOLD else 0)
    return smooth.filter(ImageFilter.GaussianBlur(BLUR_RADIUS)), component_threshold
