"""HTTP API the Android app reads in "Home Assistant" mode, plus a page with the plate for any browser."""

from __future__ import annotations

import datetime as dt
import base64
import hashlib
import json
import logging
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from pathlib import Path

from . import __version__, animation, config, dsp, plate, runtime_animation, stats, store, tvplate
from .frame import Frame

# Sounds of animals (sounds.json keys): the only sounds the TV shows, besides birds and dogs.
ANIMAL_SOUNDS = {"cat", "rooster", "horse", "cow", "sheep", "goat", "pig", "frog", "cricket", "bee", "mosquito"}
from .store import now_ms

WEB = Path(__file__).parent / "web"

log = logging.getLogger(__name__)


class App:
    def __init__(self, cfg, assets, store, sky, rails, art, live, listener=None) -> None:
        self.cfg, self.assets, self.store, self.sky, self.rails, self.art, self.live = cfg, assets, store, sky, rails, art, live
        self.listener = listener
        self.frame = Frame(cfg, cfg.data / "frame.json")
        self.wiki = tvplate.Wiki(cfg.data)
        self.sounds = {s["key"]: s for s in json.loads(assets.text("sounds.json"))["sounds"]}
        self.breeds = json.loads(assets.text("dog_breeds.json"))
        self.fonts = (str(assets.path("garamond.ttf")), str(assets.path("garamond_italic.ttf")))
        self.animation_revision = 0
        self._prefetch_epoch = 0
        self.server = None
        self._load_animations()

    def current_plate(self) -> dict | None:
        """Select one current plate for both the static background and animation descriptor."""

        journal = self.store.snapshot()
        current = plate.newest(journal, self.sounds, self.cfg.lookback_hours, self.sound_on)
        dog = self.tv_dog(journal, self.cfg.lookback_hours)
        return dog if dog and (current is None or dog["at"] > current["at"]) else current

    def _load_animations(self) -> None:
        """Load once at startup; generation registers only its newly published pack."""

        fallback = Path(__file__).with_name("prepared-animations")
        self.animation_registry = runtime_animation.PackRegistry(self.cfg.data, fallback)
        self.art.bundled_originals.clear()
        bundled_root = fallback.resolve()
        # Every bundled pack's original: used where no engraving exists yet, and instead of the add-on's own one when
        # prefer_bundled_art is on (so the prepared animation matches it).
        for kind, key in list(self.animation_registry.bindings):
            pack = self.animation_registry.get(kind, key)
            if pack is None or pack.kind != kind or pack.key != key:
                continue
            try:
                pack.path.relative_to(bundled_root)
            except ValueError:
                continue
            self.art.bundled_originals[(kind, key)] = pack.original

    def _settings_changed(self, before: dict, after: dict) -> None:
        runtime_animation.settings_changed(self, before, after)
        if (before["lat"], before["lon"]) != (after["lat"], after["lon"]):
            self.sky.location_changed()
            self.rails.location_changed()

    prefetch_once = runtime_animation.prefetch_once
    prefetch = runtime_animation.prefetch

    @staticmethod
    def _dimensions(query: dict, default: tuple[int, int], max_side: int = 4096) -> tuple[int, int]:
        """Parse bounded output dimensions before rendering or encoding a background."""

        try:
            width, height = int(query.get("w", default[0])), int(query.get("h", default[1]))
        except (TypeError, ValueError) as error:
            raise ValueError("w and h must be integers") from error
        if width < 1 or height < 1 or width > max_side or height > max_side or width * height > 16_000_000:
            raise ValueError("w and h are outside the render limits")
        return width, height

    @staticmethod
    def _placement(pack, width: int, height: int) -> list[int]:
        """Match plate.render's engraving box so only the subject layer moves."""

        scale = min(width * 0.64 / pack.width, height * 0.59 / pack.height)
        drawn_width = max(1, round(pack.width * scale))
        drawn_height = max(1, round(pack.height * scale))
        return [round((width - drawn_width) / 2), round(height * 0.72 - drawn_height), drawn_width, drawn_height]

    def animation_pack(self, kind: str, key: str) -> animation.Pack | None:
        if not self.cfg.animation_playback:
            return None
        return self.animation_registry.match(kind, key, self.art.cached(kind, key))

    def _animation_descriptor(self, pack, width: int, height: int, background: bool, current: dict | None = None) -> dict | None:
        """Build the small worker-facing descriptor from one validated immutable pack."""

        descriptor = {
            "id": pack.id,
            "subject": [pack.kind, pack.key],
            "width": width,
            "height": height,
            "frameMs": pack.frame_ms,
            "atlas": f"api/animations/{pack.id}.png",
        }
        if background:
            if current is None or current["kind"] != pack.kind or current["key"] != pack.key:
                return None
            descriptor["placement"] = self._placement(pack, width, height)
            body = plate.render(current, None, self.fonts, width, height)
            descriptor["background"] = "data:image/png;base64," + base64.b64encode(body).decode("ascii")
        return descriptor

    def plate_animation_descriptor(self, width: int, height: int) -> dict | None:
        """Return the selected plate's animation and blank fixed paper background."""

        current = self.current_plate()
        if current is None:
            return None
        pack = self.animation_pack(current["kind"], current["key"])
        return self._animation_descriptor(pack, width, height, True, current) if pack is not None else None

    def element_animation_descriptor(self, kind: str, key: str) -> dict | None:
        """Return an exact-key thumbnail descriptor without rendering a plate background."""

        pack = self.animation_pack(kind, key)
        if pack is None:
            return None
        return self._animation_descriptor(pack, pack.width, pack.height, False)

    def sound_on(self, key: str) -> bool:
        s = self.sounds.get(key, {})
        if key in self.cfg.sounds_off:
            return False
        if key in self.cfg.sounds_on:
            return True
        return s.get("enabled", True)

    def wanted(self, since: int) -> list[tuple]:
        """Return exact still identities for observations seen since a bounded cursor."""
        j = self.store.snapshot()
        dogs = {d["id"]: d for d in j["dogs"]}
        out = [("BIRD", b["sci"], b["sci"], "", "") for b in j["birds"] if b["lastAt"] >= since]
        for p in j["planes"]:
            if p["heard"] and p["lastAt"] >= since:
                key = f"{p.get('typeCode') or p['title']}-{p.get('airlineIcao') or p['airline'] or 'plain'}"
                out.append(("PLANE", key, p["title"], p["airline"], ""))
        for e in j["sounds"]:
            s = self.sounds.get(e["key"])
            if s and e["lastAt"] >= since and self.sound_on(e["key"]):
                out.append(("SCENE", f"{e['key']}-{e['variant']}" if e["variant"] else e["key"], s["now"], "", s["prompt"]))
        for b in j["barks"]:
            if b["lastAt"] >= since:
                d = dogs.get(b.get("dogId"))
                if d:
                    out.append(("DOG", d["breed"], d["breedEn"], "", ""))
                else:
                    m = self.breeds[{"mały": 0, "duży": 2}.get(b.get("size"), 1)]
                    out.append(("DOG", m["pl"], m["en"], "", ""))
        return list(dict.fromkeys(out))

    # --- Samsung The Frame ---------------------------------------------------------------------------

    def tv_plate(self, wait: bool) -> tuple[bytes, str, str]:
        """The TV picture now: (jpeg, identity, title). A wall should not go blank after a quiet night: a week back."""
        # Only animals on the wall: birds, animal sounds and dogs; no planes, trains, weather or people.
        j = self.store.snapshot()
        current = plate.newest({**j, "planes": []}, self.sounds, 7 * 24, lambda k: k in ANIMAL_SOUNDS and self.sound_on(k))
        dog = self.tv_dog(j)
        if dog and (current is None or dog["at"] > current["at"]):
            current = dog
        if current:
            current["lines"] = [x for x in current["lines"] if x]
        engraving, about = None, ""
        if current:
            f = self.art.load(current["kind"], current["key"], current["subject"], current.get("airline", ""),
                              current.get("prompt", ""), wait=wait)
            engraving = Image.open(f) if f else None
            if current["kind"] == "BIRD":
                about = self.wiki.about(current["key"])
        st = stats.compute(j, self.store.history_snapshot(), self.sounds, self.sound_on)
        start = int(dt.datetime.now(store.ZONE).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        st["animals"] = {
            "barksToday": sum(1 for b in j["barks"] if b["lastAt"] >= start),
            "kindsToday": len({e["key"] for e in j["sounds"] if e["key"] in ANIMAL_SOUNDS and self.sound_on(e["key"]) and e["lastAt"] >= start}),
        }
        identity = json.dumps([current and current["kind"], current and current["key"], current and current["title"],
                               current and current["lines"][:2]], ensure_ascii=False)
        # Engravings beside the birds in the statistics (fetched once each; birds' plates cost nothing).
        thumbs = {}
        for b in st["birds"]["top"][:5] + st["birds"]["chanceNow"][:3]:
            f = self.art.cached("BIRD", b["sci"]) or (self.art.load("BIRD", b["sci"], b["sci"], wait=wait) if wait else None)
            if f and b["sci"] not in thumbs:
                try:
                    thumbs[b["sci"]] = Image.open(f)
                except OSError:
                    pass
        jpeg = tvplate.render(current, engraving, about, st, self.fonts, thumbs)
        return jpeg, identity, current["title"] if current else "cisza"

    def tv_dog(self, j: dict, lookback_hours: int = 7 * 24) -> dict | None:
        """The newest bark of the last week as a plate: the dog by name if tagged, else a mongrel of its size."""
        since = now_ms() - lookback_hours * 3600_000
        barks = [b for b in j["barks"] if b["lastAt"] >= since]
        if not barks:
            return None
        b = max(barks, key=lambda x: x["lastAt"])
        dog = next((d for d in j["dogs"] if d["id"] == b.get("dogId")), None)
        if dog:
            key, subject, title = dog["breed"], dog["breedEn"], f"{dog['name']} szczekał"
        else:
            m = self.breeds[{"mały": 0, "duży": 2}.get(b.get("size"), 1)]
            key, subject, title = m["pl"], m["en"], "Szczekał pies" + (f", raczej {b['size']}" if b.get("size") not in (None, "?") else "")
        return {"kind": "DOG", "key": key, "subject": subject, "title": title, "at": b["at"],
                "lines": [line for line in (dog["breed"] if dog else "", f"{plate.hhmm(b['at'])} · {b['count']}×") if line]}

    def frame_loop(self) -> None:
        """Sends the TV plate when what is heard changes (at most every frame_every_min), and every 30 min for the statistics."""
        while True:
            time.sleep(60)
            if not self.cfg.frame_on or not self.cfg.frame_host.strip() or time.time() < self.frame.next_try:
                continue
            try:
                since = time.time() - self.frame.sent_at
                jpeg, identity, title = self.tv_plate(wait=True)
                if (identity != self.frame.identity and since >= self.cfg.frame_every_min * 60) or since >= 30 * 60:
                    self.frame.push(jpeg, identity, title)
            except Exception:  # noqa: BLE001
                log.exception("frame loop")

    def provider_ready(self) -> bool:
        c = self.cfg
        return {"openai": c.openai_key, "gemini": c.gemini_key, "openrouter": c.openrouter_key}.get(c.image_provider, "") != ""

    def serve(self, host: str = "0.0.0.0") -> None:
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = f"Ryciny/{__version__}"

            def log_message(self, fmt, *args):
                log.debug("%s %s", self.address_string(), fmt % args)

            def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, obj, code: int = 200, headers: dict | None = None) -> None:
                self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", headers)

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):  # noqa: N802
                url = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                path = url.path.rstrip("/") or "/"
                try:
                    if path in ("/", "/plate"):
                        return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8", {"Cache-Control": "no-cache"})
                    if path in ("/animation.js", "/location.js"):
                        return self._send(200, (WEB / path[1:]).read_bytes(), "application/javascript; charset=utf-8", {"Cache-Control": "no-cache"})
                    m = re.fullmatch(r"/fonts/(garamond|garamond_italic)\.ttf", path)
                    if m:
                        return self._send(200, app.assets.path(m[1] + ".ttf").read_bytes(), "font/ttf", {"Cache-Control": "max-age=86400"})
                    if path == "/api/sounds":
                        return self._json([{**s, "on": app.sound_on(s["key"])} for s in app.sounds.values()])
                    if path == "/api/breeds":
                        return self._json(json.loads(app.assets.text("dog_breeds.json")))
                    if path == "/api/settings":
                        return self._json({**config.runtime(app.cfg),
                                           "providerReady": app.provider_ready(),
                                           "animationKeyReady": bool(app.cfg.openai_key.strip()),
                                           "version": __version__})
                    if path == "/api/health":
                        return self._json({"ok": True, "version": __version__})
                    if path == "/api/journal":
                        etag = f'"{app.store.version}"'
                        if self.headers.get("If-None-Match") == etag:
                            return self._send(304, b"", "application/json", {"ETag": etag})
                        return self._json(app.store.snapshot(), headers={"ETag": etag})
                    if path == "/api/live":
                        mic = {"db": app.live.level_db(), "peak": round(app.listener.peak, 3) if app.listener else 0,
                               "has": bool(app.listener and app.listener.last is not None)}
                        return self._json({"version": app.store.version, "live": app.live.json(), "sky": app.sky.state(),
                                           "rails": app.rails.state(), "artError": app.art.error, "mic": mic,
                                           "animationRevision": app.animation_revision})
                    if path == "/api/tv.jpg":
                        jpeg, _, _ = app.tv_plate(wait=False)
                        return self._send(200, jpeg, "image/jpeg", {"Cache-Control": "no-store"})
                    if path == "/api/frame/mode":
                        try:
                            return self._json({"artMode": app.frame.art_mode()})
                        except Exception as e:  # noqa: BLE001
                            return self._json({"error": str(e)}, 502)
                    if path == "/api/frame":
                        return self._json({"status": app.frame.status, "paired": bool(app.frame.state.get("token")),
                                           "sentAt": int(app.frame.sent_at * 1000), "on": app.cfg.frame_on, "host": app.cfg.frame_host})
                    if path == "/api/stats":
                        return self._json(stats.compute(app.store.snapshot(), app.store.history_snapshot(), app.sounds, app.sound_on,
                                                        best=app.store.best_snapshot()))
                    if path == "/api/mic.wav":
                        last = app.listener.last if app.listener else None
                        if last is None:
                            return self._json({"error": "jeszcze nic nie nagrano"}, 404)
                        return self._send(200, dsp.wav_bytes(last, 48_000, normalize=False), "audio/wav", {"Cache-Control": "no-store"})
                    if path == "/api/plate-animation":
                        try:
                            width, height = app._dimensions(q, (1600, 900))
                        except ValueError as error:
                            return self._json({"error": str(error)}, 400)
                        return self._json(app.plate_animation_descriptor(width, height), headers={"Cache-Control": "no-store"})
                    if path == "/api/animation":
                        kind, key = q.get("kind", ""), q.get("key", "")
                        if (kind not in animation.KINDS or not key or len(key.encode("utf-8")) > animation.MAX_KEY_BYTES or
                                any(ord(character) < 32 or ord(character) == 127 for character in key)):
                            return self._json({"error": "kind and key are invalid"}, 400)
                        return self._json(app.element_animation_descriptor(kind, key), headers={"Cache-Control": "no-store"})
                    m = re.fullmatch(r"/api/animations/([0-9a-f]{64})\.png", path)
                    if m:
                        atlas = app.animation_registry.atlas(m[1])
                        return self._send(200, atlas, "image/png", {"Cache-Control": "public, max-age=31536000, immutable"}) if atlas is not None else self._json({"error": "atlas not found"}, 404)
                    if path == "/api/art":
                        kind, key = q.get("kind", ""), q.get("key", "")
                        if kind not in ("BIRD", "PLANE", "DOG", "SCENE") or not key:
                            return self._json({"error": "kind and key required"}, 400)
                        pack = app.animation_pack(kind, key)
                        if pack is not None:
                            poster = runtime_animation.read_image(pack.frames[0], animation.MAX_FRAME_BYTES)
                            if poster is not None:
                                rel = app.art.candidates(kind, key)[-1].relative_to(app.art.root).as_posix()
                                return self._send(200, poster, "image/png", {
                                    "X-Ryciny-File": rel,
                                    "Cache-Control": "no-cache",
                                })
                        if q.get("cached") == "1" and kind != "BIRD":
                            # Thumbnails: only what is already drawn; a paid picture is never ordered by scrolling.
                            found = app.art.cached(kind, key)
                            if found is None:
                                return self._json({"missing": True}, 404)
                        else:
                            found = app.art.load(kind, key, q.get("subject", key), q.get("airline", ""), q.get("prompt", ""), wait=False)
                        if found is None:
                            return self._json({"pending": True}, 202)
                        bundled = app.art.bundled_originals.get((kind, key))
                        if bundled is not None and found == bundled:
                            rel = app.art.candidates(kind, key)[-1].relative_to(app.art.root).as_posix()
                        else:
                            rel = found.relative_to(app.art.root).as_posix()
                        ctype = "image/webp" if found.suffix == ".webp" else "image/png"
                        return self._send(200, found.read_bytes(), ctype, {"X-Ryciny-File": rel, "Cache-Control": "max-age=31536000"})
                    m = re.fullmatch(r"/api/best/([0-9a-f]{8}\.(?:wav|mp3))", path)
                    if m:
                        f = app.store.best_dir / m[1]
                        return self._send(200, f.read_bytes(), "audio/mpeg" if f.suffix == ".mp3" else "audio/wav") if f.exists() else self._json({"error": "no clip"}, 404)
                    m = re.fullmatch(r"/api/clips/([0-9a-f]{8}\.(?:wav|mp3))", path)
                    if m:
                        f = app.store.clips / m[1]
                        return self._send(200, f.read_bytes(), "audio/mpeg" if f.suffix == ".mp3" else "audio/wav") if f.exists() else self._json({"error": "no clip"}, 404)
                    if path == "/api/plate.png":
                        try:
                            w, h = app._dimensions(q, (800, 480))
                        except ValueError as error:
                            return self._json({"error": str(error)}, 400)
                        palette = q.get("palette", "full")
                        current = app.current_plate()
                        pack = app.animation_pack(current["kind"], current["key"]) if current else None
                        identity = [current, w, h, palette, pack.id if pack else None, now_ms() // 60_000]
                        etag = '"' + hashlib.sha1(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16] + '"'
                        if self.headers.get("If-None-Match") == etag:
                            return self._send(304, b"", "image/png", {"ETag": etag})
                        engraving = None
                        if current:
                            f = pack.frames[0] if pack else app.art.load(
                                current["kind"], current["key"], current["subject"], current.get("airline", ""),
                                current.get("prompt", ""), wait=False)
                            engraving = Image.open(f) if f else None
                        body = plate.render(current, engraving, app.fonts, w, h, palette)
                        return self._send(200, body, "image/png", {"ETag": etag})
                    return self._json({"error": "not found"}, 404)
                except Exception as e:  # noqa: BLE001
                    log.exception("GET %s", self.path)
                    return self._json({"error": str(e)}, 500)

            do_HEAD = do_GET

            def do_POST(self):  # noqa: N802
                path = urllib.parse.urlparse(self.path).path.rstrip("/")
                try:
                    body = self._body()
                    m = re.fullmatch(r"/api/barks/([0-9a-f-]+)/tag", path)
                    if m:
                        ok = app.store.tag_bark(m[1], body.get("dogId", ""))
                        return self._json({"ok": ok}, 200 if ok else 404)
                    if path == "/api/dogs":
                        return self._json({"id": app.store.new_dog(body["name"], body["breed"], body["breedEn"], body.get("id"))})
                    if path == "/api/clips/recheck":
                        a = app.listener.analyzer if app.listener else None
                        return self._json({"public": a.recheck_public() if a else 0})
                    if path == "/api/frame/push":
                        jpeg, identity, title = app.tv_plate(wait=True)
                        app.frame.push(jpeg, identity, title)
                        return self._json({"status": app.frame.status})
                    if path == "/api/frame/restore":
                        app.frame.restore()
                        return self._json({"status": app.frame.status})
                    if path == "/api/import":
                        app.store.merge_import(body)
                        return self._json({"ok": True})
                    return self._json({"error": "not found"}, 404)
                except Exception as e:  # noqa: BLE001
                    log.exception("POST %s", self.path)
                    return self._json({"error": str(e)}, 500)

            def do_PUT(self):  # noqa: N802
                if urllib.parse.urlparse(self.path).path.rstrip("/") == "/api/settings":
                    try:
                        body = self._body()
                        with config.SETTINGS_LOCK:
                            before = config.runtime(app.cfg)
                            result = config.update(app.cfg, body)
                            app._settings_changed(before, result)
                        return self._json(result)
                    except (TypeError, ValueError) as error:
                        return self._json({"error": str(error)}, 400)
                    except OSError:
                        log.exception("saving runtime settings")
                        return self._json({"error": "could not save settings"}, 500)
                m = re.fullmatch(r"/api/dogs/([0-9a-f-]+)", urllib.parse.urlparse(self.path).path.rstrip("/"))
                if not m:
                    return self._json({"error": "not found"}, 404)
                b = self._body()
                app.store.edit_dog(m[1], b["name"], b["breed"], b["breedEn"])
                return self._json({"ok": True})

            def do_DELETE(self):  # noqa: N802
                u = urllib.parse.urlparse(self.path)
                if u.path.rstrip("/") == "/api/sounds":
                    q = dict(urllib.parse.parse_qsl(u.query))
                    n = app.store.delete_sounds(q.get("key", ""), int(q.get("since", 0)), int(q.get("until", 2**62)))
                    return self._json({"deleted": n})
                m = re.fullmatch(r"/api/dogs/([0-9a-f-]+)", u.path.rstrip("/"))
                if not m:
                    return self._json({"error": "not found"}, 404)
                app.store.delete_dog(m[1])
                return self._json({"ok": True})

        server = ThreadingHTTPServer((host, self.cfg.port), Handler)
        server.daemon_threads = True
        self.server = server
        log.info("Ryciny %s on :%d", __version__, self.cfg.port)
        try:
            server.serve_forever()
        finally:
            server.server_close()

    def stop(self) -> None:
        """Stop an embedded test server without affecting production workers."""

        if self.server is not None:
            self.server.shutdown()
