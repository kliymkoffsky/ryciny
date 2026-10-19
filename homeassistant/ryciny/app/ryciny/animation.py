"""Bounded reference-image animation generation and six-frame pack loading."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


DEFAULT_MODEL = "gpt-image-2.5-sunburst"
FRAME_MS = 180
FRAME_COUNT = 6
KINDS = frozenset(("BIRD", "PLANE", "DOG", "SCENE"))
ENDPOINT = "https://api.openai.com/v1/images/edits"
PROVIDER = "openai-images-edits"
GRID_COLUMNS = 3
GRID_ROWS = 2
REGISTRATION_PADDING = 24
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_SHEET_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 16_000_000
MAX_DECODED_BYTES = 64 * 1024 * 1024
MAX_TEXT_BYTES = 64 * 1024
MAX_KEY_BYTES = 512
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
PROMPT_PATH = Path(__file__).with_name("animation-prompt.txt")


class AnimationError(ValueError):
    """Raised when animation input, provider output, or pack data is invalid."""


@dataclass(frozen=True)
class Pack:
    """A validated immutable six-frame animation pack on disk."""

    path: Path
    id: str
    kind: str
    key: str
    source_sha256: str
    width: int
    height: int
    frame_ms: int
    frames: tuple[Path, ...]
    original: Path


def _read_regular(path: Path, limit: int, label: str) -> tuple[bytes, Path]:
    path = Path(path).expanduser()
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise AnimationError(f"{label} must be a regular file")
        if info.st_size <= 0 or info.st_size > limit:
            raise AnimationError(f"{label} exceeds the {limit} byte limit")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as error:
        raise AnimationError(f"{label} is not readable") from error
    if len(data) > limit:
        raise AnimationError(f"{label} exceeds the {limit} byte limit")
    if len(data) != info.st_size:
        raise AnimationError(f"{label} changed while it was read")
    return data, path.resolve()


def _image_info(
    data: bytes,
    label: str,
    formats: tuple[str, ...] = ("PNG",),
    *,
    rgba: bool = False,
) -> tuple[int, int]:
    if not data:
        raise AnimationError(f"{label} is empty")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in formats:
                raise AnimationError(f"{label} has an unsupported image format")
            width, height = image.size
            if min(width, height) < 1 or max(width, height) > MAX_IMAGE_SIDE:
                raise AnimationError(f"{label} dimensions exceed the image limit")
            if width * height > MAX_IMAGE_PIXELS:
                raise AnimationError(f"{label} contains too many pixels")
            if getattr(image, "n_frames", 1) != 1:
                raise AnimationError(f"{label} must contain one frame")
            if rgba and image.mode != "RGBA":
                raise AnimationError(f"{label} must be RGBA")
            image.verify()
            return width, height
    except AnimationError:
        raise
    except (Image.DecompressionBombError, OSError, ValueError) as error:
        raise AnimationError(f"{label} is not a readable image") from error


def source_png(source: Path) -> bytes:
    """Validate a bounded PNG or WebP source and preserve or convert its bytes."""

    raw, _ = _read_regular(source, MAX_SOURCE_BYTES, "source")
    _image_info(raw, "source", ("PNG", "WEBP"))
    with Image.open(io.BytesIO(raw)) as image:
        if image.format == "PNG":
            return raw
        image.load()
        output = io.BytesIO()
        image.save(output, format="PNG")
    converted = output.getvalue()
    if len(converted) > MAX_SOURCE_BYTES:
        raise AnimationError("converted source exceeds the byte limit")
    _image_info(converted, "converted source")
    return converted


def _text(value: object, label: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or (not empty and not value.strip()):
        raise AnimationError(f"{label} must be a non-empty string")
    if len(value.encode("utf-8")) > limit:
        raise AnimationError(f"{label} exceeds the {limit} byte limit")
    return value


def _kind_key(kind: object, key: object) -> tuple[str, str]:
    if not isinstance(kind, str) or kind not in KINDS:
        raise AnimationError(f"kind must be one of {sorted(KINDS)}")
    key = _text(key, "key", MAX_KEY_BYTES)
    if key in (".", "..") or "/" in key or "\\" in key:
        raise AnimationError("key must not contain a path separator")
    return kind, key


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AnimationError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise AnimationError(f"{label} must be a JSON object")
    return value


def _fixed_dir(path: Path, expected: set[str], label: str) -> Path:
    path = Path(path).expanduser()
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise AnimationError(f"{label} must be a regular directory")
    children = tuple(path.iterdir())
    if {child.name for child in children} != expected:
        raise AnimationError(f"{label} has unexpected files")
    if any(child.is_symlink() for child in children):
        raise AnimationError(f"{label} contains a symlink")
    return path.resolve()


def load_pack(path: Path) -> Pack:
    """Load one compact pack, reading each source and frame exactly once."""

    path = _fixed_dir(Path(path), {"manifest.json", "original.png", "frames"}, "pack")
    manifest_data, _ = _read_regular(path / "manifest.json", MAX_MANIFEST_BYTES, "manifest.json")
    manifest = _json_object(manifest_data, "manifest")
    required = {"version", "kind", "key", "source_sha256", "sheet_sha256", "provider", "model", "frame_ms"}
    if set(manifest) - required - {"original_sha256"} or not required.issubset(manifest):
        raise AnimationError("manifest fields are not compact and fixed")
    if manifest["version"] != 1:
        raise AnimationError("manifest version is unsupported")
    kind, key = _kind_key(manifest.get("kind"), manifest.get("key"))
    source_digest = _text(manifest.get("source_sha256"), "source_sha256", 64).lower()
    sheet_digest = _text(manifest.get("sheet_sha256"), "sheet_sha256", 64).lower()
    if not HASH_RE.fullmatch(source_digest) or not HASH_RE.fullmatch(sheet_digest):
        raise AnimationError("manifest digests must be SHA-256 values")
    if "original_sha256" in manifest:
        if _text(manifest["original_sha256"], "original_sha256", 64).lower() != source_digest:
            raise AnimationError("original_sha256 must match source_sha256")
    _text(manifest.get("provider"), "provider", 256)
    if manifest.get("model") is not None:
        _text(manifest["model"], "model", 256)
    if isinstance(manifest.get("frame_ms"), bool) or manifest["frame_ms"] != FRAME_MS:
        raise AnimationError("frame_ms must equal the fixed playback duration")

    original_data, original = _read_regular(path / "original.png", MAX_SOURCE_BYTES, "original.png")
    original_width, original_height = _image_info(original_data, "original.png")
    if _hash(original_data) != source_digest:
        raise AnimationError("original.png does not match source_sha256")
    names = {f"{index:03d}.png" for index in range(FRAME_COUNT)}
    frames_dir = _fixed_dir(path / "frames", names, "frames")
    frames, frame_bytes = [], []
    width = height = 0
    for index in range(FRAME_COUNT):
        data, frame = _read_regular(frames_dir / f"{index:03d}.png", MAX_FRAME_BYTES, f"frame {index}")
        frame_width, frame_height = _image_info(data, f"frame {index}", rgba=True)
        if index == 0:
            width, height = frame_width, frame_height
        elif (frame_width, frame_height) != (width, height):
            raise AnimationError("all frames must share one RGBA canvas")
        frames.append(frame)
        frame_bytes.append(data)
    if original_width * original_height * 4 + width * height * 4 * FRAME_COUNT > MAX_DECODED_BYTES:
        raise AnimationError("pack decoded pixels exceed the aggregate limit")
    identity = hashlib.sha256(manifest_data + original_data + b"".join(frame_bytes)).hexdigest()
    return Pack(path, identity, kind, key, source_digest, width, height, FRAME_MS, tuple(frames), original)


def animation_prompt(subject: str, motion: str = "") -> str:
    """Render the bounded six-cell prompt from the checked-in template."""

    subject, motion = _text(subject, "subject", MAX_TEXT_BYTES), _text(motion, "motion", MAX_TEXT_BYTES, empty=True)
    template_data = PROMPT_PATH.read_bytes()
    template = template_data.decode("utf-8")
    if not template_data or len(template_data) > MAX_TEXT_BYTES:
        raise AnimationError("animation prompt template exceeds the byte limit")
    if template.count("{subject}") != 1 or template.count("{motion}") != 1:
        raise AnimationError("animation prompt template must contain subject and motion once")
    prompt = template.replace("{subject}", subject).replace("{motion}", motion).strip()
    if len(prompt.encode("utf-8")) > MAX_TEXT_BYTES:
        raise AnimationError("rendered animation prompt exceeds the byte limit")
    return prompt


def _request_fields(prompt: str, model: str) -> dict[str, object]:
    return {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1536x1024",
        "quality": "high",
        "background": "transparent",
        "output_format": "png",
    }


def request_plan(
    source: Path,
    *,
    subject: str,
    motion: str = "",
    model: str = DEFAULT_MODEL,
) -> dict[str, object]:
    """Return a redacted no-network plan using the exact live request fields."""

    source_path = Path(source).expanduser()
    data = source_png(source_path)
    model = _text(model, "model", 256)
    prompt = animation_prompt(subject, motion)
    fields = _request_fields(prompt, model)
    return {
        "version": 1,
        "provider": PROVIDER,
        "operation": "images.edits",
        "method": "POST",
        "endpoint": ENDPOINT,
        "fields": fields,
        "file": {"field": "image", "filename": "reference.png", "content_type": "image/png"},
        "source": {
            "name": source_path.name,
            "sha256": _hash(data),
            "bytes": len(data),
        },
        "dry_run": True,
    }


def _multipart(fields: dict[str, object], image: bytes) -> tuple[bytes, str]:
    boundary = f"----ryciny-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend((
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
            str(value).encode("utf-8"),
            b"\r\n",
        ))
    chunks.extend((
        f"--{boundary}\r\n".encode("ascii"),
        b'Content-Disposition: form-data; name="image"; filename="reference.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        image,
        b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ))
    return b"".join(chunks), boundary


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_request(request: urllib.request.Request) -> Any:
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=180.0)


def _response_image(raw: bytes) -> bytes:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AnimationError("provider response exceeds the byte limit")
    try:
        response = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AnimationError("provider response is not valid JSON") from error
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise AnimationError("provider response contains no image")
    data = response["data"]
    if not data or not isinstance(data[0], dict) or not isinstance(data[0].get("b64_json"), str):
        raise AnimationError("provider response must contain b64_json")
    try:
        image = base64.b64decode(data[0]["b64_json"], validate=True)
    except (ValueError, binascii.Error) as error:
        raise AnimationError("provider response contains invalid base64") from error
    if len(image) > MAX_OUTPUT_BYTES:
        raise AnimationError("decoded provider image exceeds the byte limit")
    _image_info(image, "provider image")
    return image


def generate_atlas(
    source: Path,
    *,
    subject: str,
    motion: str = "",
    model: str = DEFAULT_MODEL,
    api_key: str,
) -> bytes:
    """Send one official OpenAI edit request and return its validated PNG atlas."""

    source_path = Path(source).expanduser()
    source_data = source_png(source_path)
    model, prompt = _text(model, "model", 256), animation_prompt(subject, motion)
    key = _text(api_key, "api_key", 4_096)
    body, boundary = _multipart(_request_fields(prompt, model), source_data)
    request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    response = None
    try:
        response = _open_request(request)
        status = getattr(response, "status", 200)
        if isinstance(status, int) and status >= 400:
            raise AnimationError(f"provider request failed with HTTP {status}")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise AnimationError(f"provider request failed with HTTP {error.code}") from error
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise AnimationError(f"provider request failed: {error}") from error
    finally:
        if response is not None:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    return _response_image(raw)


def _component_poses(sheet_data: bytes) -> list[Image.Image]:
    width, height = _image_info(sheet_data, "atlas", rgba=True)
    if width % GRID_COLUMNS or height % GRID_ROWS:
        raise AnimationError("atlas dimensions must divide into three columns and two rows")
    with Image.open(io.BytesIO(sheet_data)) as sheet:
        sheet.load()
        rgba = np.asarray(sheet).copy()
    alpha = rgba[:, :, 3]
    binary = Image.fromarray(np.where(alpha > 10, 255, 0).astype("uint8")).copy()
    poses: list[Image.Image] = []
    for index in range(FRAME_COUNT):
        row, column = divmod(index, GRID_COLUMNS)
        x0, x1 = column * width // GRID_COLUMNS, (column + 1) * width // GRID_COLUMNS
        y0, y1 = row * height // GRID_ROWS, (row + 1) * height // GRID_ROWS
        center = (min(x1 - 1, (x0 + x1) // 2), min(y1 - 1, (y0 + y1) // 2))
        if binary.getpixel(center) != 255:
            cell = np.asarray(binary)[y0:y1, x0:x1]
            visible = cell == 255
            if not np.any(visible):
                raise AnimationError(f"atlas cell {index} has no visible component")
            local_y, local_x = np.argwhere(visible)[0]
            center = (int(local_x + x0), int(local_y + y0))
        ImageDraw.floodfill(binary, center, 128)
        selected = np.asarray(binary) == 128
        remaining = np.asarray(binary) == 255
        cell_remaining = remaining[y0:y1, x0:x1]
        if int(cell_remaining.sum()) > 512:
            raise AnimationError(f"atlas cell {index} has overlapping components")
        selected[y0:y1, x0:x1] |= cell_remaining
        mask = Image.fromarray((selected * 255).astype("uint8")).filter(ImageFilter.MaxFilter(3))
        bbox = mask.getbbox()
        if bbox is None or int(selected.sum()) < 16:
            raise AnimationError(f"atlas cell {index} has an empty component")
        component = rgba.copy()
        component[:, :, 3] = np.minimum(alpha, np.asarray(mask))
        poses.append(Image.fromarray(component).crop(bbox))
        consumed = np.asarray(binary).copy()
        consumed[selected] = 0
        binary = Image.fromarray(consumed).copy()
    if int(np.sum(np.asarray(binary) == 255)) > 32:
        raise AnimationError("atlas contains extra or overlapping visible components")
    return poses


def _atlas_frames(sheet_data: bytes) -> tuple[list[bytes], int, int]:
    """Register complete poses on one fixed canvas without per-frame rescaling."""

    poses = _component_poses(sheet_data)
    width = max(pose.width for pose in poses) + REGISTRATION_PADDING * 2
    height = max(pose.height for pose in poses) + REGISTRATION_PADDING * 2
    if width * height > MAX_IMAGE_PIXELS:
        raise AnimationError("registered atlas frames contain too many pixels")
    frames: list[bytes] = []
    for pose in poses:
        x = (width - pose.width) // 2
        y = height - REGISTRATION_PADDING - pose.height
        canvas = Image.new("RGBA", (width, height))
        canvas.alpha_composite(pose, (x, y))
        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        encoded = output.getvalue()
        if len(encoded) > MAX_FRAME_BYTES:
            raise AnimationError("registered atlas frame exceeds the byte limit")
        frames.append(encoded)
    return frames, width, height


def prepare_atlas(
    source: Path,
    sheet: Path,
    destination: Path,
    *,
    kind: str,
    key: str,
    provider: str = PROVIDER,
    model: str | None = None,
) -> Pack:
    """Prepare six registered frames and atomically publish a new pack."""

    kind, key = _kind_key(kind, key)
    provider = _text(provider, "provider", 256)
    if model is not None:
        model = _text(model, "model", 256)
    source_path, sheet_path = Path(source).expanduser(), Path(sheet).expanduser()
    if source_path.resolve() == sheet_path.resolve():
        raise AnimationError("source and sheet must be different files")
    source_data = source_png(source_path)
    sheet_data, _ = _read_regular(sheet_path, MAX_SHEET_BYTES, "sheet")
    frames, width, height = _atlas_frames(sheet_data)
    destination = Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"output already exists: {destination}")
    parent = destination.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=str(parent)))
    manifest = {
        "version": 1,
        "kind": kind,
        "key": key,
        "source_sha256": _hash(source_data),
        "sheet_sha256": _hash(sheet_data),
        "provider": provider,
        "model": model,
        "frame_ms": FRAME_MS,
    }
    try:
        (staging / "frames").mkdir()
        (staging / "original.png").write_bytes(source_data)
        for index, frame in enumerate(frames):
            (staging / "frames" / f"{index:03d}.png").write_bytes(frame)
        manifest_data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(manifest_data) > MAX_MANIFEST_BYTES:
            raise AnimationError("manifest exceeds the byte limit")
        (staging / "manifest.json").write_bytes(manifest_data)
        load_pack(staging)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"output appeared during preparation: {destination}")
        os.replace(staging, destination)
        staging = None
        return load_pack(destination)
    except Exception:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise
