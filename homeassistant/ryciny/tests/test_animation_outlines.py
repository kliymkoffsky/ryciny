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
APP_ROOT = REPOSITORY_ROOT / "homeassistant" / "ryciny" / "app"
sys.path.insert(0, str(REPOSITORY_ROOT / "tools"))
sys.path.insert(0, str(APP_ROOT))

import add_sticker_borders as sticker  # noqa: E402
from ryciny import animation, animation_outlines, runtime_animation, sticker_renderer  # noqa: E402


PACK_ROOT = APP_ROOT / "ryciny" / "prepared-animations"


def _png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _pack(root: Path, *, key: str = "outline-shape") -> animation.Pack:
    pack = root / "SCENE" / key
    (pack / "frames").mkdir(parents=True)
    original = _png(Image.new("RGB", (8, 6), (220, 210, 190)))
    (pack / "original.png").write_bytes(original)
    manifest = {
        "version": 1,
        "kind": "SCENE",
        "key": key,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "sheet_sha256": "0" * 64,
        "provider": "test",
        "model": None,
        "frame_ms": animation.FRAME_MS,
    }
    (pack / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    for index in range(animation.FRAME_COUNT):
        frame = Image.new("RGBA", (24, 18), (0, 0, 0, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((3 + index, 4, 10 + index, 12), fill=(20 + index, 80, 160, 255))
        draw.rectangle((7 + index, 8, 16 + index, 10), fill=(220, 40, 30, 128))
        (pack / "frames" / f"{index:03d}.png").write_bytes(_png(frame))
    return animation.load_pack(pack)


def _snapshot(pack_path: Path) -> dict[str, bytes]:
    return {
        path.relative_to(pack_path).as_posix(): path.read_bytes()
        for path in sorted(pack_path.rglob("*"))
        if path.is_file()
    }


def _tracked_renderer(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple, dict]]:
    calls: list[tuple[tuple, dict]] = []
    real_renderer = sticker_renderer.render_sticker_frame

    def render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        calls.append((args, kwargs))
        return real_renderer(*args, **kwargs)

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", render)
    return calls


def test_ensure_publishes_derived_pack_and_preserves_raw_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _pack(tmp_path / "prepared")
    before = _snapshot(raw.path)
    store = animation_outlines.OutlineStore(tmp_path / "outline-cache")
    calls = _tracked_renderer(monkeypatch)

    outlined = store.ensure(raw)

    assert len(calls) == animation.FRAME_COUNT
    assert _snapshot(raw.path) == before
    assert outlined.path == tmp_path / "outline-cache" / store.recipe_id / raw.id / "pack"
    assert outlined.original.read_bytes() == raw.original.read_bytes()
    assert outlined.path.parent.joinpath("receipt.json").is_file()
    with Image.open(raw.frames[0]) as source:
        source.load()
        expected_bytes, metadata = sticker_renderer.render_sticker_frame(source)
        expected = Image.open(io.BytesIO(expected_bytes))
        try:
            assert outlined.frames[0].read_bytes() == expected_bytes
            with Image.open(outlined.frames[0]) as actual:
                actual.load()
                assert actual.size == tuple(metadata["output_size"])
                assert actual.size == expected.size
                padding = metadata["padding"]
                assert actual.getpixel((padding + 5, padding + 4)) == source.getpixel((5, 4))
                pixels = np.asarray(actual)
                assert np.any(
                    np.all(pixels[:, :, :3] == sticker_renderer.BACKING_RGB, axis=2)
                    & (pixels[:, :, 3] > 0)
                )
        finally:
            expected.close()


def test_normalized_cache_root_reuses_derived_pack_without_double_outlining(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _pack(tmp_path / "prepared")
    cache = tmp_path / "cache-root" / "nested" / ".." / "normalized-cache"
    calls = _tracked_renderer(monkeypatch)
    first_store = animation_outlines.OutlineStore(cache)
    first = first_store.ensure(raw)

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        raise AssertionError("reusing a derived pack must not render another outline")

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    second_store = animation_outlines.OutlineStore(cache)
    second = second_store.ensure(first)

    assert first_store.root == cache.resolve()
    assert first.path == cache.resolve() / first_store.recipe_id / raw.id / "pack"
    assert second.path == first.path
    assert second.id == first.id
    assert second.width == first.width and second.height == first.height
    assert len(calls) == animation.FRAME_COUNT


def test_cache_reuse_restart_validates_existing_derived_pack_without_rendering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _pack(tmp_path / "prepared")
    cache = tmp_path / "outline-cache"
    calls = _tracked_renderer(monkeypatch)
    first_store = animation_outlines.OutlineStore(cache)
    first = first_store.ensure(raw)
    first_bytes = _snapshot(first.path)

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        raise AssertionError("a valid outline cache must not rerender")

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    second_store = animation_outlines.OutlineStore(cache)
    second = second_store.ensure(raw)
    from_derived = second_store.ensure(first)

    assert len(calls) == animation.FRAME_COUNT
    assert second.path == first.path
    assert second.id == first.id
    assert _snapshot(second.path) == first_bytes
    assert from_derived.path == first.path and from_derived.id == first.id


def test_registry_outlines_on_ingestion_and_reads_cached_sprite_without_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _pack(tmp_path / "prepared", key="registry-shape")
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    calls = _tracked_renderer(monkeypatch)
    registry = runtime_animation.PackRegistry(tmp_path / "data", bundled)

    registry.add(raw)
    outlined = registry.get(raw.kind, raw.key)
    assert outlined is not None
    assert outlined.path != raw.path
    assert len(calls) == animation.FRAME_COUNT

    def fail_ensure(*args: object, **kwargs: object) -> animation.Pack:
        raise AssertionError("registry reads must not prepare outlines")

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        raise AssertionError("registry reads must not render outlines")

    assert registry.outlines is not None
    monkeypatch.setattr(registry.outlines, "ensure", fail_ensure)
    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    matched = registry.match(raw.kind, raw.key, raw.original)
    selected = registry.get(raw.kind, raw.key, raw.source_sha256)
    atlas = registry.atlas(outlined.id)

    assert matched is not None and matched.id == outlined.id
    assert selected is not None and selected.id == outlined.id
    assert atlas is not None and atlas.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(calls) == animation.FRAME_COUNT


def test_all_shipped_processed_packs_bypass_renderer_even_after_recipe_dependency_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack_paths = sorted(path for path in PACK_ROOT.glob("*/*") if path.is_dir())
    index = json.loads((APP_ROOT / "ryciny" / "animation-sticker-index.json").read_text())
    packs = [animation.load_pack(path) for path in pack_paths]

    assert len(packs) == 57
    assert {pack.id for pack in packs} == set(index["processed_pack_ids"])
    monkeypatch.setattr(animation_outlines, "_recipe", lambda: {"version": 1, "changed": True})

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        raise AssertionError("shipped processed packs must use the exact hash index")

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    store = animation_outlines.OutlineStore(tmp_path / "outline-cache")

    for pack in packs:
        outlined = store.ensure(pack)
        assert outlined.path == pack.path
        assert outlined.id == pack.id


def test_tampered_index_or_cache_receipt_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_index = tmp_path / "bad-index.json"
    bad_index.write_text("{not-json}\n")
    with pytest.raises(ValueError):
        animation_outlines.OutlineStore(tmp_path / "unused-cache", bad_index)

    raw = _pack(tmp_path / "prepared")
    cache = tmp_path / "outline-cache"
    outlined = animation_outlines.OutlineStore(cache).ensure(raw)
    receipt_path = outlined.path.parent / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    for key, value in receipt.items():
        if value == raw.id:
            receipt[key] = "0" * 64
            break
    else:
        raise AssertionError("outline receipt did not record the source pack ID")
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n")

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        raise AssertionError("tampered cache must not rerender")

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    with pytest.raises(ValueError):
        animation_outlines.OutlineStore(cache).ensure(raw)


def test_mid_frame_failure_cleans_staging_and_leaves_raw_pack_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _pack(tmp_path / "prepared")
    before = _snapshot(raw.path)
    cache = tmp_path / "outline-cache"
    store = animation_outlines.OutlineStore(cache)
    real_renderer = sticker_renderer.render_sticker_frame
    calls = 0

    def fail_midway(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ValueError("synthetic frame failure")
        return real_renderer(*args, **kwargs)

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_midway)
    with pytest.raises(ValueError):
        store.ensure(raw)

    assert calls == 4
    assert _snapshot(raw.path) == before
    assert not list(cache.rglob("receipt.json"))
    assert not any(path.name == "pack" for path in cache.rglob("*"))
    assert not any(path.name.startswith(f".{raw.id}-") for path in cache.rglob("*"))


def test_padding_limit_fails_before_renderer_or_cache_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _pack(tmp_path / "prepared")
    before = _snapshot(raw.path)
    cache = tmp_path / "outline-cache"
    store = animation_outlines.OutlineStore(cache)
    calls = 0

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        nonlocal calls
        calls += 1
        raise AssertionError("padding limits must be checked before rendering")

    monkeypatch.setattr(animation, "MAX_IMAGE_SIDE", raw.width + 2)
    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    with pytest.raises(ValueError, match="padding"):
        store.ensure(raw)

    assert calls == 0
    assert _snapshot(raw.path) == before
    assert not list(cache.rglob("receipt.json"))
    assert not any(path.name == "pack" for path in cache.rglob("*"))


def test_recipe_change_selects_new_cache_namespace_for_same_raw_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = _pack(tmp_path / "prepared")
    before = _snapshot(raw.path)
    cache = tmp_path / "outline-cache"
    calls = _tracked_renderer(monkeypatch)
    first_store = animation_outlines.OutlineStore(cache)
    first = first_store.ensure(raw)

    original_recipe = animation_outlines._recipe

    def changed_recipe() -> dict:
        recipe = original_recipe()
        recipe["numpy_version"] = f"{recipe['numpy_version']}-changed"
        return recipe

    monkeypatch.setattr(animation_outlines, "_recipe", changed_recipe)
    second_store = animation_outlines.OutlineStore(cache)
    second = second_store.ensure(raw)

    assert first_store.recipe_id != second_store.recipe_id
    assert first.path != second.path
    assert first.path == cache / first_store.recipe_id / raw.id / "pack"
    assert second.path == cache / second_store.recipe_id / raw.id / "pack"
    assert first.path.is_dir() and second.path.is_dir()
    assert len(calls) == animation.FRAME_COUNT * 2
    assert _snapshot(raw.path) == before


def test_mutating_recipe_after_store_creation_fails_before_publication(tmp_path: Path) -> None:
    raw = _pack(tmp_path / "prepared")
    cache = tmp_path / "outline-cache"
    store = animation_outlines.OutlineStore(cache)
    store.recipe["parameters"] = {"tampered": True}

    with pytest.raises(ValueError):
        store.ensure(raw)

    assert not list(cache.rglob("receipt.json"))
    assert not any(path.name == "pack" for path in cache.rglob("*"))


def test_manual_pass_updates_runtime_index_for_resolved_receipt_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "manual-root"
    raw = _pack(root, key="manual-index")
    receipt = tmp_path / "receipt-dir" / "manual-receipt.jsonl"
    receipt_argument = tmp_path / "receipt-dir" / "intermediate" / ".." / "manual-receipt.jsonl"
    backup = tmp_path / "backup"
    index_path = tmp_path / "animation-sticker-index.json"
    index_path.write_text(json.dumps({
        "version": 1,
        "algorithm": animation_outlines.AUTHORED_INDEX_ALGORITHM,
        "processed_pack_ids": [],
    }) + "\n")
    monkeypatch.setattr(sticker, "DEFAULT_ROOT", root)
    monkeypatch.setattr(sticker, "DEFAULT_RECEIPT", receipt)
    monkeypatch.setattr(animation_outlines, "INDEX_PATH", index_path)

    result = sticker.process(root, receipt=receipt_argument, backup_root=backup, apply=True)
    processed = animation.load_pack(raw.path)
    updated_index = json.loads(index_path.read_text())
    record = json.loads(receipt.read_text())

    assert result["changed"] == 1
    assert processed.id == record["after_pack_id"]
    assert processed.id in updated_index["processed_pack_ids"]

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        raise AssertionError("the manual pass index must suppress duplicate outlining")

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    outlined = animation_outlines.OutlineStore(tmp_path / "outline-cache", index_path).ensure(processed)
    assert outlined.path == processed.path
    assert outlined.id == processed.id


def _atlas(path: Path) -> bytes:
    image = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index in range(animation.FRAME_COUNT):
        row, column = divmod(index, 3)
        x, y = column * 20, row * 20
        draw.rectangle((x + 5, y + 5, x + 14, y + 14), fill=(30 + index, 50, 70, 255))
    data = _png(image)
    path.write_bytes(data)
    return data


def test_generate_animation_keeps_raw_output_and_reports_derived_outline_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import generate_animation

    source = tmp_path / "source.png"
    source.write_bytes(_png(Image.new("RGB", (16, 12), (240, 220, 190))))
    atlas = tmp_path / "atlas.png"
    _atlas(atlas)
    expected = animation.prepare_atlas(
        source,
        atlas,
        tmp_path / "expected",
        kind="SCENE",
        key="cli-shape",
        provider="local-atlas-import",
    )
    expected_bytes = _snapshot(expected.path)
    raw_output = tmp_path / "raw-output"
    outline_cache = tmp_path / "outline-cache"

    assert generate_animation.main([
        "--source", str(source),
        "--kind", "SCENE",
        "--key", "cli-shape",
        "--subject", "a test shape",
        "--sheet", str(atlas),
        "--output", str(raw_output),
        "--outline-cache", str(outline_cache),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    raw = animation.load_pack(raw_output)
    outlined = animation.load_pack(Path(payload["path"]))

    assert Path(payload["raw_path"]) == raw_output
    assert payload["raw_id"] == raw.id == expected.id
    assert _snapshot(raw.path) == expected_bytes
    assert outlined.path != raw.path
    assert payload["id"] == outlined.id


def test_generate_animation_reports_sticker_failure_without_mutating_raw_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import generate_animation

    source = tmp_path / "source.png"
    source.write_bytes(_png(Image.new("RGB", (16, 12), (240, 220, 190))))
    atlas = tmp_path / "atlas.png"
    _atlas(atlas)
    expected = animation.prepare_atlas(
        source,
        atlas,
        tmp_path / "expected",
        kind="SCENE",
        key="cli-failure",
        provider="local-atlas-import",
    )
    expected_bytes = _snapshot(expected.path)
    raw_output = tmp_path / "raw-output"
    outline_cache = tmp_path / "outline-cache"

    def fail_render(*args: object, **kwargs: object) -> tuple[bytes, dict]:
        raise sticker_renderer.StickerError("synthetic outline failure")

    monkeypatch.setattr(animation_outlines, "render_sticker_frame", fail_render)
    result = generate_animation.main([
        "--source", str(source),
        "--kind", "SCENE",
        "--key", "cli-failure",
        "--subject", "a test shape",
        "--sheet", str(atlas),
        "--output", str(raw_output),
        "--outline-cache", str(outline_cache),
    ])
    captured = capsys.readouterr()

    assert result == 2
    assert captured.out == ""
    assert "synthetic outline failure" in captured.err
    raw = animation.load_pack(raw_output)
    assert _snapshot(raw.path) == expected_bytes
    assert not list(outline_cache.rglob("receipt.json"))
    assert not any(path.name == "pack" for path in outline_cache.rglob("*"))
