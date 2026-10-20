"""Prepared animation lookup and optional generation in the existing still worker."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import tempfile
import time
from pathlib import Path

from PIL import Image

from . import animation, animation_outlines, config
from .store import now_ms

log = logging.getLogger(__name__)


class PackRegistry:
    def __init__(self, data: Path, bundled: Path) -> None:
        self.bindings: dict[tuple[str, str], dict[str, animation.Pack | None]] = {}
        self.sprites: dict[str, Path] = {}
        self.sources: dict[Path, tuple[tuple, str, str]] = {}
        # Packs also by the pixels of their original: re-encoding a WebP to PNG gives different bytes under another
        # Pillow or zlib (the add-on's container vs the machine that prepared the pack), the pixels stay the same.
        self.by_pixels: dict[tuple[str, str], dict[str, animation.Pack]] = {}
        self.sprite_root = data / "animation-sprites"
        self.outlines: animation_outlines.OutlineStore | None = None
        try:
            self.outlines = animation_outlines.OutlineStore(data / "animation-outlines")
        except (OSError, ValueError):
            log.exception("animation outlines unavailable; retaining still-image fallback")
            return
        for root in (bundled, data / "animations"):
            if root.is_symlink() or not root.is_dir():
                continue
            for kind in sorted(root.iterdir()):
                if kind.name not in animation.KINDS or kind.is_symlink() or not kind.is_dir():
                    continue
                for path in sorted(kind.iterdir()):
                    try:
                        pack = animation.load_pack(path)
                        if pack.kind != kind.name:
                            raise ValueError("pack kind does not match its directory")
                        self.add(pack)
                    except (OSError, ValueError):
                        log.warning("animation pack skipped: %s", path)

    def add(self, pack: animation.Pack) -> None:
        # Ingestion owns preparation. Descriptor and atlas reads only use validated cached outputs.
        if self.outlines is None:
            raise ValueError("animation outline preparation is unavailable")
        pack = self.outlines.ensure(pack)
        # A source can have one authored animation; conflicting copies must not win by filename.
        binding = (pack.kind, pack.key)
        versions = self.bindings.get(binding, {})
        if pack.source_sha256 in versions:
            previous = versions[pack.source_sha256]
            if previous is None or previous.id != pack.id:
                self.bindings[binding] = {**versions, pack.source_sha256: None}
                log.warning("conflicting animation packs: %s/%s", pack.kind, pack.key)
            return
        self.sprite_root.mkdir(parents=True, exist_ok=True)
        if self.sprite_root.is_symlink():
            raise ValueError("animation sprite directory must not be a symlink")
        canvas = Image.new("RGBA", (pack.width * animation.FRAME_COUNT, pack.height))
        for index, path in enumerate(pack.frames):
            with Image.open(path) as frame:
                assert frame.mode == "RGBA" and frame.size == (pack.width, pack.height)
                canvas.paste(frame, (index * pack.width, 0))
        target = self.sprite_root / f"{pack.id}.png"
        with tempfile.NamedTemporaryFile(dir=self.sprite_root, suffix=".png", delete=False) as output:
            temporary = Path(output.name)
            try:
                canvas.save(output, format="PNG", optimize=True)
                if output.tell() > animation.MAX_OUTPUT_BYTES:
                    raise ValueError("animation sprite exceeds the byte limit")
                output.flush()
                os.fsync(output.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        self.sprites[pack.id] = target
        self.bindings[binding] = {**versions, pack.source_sha256: pack}
        try:
            self.by_pixels.setdefault(binding, {})[pixel_digest(pack.original)] = pack
        except (OSError, ValueError):
            pass

    def get(self, kind: str, key: str, source_sha256: str | None = None) -> animation.Pack | None:
        versions = self.bindings.get((kind, key), {})
        if source_sha256 is not None:
            return versions.get(source_sha256)
        return next(iter(versions.values())) if len(versions) == 1 else None

    def match(self, kind: str, key: str, source: Path | None) -> animation.Pack | None:
        # Check at descriptor selection, not on immutable sprite requests. Rehash only changed stills.
        if source is None:
            return self.get(kind, key)
        try:
            info = source.lstat()
            signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            cached = self.sources.get(source)
            if cached is None or cached[0] != signature:
                digest = hashlib.sha256(animation.source_png(source)).hexdigest()
                self.sources[source] = (signature, digest, pixel_digest(source))
            _, digest, pixels = self.sources[source]
            found = self.get(kind, key, digest)
            if found is None:
                pack = self.by_pixels.get((kind, key), {}).get(pixels)
                # Only a pack that is still the one bound to its source: a conflict rejects it here too.
                if pack is not None and self.bindings.get((kind, key), {}).get(pack.source_sha256) is pack:
                    found = pack
            return found
        except (OSError, ValueError):
            return None

    def atlas(self, pack_id: str) -> bytes | None:
        path = self.sprites.get(pack_id)
        return read_image(path, animation.MAX_OUTPUT_BYTES) if path is not None else None


def pixel_digest(path: Path) -> str:
    """SHA-256 of an image's decoded RGBA pixels and size: the same picture gives the same digest in any encoding."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        return hashlib.sha256(f"{rgba.width}x{rgba.height}:".encode() + rgba.tobytes()).hexdigest()


def read_image(path: Path, limit: int) -> bytes | None:
    # Only registry-owned paths reach this bounded read; never decode or repair images here.
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            return None
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        return data if len(data) == info.st_size else None
    except OSError:
        return None


def generate_for_subject(app, kind: str, key: str, subject: str, source: Path, motion: str = "") -> bool:
    with config.SETTINGS_LOCK:
        if not app.cfg.animation_generate or not app.cfg.openai_key.strip():
            return False
        model, api_key, epoch = app.cfg.animation_model, app.cfg.openai_key, app._prefetch_epoch
    try:
        if kind not in animation.KINDS or not key or len(key.encode("utf-8")) > animation.MAX_KEY_BYTES:
            raise ValueError("invalid animation subject identity")
        if key in (".", "..") or any(char in key for char in ("/", "\\", "\x00")):
            raise ValueError("invalid animation subject key")
        source_data = animation.source_png(source)
        digest = hashlib.sha256(source_data).hexdigest()
        if digest in app.animation_registry.bindings.get((kind, key), {}):
            return False
        prompt = animation.animation_prompt(subject, motion)
        request = {"kind": kind, "key": key, "source_sha256": digest, "model": model, "prompt": prompt}
        identity = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        marker = app.cfg.data / "animation-generation" / "attempts" / f"{identity}.json"
        destination = app.cfg.data / "animations" / kind / identity
        if marker.exists() or destination.exists():
            return False
        with tempfile.TemporaryDirectory(prefix="animation-", dir=app.cfg.data) as work:
            canonical = Path(work) / "source.png"
            canonical.write_bytes(source_data)
            # The durable exclusive marker is the dispatch decision. Later disable cannot cancel an in-flight call.
            with config.SETTINGS_LOCK:
                if (not app.cfg.animation_generate or app._prefetch_epoch != epoch or
                        app.cfg.animation_model != model or app.cfg.openai_key != api_key):
                    return False
                marker.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with marker.open("x", encoding="utf-8") as output:
                        json.dump(request, output, ensure_ascii=False)
                        output.flush()
                        os.fsync(output.fileno())
                    directory = os.open(marker.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                except FileExistsError:
                    return False
            sheet = animation.generate_atlas(canonical, subject=subject, motion=motion, model=model, api_key=api_key)
            atlas = Path(work) / "atlas.png"
            atlas.write_bytes(sheet)
            pack = animation.prepare_atlas(canonical, atlas, destination, kind=kind, key=key,
                                           provider=animation.PROVIDER, model=model)
            app.animation_registry.add(pack)
            app.animation_revision += 1
        return True
    except Exception:  # noqa: BLE001 - retain the still and the marker after an uncertain paid attempt.
        log.exception("animation generation failed for %s/%s", kind, key)
        return False


def settings_changed(app, before: dict, after: dict) -> None:
    if before["animation_playback"] != after["animation_playback"]:
        app.animation_revision += 1
    if (before["animation_generate"] != after["animation_generate"] or
            after["animation_generate"] and before["animation_model"] != after["animation_model"]):
        app._prefetch_epoch += 1


def prefetch_once(app, since: int, expected_epoch: int) -> bool:
    generated = False
    for kind, key, subject, airline, prompt in app.wanted(since):
        if app._prefetch_epoch != expected_epoch:
            break
        source = app.art.cached(kind, key)
        if source is None and (kind == "BIRD" or app.provider_ready()):
            source = app.art.load(kind, key, subject, airline, prompt, wait=True)
        if app._prefetch_epoch != expected_epoch:
            break
        if source is not None:
            generated |= generate_for_subject(app, kind, key, subject, source, motion=prompt)
    return generated


def prefetch(app) -> None:
    epoch, since, version = -1, 0, -1
    while True:
        time.sleep(5)
        if app._prefetch_epoch != epoch:
            epoch, version = app._prefetch_epoch, -1
            since = 0 if app.cfg.animation_generate else now_ms() - app.cfg.lookback_hours * 3600_000
        if app.store.version == version or not (app.cfg.animation_generate or app.provider_ready()):
            continue
        observed_version, started = app.store.version, now_ms()
        prefetch_once(app, since, expected_epoch=epoch)
        if app._prefetch_epoch == epoch:
            version, since = observed_version, started - 60_000
