#!/usr/bin/env python3
"""Add deterministic, per-frame warm-ivory sticker backing to prepared packs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPOSITORY_ROOT / "homeassistant" / "ryciny" / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ryciny import animation, animation_outlines, sticker_contour  # noqa: E402
from ryciny.sticker_renderer import (  # noqa: E402
    ALGORITHM, ALPHA_THRESHOLD, BACKING_RGB, BLUR_RADIUS, FRAME_COUNT,
    PADDING_EXTRA, RADIUS_FACTOR, SMOOTH_RADIUS_FACTOR, SMOOTH_THRESHOLD,
    TOOL_VERSION, StickerError, recipe_parameters as _static_parameters,
    render_sticker_frame,
)

DEFAULT_ROOT = APP_ROOT / "ryciny" / "prepared-animations"
DEFAULT_RECEIPT = REPOSITORY_ROOT / "docs" / "animation-atlases" / "sticker-pass.jsonl"
MAX_RECEIPT_BYTES = 16 * 1024 * 1024
HASH_RE = animation.HASH_RE

@dataclass
class PackPlan:
    """Validated source pack plus staged output and receipt metadata."""

    root: Path
    relative: str
    pack: animation.Pack
    original_bytes: bytes
    manifest_bytes: bytes
    before_frames: list[bytes]
    radius: int
    padding: int
    output_size: tuple[int, int]
    output_frames: list[bytes]
    component_thresholds: list[int]
    staged: Path | None = None
    after: animation.Pack | None = None
    old_frames: Path | None = None

    @property
    def source_original_sha256(self) -> str:
        return _hash(self.original_bytes)

    @property
    def source_manifest_sha256(self) -> str:
        return _hash(self.manifest_bytes)

    @property
    def before_frame_sha256(self) -> list[str]:
        return [_hash(value) for value in self.before_frames]

    @property
    def after_frame_sha256(self) -> list[str]:
        return [_hash(value) for value in self.output_frames]


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _absolute(path: Path) -> Path:
    path = Path(path).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _paths_overlap(left: Path, right: Path) -> bool:
    left_resolved = _absolute(left).resolve()
    right_resolved = _absolute(right).resolve()
    try:
        left_resolved.relative_to(right_resolved)
        return True
    except ValueError:
        pass
    try:
        right_resolved.relative_to(left_resolved)
        return True
    except ValueError:
        return False


def _assert_no_symlink(path: Path, label: str, *, allow_missing: bool = False) -> Path:
    """Reject symlink path components before resolving a user-controlled path."""

    candidate = _absolute(path)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                break
            raise StickerError(f"{label} does not exist: {candidate}") from None
        except OSError as error:
            raise StickerError(f"{label} is not readable: {candidate}") from error
        if stat.S_ISLNK(info.st_mode):
            raise StickerError(f"{label} must not contain a symlink: {candidate}")
    return candidate


def _regular_dir(path: Path, label: str, *, allow_missing: bool = False) -> Path:
    path = _assert_no_symlink(path, label, allow_missing=allow_missing)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return path
        raise StickerError(f"{label} does not exist: {path}") from None
    except OSError as error:
        raise StickerError(f"{label} is not readable: {path}") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StickerError(f"{label} must be a regular directory: {path}")
    return path.resolve()


def _regular_file(path: Path, label: str, limit: int) -> tuple[bytes, Path]:
    path = _assert_no_symlink(path, label)
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise StickerError(f"{label} must be a regular file: {path}")
        if info.st_size <= 0 or info.st_size > limit:
            raise StickerError(f"{label} exceeds its byte limit: {path}")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except StickerError:
        raise
    except OSError as error:
        raise StickerError(f"{label} is not readable: {path}") from error
    if len(data) != info.st_size or len(data) > limit:
        raise StickerError(f"{label} changed while it was read: {path}")
    return data, path.resolve()


def _pack_relative(root: Path, pack: Path) -> str:
    try:
        return pack.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise StickerError(f"pack is outside prepared root: {pack}") from error


def _pack_path(root: Path, requested: str | Path) -> Path:
    requested_path = Path(requested).expanduser()
    candidate = requested_path if requested_path.is_absolute() else root / requested_path
    candidate = _assert_no_symlink(candidate, "pack")
    root_resolved = root.resolve()
    try:
        candidate.resolve().relative_to(root_resolved)
    except ValueError as error:
        raise StickerError(f"pack must be below prepared root: {candidate}") from error
    if not candidate.is_dir():
        raise StickerError(f"pack must be a directory: {candidate}")
    return candidate


def discover_packs(root: Path) -> list[Path]:
    """Discover exactly two-level prepared packs and reject malformed siblings."""

    root = _regular_dir(root, "prepared root")
    try:
        kind_dirs = sorted(root.iterdir(), key=lambda value: value.name)
    except OSError as error:
        raise StickerError(f"prepared root is not readable: {root}") from error
    packs: list[Path] = []
    for kind_dir in kind_dirs:
        if kind_dir.is_symlink() or not kind_dir.is_dir() or kind_dir.name not in animation.KINDS:
            raise StickerError(f"prepared root contains an unexpected entry: {kind_dir}")
        children = sorted(kind_dir.iterdir(), key=lambda value: value.name)
        for pack in children:
            if pack.is_symlink() or not pack.is_dir():
                raise StickerError(f"kind directory contains an unexpected entry: {pack}")
            _assert_no_symlink(pack, "pack")
            packs.append(pack)
    if not packs:
        raise StickerError(f"prepared root contains no packs: {root}")
    return packs


def _read_pack_inputs(pack: animation.Pack) -> tuple[bytes, bytes, list[bytes]]:
    original_bytes, _ = _regular_file(pack.original, "original.png", animation.MAX_SOURCE_BYTES)
    manifest_bytes, _ = _regular_file(pack.path / "manifest.json", "manifest.json", animation.MAX_MANIFEST_BYTES)
    frames = [_regular_file(frame, f"frame {index}", animation.MAX_FRAME_BYTES)[0] for index, frame in enumerate(pack.frames)]
    if _hash(original_bytes) != pack.source_sha256:
        raise StickerError(f"original source hash changed: {pack.path}")
    return original_bytes, manifest_bytes, frames


def _receipt_record(plan: PackPlan) -> dict[str, Any]:
    if plan.after is None:
        raise StickerError("cannot record a pack without staged validation")
    parameters = _static_parameters()
    parameters.update({
        "input_size": [plan.pack.width, plan.pack.height],
        "output_size": list(plan.output_size),
        "radius": plan.radius,
        "padding": plan.padding,
        "component_thresholds": plan.component_thresholds,
    })
    return {
        "version": TOOL_VERSION,
        "operation": "add-sticker-borders",
        "algorithm": ALGORITHM,
        "pack": plan.relative,
        "kind": plan.pack.kind,
        "key": plan.pack.key,
        "source_original_sha256": plan.source_original_sha256,
        "source_manifest_sha256": plan.source_manifest_sha256,
        "before_pack_id": plan.pack.id,
        "after_pack_id": plan.after.id,
        "before_frame_sha256": plan.before_frame_sha256,
        "after_frame_sha256": plan.after_frame_sha256,
        "parameters": parameters,
    }


def _load_receipt(path: Path) -> dict[str, dict[str, Any]]:
    """Read compact JSONL and reject malformed or conflicting provenance."""

    path = _assert_no_symlink(path, "receipt", allow_missing=True)
    if not path.exists():
        return {}
    data, _ = _regular_file(path, "receipt", MAX_RECEIPT_BYTES)
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(data.splitlines(), 1):
        if not line.strip():
            raise StickerError(f"receipt line {line_number} is empty")
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StickerError(f"receipt line {line_number} is not JSON") from error
        if not isinstance(record, dict):
            raise StickerError(f"receipt line {line_number} is not an object")
        _validate_record(record, f"receipt line {line_number}")
        pack = record["pack"]
        if pack in records and records[pack] != record:
            raise StickerError(f"receipt contains conflicting records for {pack}")
        records[pack] = record
    return records


def _validate_record(record: dict[str, Any], label: str) -> None:
    required = {
        "version", "operation", "algorithm", "pack", "kind", "key",
        "source_original_sha256", "source_manifest_sha256", "before_pack_id",
        "after_pack_id", "before_frame_sha256", "after_frame_sha256", "parameters",
    }
    if set(record) != required:
        raise StickerError(f"{label} has unexpected fields")
    if record["version"] != TOOL_VERSION or record["operation"] != "add-sticker-borders" or record["algorithm"] != ALGORITHM:
        raise StickerError(f"{label} has an unsupported algorithm")
    for field in ("source_original_sha256", "source_manifest_sha256", "before_pack_id", "after_pack_id"):
        if not isinstance(record[field], str) or not HASH_RE.fullmatch(record[field]):
            raise StickerError(f"{label} has an invalid {field}")
    if not isinstance(record["pack"], str) or not record["pack"] or Path(record["pack"]).is_absolute():
        raise StickerError(f"{label} has an invalid pack path")
    if not isinstance(record["kind"], str) or record["kind"] not in animation.KINDS:
        raise StickerError(f"{label} has an invalid kind")
    if not isinstance(record["key"], str) or not record["key"]:
        raise StickerError(f"{label} has an invalid key")
    for field in ("before_frame_sha256", "after_frame_sha256"):
        values = record[field]
        if not isinstance(values, list) or len(values) != FRAME_COUNT or any(
            not isinstance(value, str) or not HASH_RE.fullmatch(value) for value in values
        ):
            raise StickerError(f"{label} has invalid {field}")
    parameters = record["parameters"]
    if not isinstance(parameters, dict):
        raise StickerError(f"{label} has invalid parameters")
    static = _static_parameters()
    if {key: parameters.get(key) for key in static} != static:
        raise StickerError(f"{label} uses different sticker parameters")
    for field in ("input_size", "output_size"):
        value = parameters.get(field)
        if not isinstance(value, list) or len(value) != 2 or any(not isinstance(item, int) or item < 1 for item in value):
            raise StickerError(f"{label} has invalid {field}")
    for field in ("radius", "padding"):
        if not isinstance(parameters.get(field), int) or parameters[field] < 1:
            raise StickerError(f"{label} has invalid {field}")
    thresholds = parameters.get("component_thresholds")
    if not isinstance(thresholds, list) or len(thresholds) != FRAME_COUNT or any(
        not isinstance(value, int) or value < 1 for value in thresholds
    ):
        raise StickerError(f"{label} has invalid component_thresholds")


def _state_for_pack(plan: PackPlan, record: dict[str, Any] | None) -> str:
    if record is None:
        return "new"
    if record["kind"] != plan.pack.kind or record["key"] != plan.pack.key:
        raise StickerError(f"receipt binding does not match {plan.relative}")
    if record["source_original_sha256"] != plan.source_original_sha256 or record["source_manifest_sha256"] != plan.source_manifest_sha256:
        raise StickerError(f"receipt source bytes do not match {plan.relative}")
    current_frames = plan.before_frame_sha256
    if record["before_pack_id"] == plan.pack.id and record["before_frame_sha256"] == current_frames:
        return "apply"
    if record["after_pack_id"] == plan.pack.id and record["after_frame_sha256"] == current_frames:
        return "skip"
    raise StickerError(f"receipt/output mismatch for {plan.relative}; refusing to reprocess")


def _stage_plan(plan: PackPlan) -> None:
    parent = plan.pack.path.parent
    stage = Path(tempfile.mkdtemp(prefix=f".{plan.pack.path.name}.sticker-stage-", dir=str(parent)))
    try:
        (stage / "frames").mkdir()
        (stage / "original.png").write_bytes(plan.original_bytes)
        (stage / "manifest.json").write_bytes(plan.manifest_bytes)
        for index, data in enumerate(plan.output_frames):
            (stage / "frames" / f"{index:03d}.png").write_bytes(data)
        loaded = animation.load_pack(stage)
        if loaded.kind != plan.pack.kind or loaded.key != plan.pack.key:
            raise StickerError(f"staged binding changed for {plan.relative}")
        if loaded.width * loaded.height * 4 * FRAME_COUNT > animation.MAX_DECODED_BYTES:
            raise StickerError(f"staged pack exceeds decoded pixel limit: {plan.relative}")
        plan.staged = stage
        plan.after = loaded
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _backup_pack(plan: PackPlan, backup_root: Path) -> None:
    """Copy the exact pre-pass pack outside the repository before any swap."""

    destination = backup_root / plan.relative
    if destination.exists() or destination.is_symlink():
        existing = animation.load_pack(destination)
        if existing.id != plan.pack.id:
            raise StickerError(f"backup already exists with different content: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.backup-", dir=str(destination.parent)))
    try:
        (stage / "frames").mkdir()
        (stage / "original.png").write_bytes(plan.original_bytes)
        (stage / "manifest.json").write_bytes(plan.manifest_bytes)
        for index, data in enumerate(plan.before_frames):
            (stage / "frames" / f"{index:03d}.png").write_bytes(data)
        loaded = animation.load_pack(stage)
        if loaded.id != plan.pack.id:
            raise StickerError(f"backup validation changed content: {destination}")
        os.replace(stage, destination)
        stage = None  # type: ignore[assignment]
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)


def _backup_manifest(plans: list[PackPlan], backup_root: Path) -> None:
    backup_root = _regular_dir(backup_root, "backup root", allow_missing=True)
    if not backup_root.exists():
        backup_root.mkdir(parents=True)
    for plan in plans:
        _backup_pack(plan, backup_root)
    lines = []
    for plan in plans:
        lines.append(json.dumps({
            "version": TOOL_VERSION,
            "operation": "sticker-input-backup",
            "pack": plan.relative,
            "pack_id": plan.pack.id,
            "original_sha256": plan.source_original_sha256,
            "manifest_sha256": plan.source_manifest_sha256,
            "frame_sha256": plan.before_frame_sha256,
        }, sort_keys=True, separators=(",", ":")))
    manifest_path = backup_root / "backup-manifest.jsonl"
    if manifest_path.exists() or manifest_path.is_symlink():
        existing, _ = _regular_file(manifest_path, "backup manifest", MAX_RECEIPT_BYTES)
        try:
            existing_text = existing.decode("utf-8")
        except UnicodeDecodeError as error:
            raise StickerError(f"backup manifest is not UTF-8: {manifest_path}") from error
        old_lines = {line for line in existing_text.splitlines() if line.strip()}
        if not set(lines).issubset(old_lines):
            raise StickerError(f"backup manifest conflicts with existing evidence: {manifest_path}")
        return
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_receipt(path: Path, records: dict[str, dict[str, Any]]) -> None:
    path = _assert_no_symlink(path, "receipt", allow_missing=True)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _assert_no_symlink(path, "receipt")
    lines = [json.dumps(records[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")) for key in sorted(records)]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    if len(payload) > MAX_RECEIPT_BYTES:
        raise StickerError("receipt exceeds the byte limit")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None  # type: ignore[assignment]
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_runtime_index(records: dict[str, dict[str, Any]]) -> None:
    """Publish proof of authored outputs alongside the deployable renderer."""

    path = animation_outlines.INDEX_PATH
    ids = set(animation_outlines._processed_ids(path))
    ids.update(record["after_pack_id"] for record in records.values())
    payload = (json.dumps({"version": 1, "algorithm": ALGORITHM,
                          "processed_pack_ids": sorted(ids)}, indent=2) + "\n").encode("utf-8")
    if len(payload) > animation_outlines.MAX_METADATA_BYTES:
        raise StickerError("runtime outline index exceeds its byte limit")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _swap_frames(plans: list[PackPlan]) -> None:
    swapped: list[PackPlan] = []
    try:
        for plan in plans:
            if plan.staged is None:
                raise StickerError(f"missing staged output for {plan.relative}")
            current = animation.load_pack(plan.pack.path)
            if current.id != plan.pack.id:
                raise StickerError(f"pack changed before replacement: {plan.relative}")
            old_frames = plan.pack.path.parent / f".{plan.pack.path.name}.sticker-old-{uuid.uuid4().hex}"
            os.replace(plan.pack.path / "frames", old_frames)
            try:
                os.replace(plan.staged / "frames", plan.pack.path / "frames")
            except Exception:
                os.replace(old_frames, plan.pack.path / "frames")
                raise
            plan.old_frames = old_frames
            swapped.append(plan)
        for plan in plans:
            loaded = animation.load_pack(plan.pack.path)
            if plan.after is None or loaded.id != plan.after.id:
                raise StickerError(f"replacement validation failed: {plan.relative}")
    except Exception:
        for plan in reversed(swapped):
            try:
                failed_frames = plan.pack.path / "frames"
                rollback_frames = plan.pack.path.parent / f".{plan.pack.path.name}.sticker-rollback-{uuid.uuid4().hex}"
                os.replace(failed_frames, rollback_frames)
                if plan.old_frames is not None:
                    os.replace(plan.old_frames, failed_frames)
                shutil.rmtree(rollback_frames, ignore_errors=True)
            except OSError:
                pass
        raise
    finally:
        for plan in plans:
            if plan.staged is not None:
                shutil.rmtree(plan.staged, ignore_errors=True)
                plan.staged = None
    for plan in plans:
        if plan.old_frames is not None:
            shutil.rmtree(plan.old_frames, ignore_errors=True)
            plan.old_frames = None


def _build_plan(root: Path, path: Path, *, render: bool = True) -> PackPlan:
    _assert_no_symlink(path, "pack")
    pack = animation.load_pack(path)
    original_bytes, manifest_bytes, before_frames = _read_pack_inputs(pack)
    radius = math.ceil(RADIUS_FACTOR * max(pack.width, pack.height))
    padding = radius + PADDING_EXTRA
    if not render:
        return PackPlan(
            root=root,
            relative=_pack_relative(root, path),
            pack=pack,
            original_bytes=original_bytes,
            manifest_bytes=manifest_bytes,
            before_frames=before_frames,
            radius=radius,
            padding=padding,
            output_size=(pack.width + 2 * padding, pack.height + 2 * padding),
            output_frames=[],
            component_thresholds=[],
        )
    outputs: list[bytes] = []
    component_thresholds: list[int] = []
    output_size: tuple[int, int] | None = None
    for index, frame_bytes in enumerate(before_frames):
        try:
            with Image.open(io.BytesIO(frame_bytes)) as image:
                image.load()
                output, metadata = render_sticker_frame(image, radius)
        except StickerError:
            raise
        except (OSError, ValueError) as error:
            raise StickerError(f"frame {index} cannot be decoded: {path}") from error
        size = tuple(metadata["output_size"])
        if output_size is None:
            output_size = size
        elif output_size != size:
            raise StickerError(f"sticker output dimensions diverged: {path}")
        outputs.append(output)
        component_thresholds.append(metadata["component_threshold"])
    if output_size is None:
        raise StickerError(f"pack has no frames: {path}")
    return PackPlan(
        root=root,
        relative=_pack_relative(root, path),
        pack=pack,
        original_bytes=original_bytes,
        manifest_bytes=manifest_bytes,
        before_frames=before_frames,
        radius=radius,
        padding=padding,
        output_size=output_size,
        output_frames=outputs,
        component_thresholds=component_thresholds,
    )


def process(
    root: Path,
    *,
    pack_path: Path | None = None,
    receipt: Path = DEFAULT_RECEIPT,
    backup_root: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Validate, stage, and optionally publish sticker borders for selected packs."""

    root = _regular_dir(root, "prepared root")
    paths = [_pack_path(root, pack_path)] if pack_path is not None else discover_packs(root)
    paths = sorted(paths, key=lambda value: _pack_relative(root, value))
    records = _load_receipt(receipt)
    update_index = root == DEFAULT_ROOT.resolve() and _absolute(receipt).resolve() == DEFAULT_RECEIPT.resolve()
    if update_index:
        animation_outlines._processed_ids(animation_outlines.INDEX_PATH)
    receipt_path = _absolute(receipt)
    if _paths_overlap(receipt_path, root):
        raise StickerError("receipt must be outside prepared root")
    if backup_root is not None:
        backup_path = _absolute(backup_root)
        if _paths_overlap(root, backup_path):
            raise StickerError("backup directory must be outside prepared root")
        if _paths_overlap(receipt_path, backup_path):
            raise StickerError("receipt must be outside backup directory")
    plans: list[PackPlan] = []
    statuses: dict[str, str] = {}
    for path in paths:
        snapshot = _build_plan(root, path, render=False)
        status = _state_for_pack(snapshot, records.get(snapshot.relative))
        statuses[snapshot.relative] = status
        if status != "skip":
            plan = _build_plan(root, path)
            if plan.pack.id != snapshot.pack.id:
                raise StickerError(f"pack changed during validation: {plan.relative}")
            plans.append(plan)
    result = {
        "version": TOOL_VERSION,
        "operation": "add-sticker-borders",
        "algorithm": ALGORITHM,
        "root": str(root),
        "packs": len(paths),
        "apply": apply,
        "statuses": statuses,
    }
    if apply and not plans and update_index:
        _write_runtime_index(records)
    if not apply or not plans:
        result["staged"] = 0
        result["changed"] = 0
        return result
    if backup_root is None:
        raise StickerError("an explicit backup directory is required with --apply")
    try:
        for plan in plans:
            _stage_plan(plan)
        _backup_manifest(plans, _absolute(backup_root))
        updated = dict(records)
        for plan in plans:
            updated[plan.relative] = _receipt_record(plan)
        _write_receipt(_absolute(receipt), updated)
        if update_index:
            _write_runtime_index(updated)
        _swap_frames(plans)
    except Exception:
        for plan in plans:
            if plan.staged is not None:
                shutil.rmtree(plan.staged, ignore_errors=True)
                plan.staged = None
        raise
    result["staged"] = len(plans)
    result["changed"] = len(plans)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Add repeatable per-frame warm-ivory sticker backing to prepared packs.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Prepared animation root.")
    parser.add_argument("--pack", type=Path, help="One pack path, relative to --root or absolute.")
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT, help="External JSONL provenance receipt.")
    parser.add_argument("--backup-dir", type=Path, help="Required external pre-pass frame backup root with --apply.")
    parser.add_argument("--apply", action="store_true", help="Publish staged frame outputs; default is validation only.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = process(
            args.root,
            pack_path=args.pack,
            receipt=args.receipt,
            backup_root=args.backup_dir,
            apply=args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (StickerError, animation.AnimationError, FileExistsError, OSError) as error:
        print(f"add_sticker_borders: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
