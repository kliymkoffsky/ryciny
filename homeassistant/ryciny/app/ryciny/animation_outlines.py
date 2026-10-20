"""Prepare immutable outlined variants at animation ingestion, never on playback."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import tempfile
import zlib
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import animation, sticker_contour, sticker_renderer
from .sticker_renderer import PADDING_EXTRA, RADIUS_FACTOR, render_sticker_frame

INDEX_PATH = Path(__file__).with_name("animation-sticker-index.json")
MAX_METADATA_BYTES = 128 * 1024
AUTHORED_INDEX_ALGORITHM = "alpha-silhouette-disk-dilation-smooth-v4-ivory"


def _json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _no_symlinks(path: Path) -> Path:
    path = Path(path).expanduser().absolute()
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise animation.AnimationError(f"outline path contains a symlink: {component}")
    return path.resolve()


def _metadata(path: Path) -> dict:
    _no_symlinks(path)
    data, _ = animation._read_regular(path, MAX_METADATA_BYTES, "outline metadata")
    return animation._json_object(data, "outline metadata")


def _recipe() -> dict:
    # Code and encoder versions separate cache identities without changing the authored v4 index.
    return {
        "version": 1,
        "parameters": sticker_renderer.recipe_parameters(),
        "numpy_version": np.__version__,
        "zlib_version": zlib.ZLIB_RUNTIME_VERSION,
        "implementation_sha256": {
            Path(module.__file__).name: _hash(Path(module.__file__).read_bytes())
            for module in (sticker_contour, sticker_renderer)
        },
        "pipeline_sha256": _hash(Path(__file__).read_bytes()),
    }


def _processed_ids(index_path: Path) -> frozenset[str]:
    index = _metadata(index_path)
    if set(index) != {"version", "algorithm", "processed_pack_ids"}:
        raise animation.AnimationError("outline index has unexpected fields")
    if type(index["version"]) is not int or index["version"] != 1 or index["algorithm"] != AUTHORED_INDEX_ALGORITHM:
        raise animation.AnimationError("outline index recipe is unsupported")
    ids = index["processed_pack_ids"]
    if not isinstance(ids, list) or any(not isinstance(value, str) or not animation.HASH_RE.fullmatch(value) for value in ids):
        raise animation.AnimationError("outline index has invalid pack identities")
    if len(ids) != len(set(ids)):
        raise animation.AnimationError("outline index contains duplicate pack identities")
    return frozenset(ids)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path: Path, data: bytes) -> None:
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


class OutlineStore:
    """Keep raw packs and deterministic outlined variants under separate ownership."""

    def __init__(self, cache_root: Path, index_path: Path = INDEX_PATH) -> None:
        self.root = _no_symlinks(cache_root)
        self.processed_ids = _processed_ids(index_path)
        self.recipe = _recipe()
        self.recipe_id = _hash(_json(self.recipe))

    def _cached(self, target: Path, source_id: str, source: animation.Pack | None = None) -> animation.Pack:
        _no_symlinks(target)
        animation._fixed_dir(target, {"pack", "receipt.json"}, "outline cache bundle")
        receipt = _metadata(target / "receipt.json")
        if set(receipt) != {"version", "source_pack_id", "output_pack_id", "recipe_id", "recipe"}:
            raise animation.AnimationError("outline receipt has unexpected fields")
        if (type(receipt["version"]) is not int or receipt["version"] != 1 or
                receipt["source_pack_id"] != source_id or receipt["recipe_id"] != self.recipe_id or
                _hash(_json(receipt["recipe"])) != self.recipe_id):
            raise animation.AnimationError("outline receipt does not match source and recipe")
        result = animation.load_pack(target / "pack")
        if receipt["output_pack_id"] != result.id:
            raise animation.AnimationError("outline receipt does not match output bytes")
        if source is not None:
            for name in ("original.png", "manifest.json"):
                if (source.path / name).read_bytes() != (result.path / name).read_bytes():
                    raise animation.AnimationError("outline output changed source provenance")
            padding = math.ceil(RADIUS_FACTOR * max(source.width, source.height)) + PADDING_EXTRA
            if (result.width, result.height) != (source.width + 2 * padding, source.height + 2 * padding):
                raise animation.AnimationError("outline output dimensions do not match recipe")
        return result

    def ensure(self, pack: animation.Pack) -> animation.Pack:
        """Validate a pack and return its existing or newly prepared outlined variant."""

        _no_symlinks(pack.path)
        current = animation.load_pack(pack.path)
        if current != pack:
            raise animation.AnimationError("outline source changed after validation")
        # These IDs bind all six authored frame bytes, the original and the unchanged manifest.
        # They remain valid when a newer Pillow or implementation creates a different cache key.
        if pack.id in self.processed_ids:
            return pack
        if _hash(_json(self.recipe)) != self.recipe_id:
            raise animation.AnimationError("outline recipe changed after initialization")
        parent = _no_symlinks(self.root / self.recipe_id)
        if pack.path.name == "pack" and pack.path.parent.parent.parent == self.root:
            if pack.path.parent.parent != parent:
                raise animation.AnimationError("a new outline recipe requires the raw source pack")
            result = self._cached(pack.path.parent, pack.path.parent.name)
            if result.id != pack.id:
                raise animation.AnimationError("outline cached pack identity changed")
            return result
        if self.root == pack.path or pack.path in self.root.parents:
            raise animation.AnimationError("outline cache must be outside the raw source pack")
        target = _no_symlinks(parent / pack.id)
        if target.exists():
            return self._cached(target, pack.id, pack)

        original, _ = animation._read_regular(pack.original, animation.MAX_SOURCE_BYTES, "outline source")
        manifest, _ = animation._read_regular(pack.path / "manifest.json", animation.MAX_MANIFEST_BYTES, "outline manifest")
        frames = [animation._read_regular(frame, animation.MAX_FRAME_BYTES, "outline frame")[0] for frame in pack.frames]
        if _hash(manifest + original + b"".join(frames)) != pack.id:
            raise animation.AnimationError("outline source changed during snapshot")
        radius = math.ceil(RADIUS_FACTOR * max(pack.width, pack.height))
        padding = radius + PADDING_EXTRA
        width, height = pack.width + 2 * padding, pack.height + 2 * padding
        original_width, original_height = animation._image_info(original, "outline source")
        if (max(width, height) > animation.MAX_IMAGE_SIDE or width * height > animation.MAX_IMAGE_PIXELS or
                original_width * original_height * 4 + width * height * 4 * animation.FRAME_COUNT > animation.MAX_DECODED_BYTES):
            raise animation.AnimationError("outline padding exceeds animation dimension or decoded-byte limits")

        parent.mkdir(parents=True, exist_ok=True)
        _no_symlinks(parent)
        stage = Path(tempfile.mkdtemp(prefix=f".{pack.id}-", dir=parent))
        try:
            output_pack = stage / "pack"
            (output_pack / "frames").mkdir(parents=True)
            _write(output_pack / "original.png", original)
            _write(output_pack / "manifest.json", manifest)
            for index, frame in enumerate(frames):
                with Image.open(io.BytesIO(frame)) as image:
                    image.load()
                    encoded, _ = render_sticker_frame(image, radius)
                if len(encoded) > animation.MAX_FRAME_BYTES:
                    raise animation.AnimationError("outline frame exceeds encoded-byte limit")
                _write(output_pack / "frames" / f"{index:03d}.png", encoded)
            result = animation.load_pack(output_pack)
            receipt = {"version": 1, "source_pack_id": pack.id, "output_pack_id": result.id,
                       "recipe_id": self.recipe_id, "recipe": self.recipe}
            _write(stage / "receipt.json", _json(receipt))
            self._cached(stage, pack.id, pack)
            if animation.load_pack(pack.path).id != pack.id:
                raise animation.AnimationError("outline source changed before publication")
            # A bundle becomes visible only with all frames and its receipt durable together.
            for directory in (output_pack / "frames", output_pack, stage):
                _sync_directory(directory)
            try:
                os.rename(stage, target)
            except OSError:
                # A competing ingestion may have published the same immutable bundle first.
                if not target.exists():
                    raise
                return self._cached(target, pack.id, pack)
            _sync_directory(parent)
            return self._cached(target, pack.id, pack)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
