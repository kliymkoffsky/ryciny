from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from ryciny import animation


PACK_ROOT = Path(__file__).parents[1] / "app" / "ryciny" / "prepared-animations"


def _source(path: Path, *, webp: bool = False) -> bytes:
    image = Image.new("RGB", (16, 12), (240, 220, 190))
    output = io.BytesIO()
    image.save(output, format="WEBP" if webp else "PNG")
    path.write_bytes(output.getvalue())
    return output.getvalue()


def _atlas(path: Path) -> bytes:
    image = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for index in range(6):
        row, column = divmod(index, 3)
        x, y = column * 20, row * 20
        draw.rectangle((x + 5, y + 5, x + 14, y + 14), fill=(30 + index, 50, 70, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    path.write_bytes(output.getvalue())
    return output.getvalue()


def _rgba_frame(path: Path, size: tuple[int, int]) -> bool:
    with Image.open(path) as image:
        return image.mode == "RGBA" and image.size == size


def test_source_png_preserves_png_and_converts_webp(tmp_path: Path) -> None:
    png = _source(tmp_path / "source.png")
    webp = _source(tmp_path / "source.webp", webp=True)
    assert animation.source_png(tmp_path / "source.png") == png
    converted = animation.source_png(tmp_path / "source.webp")
    assert converted.startswith(animation.PNG_SIGNATURE) if hasattr(animation, "PNG_SIGNATURE") else converted[:8] == b"\x89PNG\r\n\x1a\n"
    assert converted != webp


def test_prepare_loads_fixed_pack_and_rejects_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    sheet = tmp_path / "atlas.png"
    _source(source)
    _atlas(sheet)
    destination = tmp_path / "pack"
    pack = animation.prepare_atlas(source, sheet, destination, kind="SCENE", key="bells")
    loaded = animation.load_pack(destination)
    assert loaded == pack
    assert (loaded.kind, loaded.key, loaded.frame_ms) == ("SCENE", "bells", 180)
    assert len(loaded.frames) == animation.FRAME_COUNT
    assert len({frame.read_bytes() for frame in loaded.frames}) == 6
    manifest = json.loads((destination / "manifest.json").read_text())
    assert set(manifest) == {"version", "kind", "key", "source_sha256", "sheet_sha256", "provider", "model", "frame_ms"}
    before = (destination / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        animation.prepare_atlas(source, sheet, destination, kind="SCENE", key="bells")
    assert (destination / "manifest.json").read_bytes() == before


def test_malformed_source_and_pack_are_rejected(tmp_path: Path) -> None:
    source, sheet, destination = tmp_path / "source.png", tmp_path / "atlas.png", tmp_path / "pack"
    _source(source)
    _atlas(sheet)
    animation.prepare_atlas(source, sheet, destination, kind="DOG", key="small")
    original = (destination / "original.png").read_bytes()
    (destination / "original.png").write_bytes(original + b"changed")
    with pytest.raises(animation.AnimationError):
        animation.load_pack(destination)
    with pytest.raises(animation.AnimationError):
        animation.source_png(tmp_path / "missing.png")
    with pytest.raises(animation.AnimationError):
        animation.prepare_atlas(source, sheet, tmp_path / "other", kind="BAD", key="x")


def test_request_and_mocked_provider_prepare_one_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, sheet, destination = tmp_path / "source.png", tmp_path / "atlas.png", tmp_path / "pack"
    _source(source)
    atlas = _atlas(sheet)
    plan = animation.request_plan(source, subject="a bell", motion="ring", model="test-model")
    assert plan["dry_run"] is True
    assert "secret" not in json.dumps(plan)
    calls = []

    class Response:
        status = 200

        def read(self, limit: int) -> bytes:
            return json.dumps({"data": [{"b64_json": base64.b64encode(atlas).decode()}]}).encode()

        def close(self) -> None:
            pass

    def fake_open(request):
        calls.append(request)
        return Response()

    monkeypatch.setattr(animation, "_open_request", fake_open)
    result = animation.generate_atlas(source, subject="a bell", motion="ring", model="test-model", api_key="secret")
    assert result == atlas and len(calls) == 1
    assert calls[0].full_url == animation.ENDPOINT
    assert b'filename="reference.png"' in calls[0].data
    pack = animation.prepare_atlas(source, sheet, destination, kind="SCENE", key="bells")
    assert animation.load_pack(pack.path).id == pack.id


def test_provider_error_and_real_checked_in_packs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.png"
    _source(source)
    monkeypatch.setattr(animation, "_open_request", lambda request: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(animation.AnimationError, match="provider request failed"):
        animation.generate_atlas(source, subject="subject", api_key="secret")
    expected = {
        ("BIRD", "Turdus merula"), ("DOG", "Kundel średni"), ("PLANE", "C208-plain"),
        ("PLANE", "E75S-LOT"), ("SCENE", "bells"), ("SCENE", "mower"), ("SCENE", "music"),
        ("BIRD", "Aegithalos caudatus"), ("BIRD", "Anas platyrhynchos"),
        ("BIRD", "Ardea cinerea"), ("BIRD", "Buteo buteo"),
        ("BIRD", "Columba palumbus"), ("BIRD", "Dendrocopos major"),
        ("BIRD", "Erithacus rubecula"), ("BIRD", "Hirundo rustica"),
        ("BIRD", "Pica pica"), ("BIRD", "Upupa epops"),
        ("BIRD", "Alcedo atthis"), ("BIRD", "Ciconia ciconia"),
        ("BIRD", "Strix aluco"), ("BIRD", "Parus major"),
        ("BIRD", "Cyanistes caeruleus"), ("BIRD", "Passer domesticus"),
        ("BIRD", "Fringilla coelebs"), ("BIRD", "Carduelis carduelis"),
        ("BIRD", "Troglodytes troglodytes"), ("BIRD", "Sturnus vulgaris"),
        ("SCENE", "cat"), ("SCENE", "car"), ("SCENE", "motorcycle"),
        ("SCENE", "train"), ("SCENE", "rain"), ("SCENE", "wind"),
        ("SCENE", "storm"), ("SCENE", "doorbell"), ("SCENE", "talking"),
        ("SCENE", "children"),
        ("SCENE", "tools"), ("SCENE", "chainsaw"), ("SCENE", "helicopter"),
        ("SCENE", "ambulance"), ("SCENE", "police"), ("SCENE", "fire"),
        ("SCENE", "caralarm"), ("SCENE", "rooster"), ("SCENE", "frog"),
        ("SCENE", "bee"),
        ("SCENE", "ship"), ("SCENE", "siren"), ("SCENE", "horse"),
        ("SCENE", "cow"), ("SCENE", "sheep"), ("SCENE", "pig"),
        ("SCENE", "cricket"), ("SCENE", "mosquito"), ("SCENE", "icecream"),
        ("SCENE", "goat"),
        ("BIRD", "Alauda arvensis"),
        ("BIRD", "Anser anser"),
        ("BIRD", "Apus apus"),
        ("BIRD", "Athene noctua"),
        ("BIRD", "Columba livia"),
        ("BIRD", "Corvus corax"),
        ("BIRD", "Cuculus canorus"),
        ("BIRD", "Streptopelia decaocto"),
        ("BIRD", "Delichon urbicum"),
        ("BIRD", "Falco tinnunculus"),
        ("BIRD", "Fulica atra"),
        ("BIRD", "Gallinula chloropus"),
        ("BIRD", "Garrulus glandarius"),
        ("BIRD", "Larus argentatus"),
        ("BIRD", "Luscinia megarhynchos"),
        ("BIRD", "Motacilla alba"),
        ("BIRD", "Phasianus colchicus"),
        ("BIRD", "Picus viridis"),
        ("BIRD", "Sylvia atricapilla"),
        ("BIRD", "Tyto alba"),
    }
    found = set()
    for path in sorted(PACK_ROOT.glob("*/*")):
        pack = animation.load_pack(path)
        found.add((pack.kind, pack.key))
        assert len(pack.frames) == 6 and not (path / "frames" / "006.png").exists()
        assert pack.source_sha256 == hashlib.sha256(pack.original.read_bytes()).hexdigest()
        assert all(_rgba_frame(frame, (pack.width, pack.height)) for frame in pack.frames)
    assert found == expected
