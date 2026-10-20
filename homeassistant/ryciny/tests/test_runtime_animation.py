from __future__ import annotations

import io
import json
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
from ryciny import animation, config, runtime_animation
from ryciny.api import App
from ryciny.art import Art
from ryciny.assets import Assets
from ryciny.store import now_ms

REPO = Path(__file__).resolve().parents[3]
BUNDLED = Path(__file__).parents[1] / "app" / "ryciny" / "prepared-animations"


def test_catalog_subjects_through_runtime_and_immutable_atlas(tmp_path, monkeypatch):
    cfg = config.Config(data=tmp_path, assets=REPO, port=0, animation_playback=True, image_provider="none")
    assets = Assets(tmp_path, REPO)
    journal = {key: [] for key in ("birds", "planes", "dogs", "barks", "sounds")}
    state = SimpleNamespace(state=lambda: {})
    app = App(cfg, assets, SimpleNamespace(snapshot=lambda: journal, version=1), state, state, Art(cfg, assets),
              SimpleNamespace(level_db=lambda: 0, json=lambda: {}))
    thread = threading.Thread(target=app.serve, args=("127.0.0.1",), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while app.server is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app.server is not None
    base = f"http://127.0.0.1:{app.server.server_port}/"

    def get(path):
        with urllib.request.urlopen(base + path) as response:
            return response.read(), response.headers

    try:
        assert "javascript" in get("animation.js")[1]["Content-Type"]
        catalog = json.loads((REPO / "docs/animation-atlases/catalog.json").read_text())["examples"]
        assert len(catalog) == len(app.animation_registry.bindings) == 77
        app.cfg.sounds_on, app.cfg.sounds_off = list(app.sounds), []  # sheep and goat are off by default; check every subject
        for entry in catalog:
            kind, key, at = entry["kind"], entry["key"], now_ms()
            journal.update({name: [] for name in journal})
            if kind == "BIRD":
                journal["birds"] = [{"sci": key, "name": entry["title"], "at": at, "lastAt": at}]
            elif kind == "PLANE":
                code, airline = key.rsplit("-", 1)
                journal["planes"] = [{"typeCode": code, "airlineIcao": "" if airline == "plain" else airline,
                                      "airline": "", "title": entry["title"], "heard": True, "callsign": "", "route": "", "at": at, "lastAt": at}]
            elif kind == "DOG":
                journal["barks"] = [{"size": "średni", "count": 1, "at": at, "lastAt": at}]
            else:
                journal["sounds"] = [{"key": key, "variant": "", "title": entry["title"], "subtitle": "", "at": at, "lastAt": at}]
            query = urllib.parse.urlencode({"kind": kind, "key": key})
            pack = app.animation_registry.get(kind, key)
            assert any(wanted[:2] == (kind, key) for wanted in app.wanted(0))
            descriptor = json.loads(get("api/animation?" + query)[0])
            plate = json.loads(get("api/plate-animation?w=800&h=480")[0])
            assert descriptor["subject"] == plate["subject"] == [kind, key]
            assert descriptor["frameMs"] == 180 and plate["background"].startswith("data:image/png;base64,")
            sprite, headers = get(descriptor["atlas"])
            assert "immutable" in headers["Cache-Control"]
            with Image.open(io.BytesIO(sprite)) as image:
                assert image.size == (pack.width * 6, pack.height)
                for index, frame in enumerate(pack.frames):
                    with Image.open(frame) as expected:
                        assert image.crop((index * pack.width, 0, (index + 1) * pack.width, pack.height)).tobytes() == expected.tobytes()
            assert get("api/art?cached=1&" + query)[0] == pack.frames[0].read_bytes()
            assert get("api/plate.png?w=800&h=480")[0].startswith(animation.PNG_SIGNATURE)
        assert json.loads(get("api/animation?kind=PLANE&key=E75L-LOT")[0]) is None
        pack = app.animation_registry.get("SCENE", "bells")
        source = app.art.candidates("SCENE", "bells")[0]
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pack.original, source)
        assert app.animation_pack("SCENE", "bells") == pack
        Image.new("RGBA", (8, 8), "red").save(source)
        assert app.animation_pack("SCENE", "bells") is None
        with monkeypatch.context() as boundary:
            boundary.setattr(animation, "source_png", lambda path: (_ for _ in ()).throw(AssertionError("source decode on atlas GET")))
            boundary.setattr(Image, "open", lambda *args: (_ for _ in ()).throw(AssertionError("image decode on atlas GET")))
            assert get(f"api/animations/{pack.id}.png")[0]
        request = urllib.request.Request(base + "api/settings", data=b'{"animation_playback":false}', method="PUT")
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["animation_playback"] is False
        assert json.loads(get("api/live")[0])["animationRevision"] == 1
        assert json.loads(get("api/animation?kind=SCENE&key=music")[0]) is None
        assert json.loads((tmp_path / "settings.json").read_text())["animation_playback"] is False
    finally:
        app.stop()
        thread.join(5)


def _generation_app(tmp_path):
    source = tmp_path / "still.png"
    Image.new("RGBA", (16, 12), "brown").save(source)
    return SimpleNamespace(
        cfg=config.Config(data=tmp_path, assets=None, animation_generate=True, openai_key="test-key"),
        animation_registry=runtime_animation.PackRegistry(tmp_path, tmp_path / "bundled"),
        animation_revision=0, _prefetch_epoch=0,
    ), source


def _atlas_bytes():
    image = Image.new("RGBA", (60, 40))
    draw = ImageDraw.Draw(image)
    for index in range(6):
        x, y = (index % 3) * 20, (index // 3) * 20
        draw.rectangle((x + 5, y + 5, x + 14, y + 14), fill=(40 + index, 30, 20, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_opt_in_and_key_rechecked_before_attempt_marker(tmp_path, monkeypatch):
    app, source = _generation_app(tmp_path)
    monkeypatch.setattr(animation, "generate_atlas", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("paid call")))
    app.cfg.animation_generate = False
    assert not runtime_animation.generate_for_subject(app, "SCENE", "bells", "Bells", source)
    app.cfg.animation_generate, app.cfg.openai_key = True, ""
    assert not runtime_animation.generate_for_subject(app, "SCENE", "bells", "Bells", source)
    app.cfg.openai_key = "test-key"
    original = animation.source_png

    def disable_during_preparation(path):
        app.cfg.animation_generate = False
        app._prefetch_epoch += 1
        return original(path)

    monkeypatch.setattr(animation, "source_png", disable_during_preparation)
    assert not runtime_animation.generate_for_subject(app, "SCENE", "bells", "Bells", source)
    assert not (tmp_path / "animation-generation").exists()


def test_uncertain_paid_attempt_blocks_retry_after_restart(tmp_path, monkeypatch):
    app, source = _generation_app(tmp_path)
    calls = []

    def fail_after_dispatch(*args, **kwargs):
        markers = list((tmp_path / "animation-generation/attempts").glob("*.json"))
        assert len(markers) == 1
        assert json.loads(markers[0].read_text())["model"] == app.cfg.animation_model
        calls.append(True)
        raise OSError("uncertain network result")

    monkeypatch.setattr(animation, "generate_atlas", fail_after_dispatch)
    assert not runtime_animation.generate_for_subject(app, "SCENE", "bells", "Bells", source)
    restarted, source = _generation_app(tmp_path)
    assert not runtime_animation.generate_for_subject(restarted, "SCENE", "bells", "Bells", source)
    assert calls == [True]


def test_sequential_still_pipeline_keeps_source_versions_and_rejects_conflicts(tmp_path, monkeypatch):
    app, source = _generation_app(tmp_path)
    calls, sources = [], {"existing": source}

    def still(kind, key, *args, **kwargs):
        sources[key] = tmp_path / f"{key}.png"
        Image.new("RGBA", (16, 12), "green").save(sources[key])
        return sources[key]

    def generate(*args, **kwargs):
        calls.append(kwargs["subject"])
        return _atlas_bytes()

    monkeypatch.setattr(animation, "generate_atlas", generate)
    app.art = SimpleNamespace(cached=lambda kind, key: sources.get(key), load=still)
    app.provider_ready = lambda: True
    app.wanted = lambda since: [("SCENE", key, key, "", "") for key in ("existing", "new")]
    assert runtime_animation.prefetch_once(app, 0, 0)
    first = app.animation_registry.get("SCENE", "existing")
    app.cfg.animation_playback = False
    assert not runtime_animation.prefetch_once(app, 0, 0)
    Image.new("RGBA", (16, 12), "blue").save(source)
    assert runtime_animation.prefetch_once(app, 0, 0)
    current = app.animation_registry.match("SCENE", "existing", source)
    assert current.id != first.id and current.path != first.path
    assert animation.load_pack(first.path) == first
    assert calls == ["existing", "new", "existing"] and app.animation_revision == 3
    conflict = tmp_path / "conflict"
    shutil.copytree(current.path, conflict)
    Image.new("RGBA", (current.width, current.height), "yellow").save(conflict / "frames/000.png")
    app.animation_registry.add(animation.load_pack(conflict))
    assert app.animation_registry.match("SCENE", "existing", source) is None
    assert not runtime_animation.prefetch_once(app, 0, 0)
    assert calls == ["existing", "new", "existing"]


def test_pack_matches_by_pixels_when_png_bytes_differ(tmp_path):
    """The add-on's Pillow may encode the converted PNG differently; the same pixels still find the pack."""
    import io
    from PIL import Image
    from ryciny import runtime_animation
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    img = Image.new("RGBA", (40, 30), (10, 20, 30, 255))
    img.save(a, compress_level=1)
    img.save(b, compress_level=9, optimize=True)
    assert a.read_bytes() != b.read_bytes()
    assert runtime_animation.pixel_digest(a) == runtime_animation.pixel_digest(b)
