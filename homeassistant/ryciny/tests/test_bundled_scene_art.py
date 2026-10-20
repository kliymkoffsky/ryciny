from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from ryciny import api as api_module
from ryciny import art as art_module
from ryciny import config, runtime_animation
from ryciny.api import App
from ryciny.assets import Assets
from ryciny.art import Art
from ryciny.publish import Publisher
from ryciny.store import now_ms


REPO = Path(__file__).resolve().parents[3]
PACK_ROOT = Path(__file__).parents[1] / "app" / "ryciny" / "prepared-animations"
SCENE_KEY, SCENE_FILE = "cat", "scenes/cat.png"


def _app(tmp_path: Path, *, playback: bool) -> App:
    cfg = config.Config(data=tmp_path, assets=REPO, port=0, animation_playback=playback, image_provider="none")
    assets = Assets(tmp_path, REPO)
    at = now_ms()
    journal = {
        "birds": [],
        "planes": [],
        "dogs": [],
        "barks": [],
        "sounds": [{"key": SCENE_KEY, "variant": "", "title": "scene", "subtitle": "", "at": at, "lastAt": at}],
    }
    store = SimpleNamespace(snapshot=lambda: journal, version=1)
    live = SimpleNamespace(level_db=lambda: 0, json=lambda: {})
    return App(cfg, assets, store, live, live, Art(cfg, assets), live)


@contextmanager
def _served(app: App):
    thread = threading.Thread(target=app.serve, args=("127.0.0.1",), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while app.server is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app.server is not None
    try:
        yield f"http://127.0.0.1:{app.server.server_port}/"
    finally:
        app.stop()
        thread.join(5)


def _get(base: str, path: str) -> tuple[int, bytes, object]:
    try:
        with urllib.request.urlopen(base + path) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


def test_bundled_scene_is_still_source_and_animation_poster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, playback=False)
    pack = app.animation_registry.get("SCENE", SCENE_KEY)
    assert pack is not None
    assert app.art.bundled_originals[("SCENE", SCENE_KEY)] == pack.original
    assert ("SCENE", "cat-some-variant") not in app.art.bundled_originals and app.art.cached("SCENE", "cat-some-variant") is None
    original = pack.original.read_bytes()
    provider_calls: list[tuple] = []
    monkeypatch.setattr(art_module.net, "get", lambda *args, **kwargs: provider_calls.append((args, kwargs)))
    monkeypatch.setattr(art_module.net, "post_json", lambda *args, **kwargs: provider_calls.append((args, kwargs)))

    with _served(app) as base:
        query = "kind=SCENE&key=" + SCENE_KEY
        status, body, headers = _get(base, "api/art?cached=1&" + query)
        assert status == 200 and body == original
        assert headers["X-Ryciny-File"] == SCENE_FILE
        status, body, headers = _get(base, "api/art?" + query)
        assert status == 200 and body == original
        assert headers["X-Ryciny-File"] == SCENE_FILE
        assert json.loads(_get(base, "api/animation?" + query)[1]) is None
        status, body, _ = _get(base, "api/plate.png?w=320&h=240")
        assert status == 200 and body.startswith(b"\x89PNG\r\n\x1a\n")
        assert not (tmp_path / "art").exists()
        assert provider_calls == []

        app.cfg.animation_playback = True
        descriptor = json.loads(_get(base, "api/animation?" + query)[1])
        assert descriptor["id"] == pack.id
        assert descriptor["atlas"] == f"api/animations/{pack.id}.png"
        plate_descriptor = json.loads(_get(base, "api/plate-animation?w=800&h=480")[1])
        assert plate_descriptor["placement"] == app._placement(pack, 800, 480)
        status, body, headers = _get(base, "api/art?cached=1&" + query)
        assert status == 200 and body == pack.frames[0].read_bytes()
        assert headers["X-Ryciny-File"] == SCENE_FILE
        assert headers["Cache-Control"] == "no-cache"
        bird_pack = app.animation_registry.get("BIRD", "Turdus merula")
        assert bird_pack is not None
        status, body, headers = _get(base, "api/art?cached=1&kind=BIRD&key=Turdus%20merula")
        assert status == 200 and body == bird_pack.frames[0].read_bytes()
        assert headers["X-Ryciny-File"] == "birds-generated/turdus-merula.png"

        app.cfg.animation_generate = True
        app.cfg.openai_key = "test-key"
        monkeypatch.setattr(runtime_animation.animation, "generate_atlas", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("paid call")))
        assert not runtime_animation.prefetch_once(app, 0, app._prefetch_epoch)
        assert not (tmp_path / "animation-generation").exists()

        custom = app.art.candidates("SCENE", SCENE_KEY)[-1]
        custom.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (8, 8), (220, 20, 20, 255)).save(custom)
        custom_bytes = custom.read_bytes()
        assert app.art.cached("SCENE", SCENE_KEY) == custom
        assert app.animation_pack("SCENE", SCENE_KEY) is None
        assert json.loads(_get(base, "api/animation?" + query)[1]) is None
        status, body, headers = _get(base, "api/art?cached=1&" + query)
        assert status == 200 and body == custom_bytes
        assert headers["X-Ryciny-File"] == SCENE_FILE
        assert pack.original.read_bytes() == original


def test_missing_bundled_root_keeps_custom_art_and_no_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path, playback=True)
    custom = app.art.candidates("SCENE", SCENE_KEY)[-1]
    custom.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), (20, 30, 220, 255)).save(custom)
    missing = tmp_path / "missing-prepared-animations"
    data_pack = tmp_path / "animations" / "SCENE" / SCENE_KEY
    data_pack.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PACK_ROOT / "SCENE" / SCENE_KEY, data_pack)

    class PathAnchor:
        def with_name(self, _name: str) -> Path:
            return missing

    with monkeypatch.context() as boundary:
        boundary.setattr(api_module, "Path", lambda *_args: PathAnchor())
        app._load_animations()
    assert app.art.bundled_originals == {} and app.animation_registry.get("SCENE", SCENE_KEY) is not None
    app.cfg.animation_playback = False

    with _served(app) as base:
        query = "kind=SCENE&key=" + SCENE_KEY
        status, body, headers = _get(base, "api/art?cached=1&" + query)
        assert status == 200 and body == custom.read_bytes()
        assert headers["X-Ryciny-File"] == SCENE_FILE
        assert json.loads(_get(base, "api/animation?" + query)[1]) is None
        custom.unlink()
        status, body, _ = _get(base, "api/art?cached=1&" + query)
        assert status == 404 and json.loads(body) == {"missing": True}


def test_public_exporter_uses_bundled_scene_original_and_atlas(tmp_path: Path) -> None:
    app = _app(tmp_path, playback=False)
    pack = app.animation_registry.get("SCENE", SCENE_KEY)
    assert pack is not None
    publisher = Publisher(app.cfg, app)
    publisher.sent = set()
    uploads: list[tuple[str, bytes, str]] = []
    publisher._put = lambda path, body, ctype: uploads.append((path, body, ctype)) or b""
    state = {"birds": [], "planes": [], "sounds": [{"art": SCENE_KEY}]}

    publisher._art(state)
    publisher._animations(state)

    art_upload = next(item for item in uploads if item[0].startswith("/ingest/art?"))
    atlas_upload = next(item for item in uploads if item[0].startswith("/ingest/anim?") and "poster" not in item[0])
    assert art_upload[1] == pack.original.read_bytes()
    assert atlas_upload[1] == app.animation_registry.atlas(pack.id)
    assert state["animations"][f"SCENE:{SCENE_KEY}"]["id"] == pack.id
