"""HTTP API the Android app reads in "Home Assistant" mode, plus a page with the plate for any browser."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from pathlib import Path

from . import __version__, config, dsp, plate
from .store import now_ms

WEB = Path(__file__).parent / "web"

log = logging.getLogger(__name__)




class App:
    def __init__(self, cfg, assets, store, sky, rails, art, live, listener=None) -> None:
        self.cfg, self.assets, self.store, self.sky, self.rails, self.art, self.live = cfg, assets, store, sky, rails, art, live
        self.listener = listener
        self.sounds = {s["key"]: s for s in json.loads(assets.text("sounds.json"))["sounds"]}
        self.fonts = (str(assets.path("garamond.ttf")), str(assets.path("garamond_italic.ttf")))

    def sound_on(self, key: str) -> bool:
        s = self.sounds.get(key, {})
        if key in self.cfg.sounds_off:
            return False
        if key in self.cfg.sounds_on:
            return True
        return s.get("enabled", True)

    def wanted(self, since: int) -> list[tuple]:
        """Engravings the journal needs for entries seen since [since]: heard planes, sounds that are on, barks."""
        j = self.store.snapshot()
        dogs = {d["id"]: d for d in j["dogs"]}
        breeds = json.loads(self.assets.text("dog_breeds.json"))
        out = []
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
                    m = breeds[{"mały": 0, "duży": 2}.get(b.get("size"), 1)]
                    out.append(("DOG", m["pl"], m["en"], "", ""))
        return list(dict.fromkeys(out))

    def prefetch(self) -> None:
        """Orders each missing engraving once, right after the event, so the Journal shows it without anyone watching."""
        since, version = now_ms() - self.cfg.lookback_hours * 3600_000, -1
        while True:
            time.sleep(5)
            if self.store.version == version or not self.provider_ready():
                continue
            version, started = self.store.version, now_ms()
            for kind, key, subject, airline, prompt in self.wanted(since):
                if self.art.cached(kind, key) is None:
                    log.info("art: ordering %s %s", kind, key)
                    self.art.load(kind, key, subject, airline, prompt, wait=True)
            since = started - 60_000

    def provider_ready(self) -> bool:
        c = self.cfg
        return {"openai": c.openai_key, "gemini": c.gemini_key, "openrouter": c.openrouter_key}.get(c.image_provider, "") != ""

    def serve(self) -> None:
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
                    m = re.fullmatch(r"/fonts/(garamond|garamond_italic)\.ttf", path)
                    if m:
                        return self._send(200, app.assets.path(m[1] + ".ttf").read_bytes(), "font/ttf", {"Cache-Control": "max-age=86400"})
                    if path == "/api/sounds":
                        return self._json([{**s, "on": app.sound_on(s["key"])} for s in app.sounds.values()])
                    if path == "/api/breeds":
                        return self._json(json.loads(app.assets.text("dog_breeds.json")))
                    if path == "/api/settings":
                        return self._json({**config.runtime(app.cfg), "lat": app.cfg.lat, "lon": app.cfg.lon,
                                           "providerReady": app.provider_ready(), "version": __version__})
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
                                           "rails": app.rails.state(), "artError": app.art.error, "mic": mic})
                    if path == "/api/mic.wav":
                        last = app.listener.last if app.listener else None
                        if last is None:
                            return self._json({"error": "jeszcze nic nie nagrano"}, 404)
                        return self._send(200, dsp.wav_bytes(last, 48_000, normalize=False), "audio/wav", {"Cache-Control": "no-store"})
                    if path == "/api/art":
                        kind, key = q.get("kind", ""), q.get("key", "")
                        if kind not in ("BIRD", "PLANE", "DOG", "SCENE") or not key:
                            return self._json({"error": "kind and key required"}, 400)
                        if q.get("cached") == "1" and kind != "BIRD":
                            # Thumbnails: only what is already drawn; a paid picture is never ordered by scrolling.
                            found = app.art.cached(kind, key)
                            if found is None:
                                return self._json({"missing": True}, 404)
                        else:
                            found = app.art.load(kind, key, q.get("subject", key), q.get("airline", ""), q.get("prompt", ""), wait=False)
                        if found is None:
                            return self._json({"pending": True}, 202)
                        rel = found.relative_to(app.art.root).as_posix()
                        ctype = "image/webp" if found.suffix == ".webp" else "image/png"
                        return self._send(200, found.read_bytes(), ctype, {"X-Ryciny-File": rel, "Cache-Control": "max-age=31536000"})
                    m = re.fullmatch(r"/api/clips/([0-9a-f]{8}\.wav)", path)
                    if m:
                        f = app.store.clips / m[1]
                        return self._send(200, f.read_bytes(), "audio/wav") if f.exists() else self._json({"error": "no clip"}, 404)
                    if path == "/api/plate.png":
                        w, h = int(q.get("w", 800)), int(q.get("h", 480))
                        palette = q.get("palette", "full")
                        current = plate.newest(app.store.snapshot(), app.sounds, app.cfg.lookback_hours, app.sound_on)
                        etag = '"' + hashlib.sha1(json.dumps([current, w, h, palette], sort_keys=True).encode()).hexdigest()[:16] + '"'
                        if self.headers.get("If-None-Match") == etag:
                            return self._send(304, b"", "image/png", {"ETag": etag})
                        engraving = None
                        if current:
                            f = app.art.load(current["kind"], current["key"], current["subject"], current.get("airline", ""),
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
                    if path == "/api/import":
                        app.store.merge_import(body)
                        return self._json({"ok": True})
                    return self._json({"error": "not found"}, 404)
                except Exception as e:  # noqa: BLE001
                    log.exception("POST %s", self.path)
                    return self._json({"error": str(e)}, 500)

            def do_PUT(self):  # noqa: N802
                if urllib.parse.urlparse(self.path).path.rstrip("/") == "/api/settings":
                    return self._json(config.update(app.cfg, self._body()))
                m = re.fullmatch(r"/api/dogs/([0-9a-f-]+)", urllib.parse.urlparse(self.path).path.rstrip("/"))
                if not m:
                    return self._json({"error": "not found"}, 404)
                b = self._body()
                app.store.edit_dog(m[1], b["name"], b["breed"], b["breedEn"])
                return self._json({"ok": True})

            def do_DELETE(self):  # noqa: N802
                m = re.fullmatch(r"/api/dogs/([0-9a-f-]+)", urllib.parse.urlparse(self.path).path.rstrip("/"))
                if not m:
                    return self._json({"error": "not found"}, 404)
                app.store.delete_dog(m[1])
                return self._json({"ok": True})

        server = ThreadingHTTPServer(("0.0.0.0", self.cfg.port), Handler)
        log.info("Ryciny %s on :%d", __version__, self.cfg.port)
        server.serve_forever()
