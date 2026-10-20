from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw


REPOSITORY_ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from ryciny import animation  # noqa: E402
import add_sticker_borders as sticker  # noqa: E402
import sticker_contour  # noqa: E402


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _pack(root: Path, *, empty: bool = False) -> Path:
    pack = root / "SCENE" / "test-shape"
    (pack / "frames").mkdir(parents=True)
    original = Image.new("RGB", (8, 6), (220, 210, 190))
    original_bytes = _png(original)
    (pack / "original.png").write_bytes(original_bytes)
    manifest = {
        "version": 1,
        "kind": "SCENE",
        "key": "test-shape",
        "source_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "sheet_sha256": "0" * 64,
        "provider": "test",
        "model": None,
        "frame_ms": animation.FRAME_MS,
    }
    (pack / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    for index in range(animation.FRAME_COUNT):
        frame = Image.new("RGBA", (24, 18), (0, 0, 0, 0))
        if not empty:
            draw = ImageDraw.Draw(frame)
            draw.rectangle((3 + index, 4, 10 + index, 12), fill=(20 + index, 80, 160, 255))
            draw.rectangle((7 + index, 8, 16 + index, 10), fill=(220, 40, 30, 128))
        (pack / "frames" / f"{index:03d}.png").write_bytes(_png(frame))
    return pack


def _decode(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.copy()


def test_render_has_ivory_backing_and_transparent_exterior() -> None:
    image = Image.new("RGBA", (24, 18), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 4, 11, 13), fill=(12, 90, 170, 255))
    draw.rectangle((10, 8, 17, 9), fill=(200, 20, 30, 128))
    encoded, metadata = sticker.render_sticker_frame(image)
    output = _decode(encoded)
    assert output.size == (24 + 2 * metadata["padding"], 18 + 2 * metadata["padding"])
    assert output.mode == "RGBA"
    assert output.getpixel((0, 0))[3] == 0
    assert output.getpixel((output.width - 1, output.height - 1))[3] == 0
    # The contour fills only the local border area with the authored ivory backing.
    pad = metadata["padding"]
    assert output.getpixel((pad + 12, pad + 6))[:3] == sticker.BACKING_RGB
    assert output.getpixel((pad + 12, pad + 6))[3] >= 128
    # Fully opaque source pixels keep their exact foreground color at the offset.
    assert output.getpixel((pad + 5, pad + 4)) == image.getpixel((5, 4))


def test_each_frame_gets_its_own_contour_and_keeps_external_concavity() -> None:
    left = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    right = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    left_draw = ImageDraw.Draw(left)
    right_draw = ImageDraw.Draw(right)
    # A wide U-shaped gap remains connected to the outside and must stay clear.
    left_draw.rectangle((3, 4, 8, 15), fill=(20, 80, 160, 255))
    left_draw.rectangle((29, 4, 35, 15), fill=(20, 80, 160, 255))
    left_draw.rectangle((3, 12, 35, 15), fill=(20, 80, 160, 255))
    right_draw.rectangle((5, 6, 13, 13), fill=(20, 80, 160, 255))
    left_bytes, left_meta = sticker.render_sticker_frame(left)
    right_bytes, right_meta = sticker.render_sticker_frame(right)
    left_out, right_out = _decode(left_bytes), _decode(right_bytes)
    assert left_out.size == right_out.size
    pad = left_meta["padding"]
    gap = (pad + 20, pad + 6)
    assert left_out.getpixel(gap)[3] == 0
    assert left_out.getpixel((pad + 5, pad + 6))[3] > 0
    assert right_out.getpixel((pad + 20, pad + 6))[3] == 0
    assert np.asarray(left_out.getchannel("A")).sum() != np.asarray(right_out.getchannel("A")).sum()


def test_render_is_deterministic_and_preserves_aspect_without_scaling() -> None:
    image = Image.new("RGBA", (31, 17), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((8, 5, 12, 9), fill=(10, 20, 30, 255))
    image.putpixel((9, 5), (40, 50, 60, 128))
    first, metadata = sticker.render_sticker_frame(image)
    second, second_metadata = sticker.render_sticker_frame(image)
    assert first == second
    assert metadata == second_metadata
    output = _decode(first)
    pad = metadata["padding"]
    assert output.size == (31 + 2 * pad, 17 + 2 * pad)
    assert output.getpixel((pad + 8, pad + 6)) == (10, 20, 30, 255)
    # The half-alpha source is composited over ivory, retaining its alpha input.
    expected = Image.new("RGBA", output.size, (*sticker.BACKING_RGB, 0))
    mask, _ = sticker_contour.contour_mask(np.asarray(image.getchannel("A")), metadata["radius"], pad)
    expected.putalpha(mask)
    expected.alpha_composite(image, (pad, pad))
    assert output.getpixel((pad + 9, pad + 5)) == expected.getpixel((pad + 9, pad + 5))


def test_apply_is_idempotent_and_preserves_original_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "prepared"
    pack = _pack(root)
    original_before = (pack / "original.png").read_bytes()
    manifest_before = (pack / "manifest.json").read_bytes()
    before_frames = [(pack / "frames" / f"{index:03d}.png").read_bytes() for index in range(6)]
    receipt = tmp_path / "sticker-pass.jsonl"
    backup = tmp_path / "backup"
    # Exercise reuse of a byte-backed external manifest before applying outputs.
    plan = sticker._build_plan(root, pack)
    sticker._backup_manifest([plan], backup)
    sticker._backup_manifest([plan], backup)
    first = sticker.process(root, receipt=receipt, backup_root=backup, apply=True)
    first_frames = [(pack / "frames" / f"{index:03d}.png").read_bytes() for index in range(6)]
    second = sticker.process(root, receipt=receipt, backup_root=backup, apply=True)
    assert first["changed"] == 1
    assert second["changed"] == 0
    assert second["statuses"]["SCENE/test-shape"] == "skip"
    assert first_frames == [(pack / "frames" / f"{index:03d}.png").read_bytes() for index in range(6)]
    assert (pack / "original.png").read_bytes() == original_before
    assert (pack / "manifest.json").read_bytes() == manifest_before
    backup_frames = [
        (backup / "SCENE" / "test-shape" / "frames" / f"{index:03d}.png").read_bytes()
        for index in range(6)
    ]
    assert backup_frames == before_frames
    assert len(receipt.read_text().splitlines()) == 1


def test_matching_receipt_skips_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "prepared"
    pack = _pack(root)
    receipt = tmp_path / "sticker-pass.jsonl"
    backup = tmp_path / "backup"
    sticker.process(root, receipt=receipt, backup_root=backup, apply=True)

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict[str, object]]:
        raise AssertionError("matching receipt must skip rendering")

    monkeypatch.setattr(sticker, "render_sticker_frame", fail_render)
    result = sticker.process(root, receipt=receipt, backup_root=backup, apply=True)
    assert result["changed"] == 0
    assert result["statuses"]["SCENE/test-shape"] == "skip"


def test_empty_alpha_and_stale_receipt_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "prepared"
    _pack(root)
    empty_root = tmp_path / "empty-prepared"
    _pack(empty_root, empty=True)
    with pytest.raises(sticker.StickerError, match="no visible pixels"):
        sticker.process(empty_root, receipt=tmp_path / "empty-pass.jsonl")
    receipt = tmp_path / "sticker-pass.jsonl"
    sticker.process(root, receipt=receipt, backup_root=tmp_path / "backup", apply=True)
    record = json.loads(receipt.read_text())
    assert record["algorithm"] == sticker.ALGORITHM
    assert record["parameters"]["backing_rgb"] == list(sticker.BACKING_RGB)
    record["after_pack_id"] = "0" * 64
    receipt.write_text(json.dumps(record) + "\n")
    with pytest.raises(sticker.StickerError, match="receipt/output mismatch"):
        sticker.process(root, receipt=receipt, backup_root=tmp_path / "backup", apply=True)


def test_malformed_receipt_and_symlink_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "prepared"
    _pack(root)
    receipt = tmp_path / "bad.jsonl"
    receipt.write_text("{not-json}\n")
    with pytest.raises(sticker.StickerError, match="not JSON"):
        sticker.process(root, receipt=receipt)
    link_root = tmp_path / "linked-root"
    link_root.symlink_to(root, target_is_directory=True)
    with pytest.raises(sticker.StickerError, match="symlink"):
        sticker.process(link_root, receipt=tmp_path / "link.jsonl")

    with pytest.raises(sticker.StickerError, match="outside prepared root"):
        sticker.process(root, receipt=tmp_path / "overlap.jsonl", backup_root=root, apply=True)
    with pytest.raises(sticker.StickerError, match="receipt must be outside prepared root"):
        sticker.process(root, receipt=root / "receipt.jsonl", backup_root=tmp_path / "backup", apply=True)
    backup = tmp_path / "backup"
    with pytest.raises(sticker.StickerError, match="outside backup directory"):
        sticker.process(root, receipt=backup / "receipt.jsonl", backup_root=backup, apply=True)
