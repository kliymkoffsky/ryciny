"""Optional public page: pushes a trimmed journal and the engravings to the Cloudflare Worker in public-site/.

Only what is fine for anyone to see goes out: birds, heard planes and neighbourhood sounds. No dogs, no speech,
children, music or doorbell, no coordinates and no distances (those would place the house). Audio: the 9 s
recording of each bird and sound entry, only when YAMNet heard no people and no music in it; the Worker drops it
after CLIP_DAYS.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import time
import urllib.parse
import urllib.request

from PIL import Image

from . import config, stats
from .store import local, now_ms

log = logging.getLogger(__name__)

PRIVATE_SOUNDS = {"talking", "children", "music", "doorbell"}
EVERY_S = 240  # KV on the free plan takes 1000 writes a day: the state, plus one write per new recording
KEEP_DAYS = 30
CLIP_DAYS = 14


def public_state(journal: dict, sounds: dict, sound_on, station_title: str = config.DEFAULT_STATION_TITLE) -> dict:
    title = config._validated_station_title(station_title)
    since = now_ms() - KEEP_DAYS * 86_400_000
    birds = [{"name": b["name"], "sci": b["sci"], "conf": round(b["conf"], 2), "count": b["count"], "lastAt": b["lastAt"]}
             for b in journal["birds"] if b["lastAt"] >= since]
    # Every entry's recording, when YAMNet found no people and no music in it.
    clip_since = now_ms() - CLIP_DAYS * 86_400_000
    audio = {(b["sci"], b["lastAt"]): b["clip"] for b in journal["birds"]
             if b.get("clip") and b.get("clipPublic") and b["lastAt"] >= clip_since}
    for b in birds:
        if (b["sci"], b["lastAt"]) in audio:
            b["audio"] = audio[(b["sci"], b["lastAt"])]
    planes = [{"title": p["title"], "airline": p["airline"], "callsign": p["callsign"], "route": p["route"],
               "at": p["at"], "lastAt": p["lastAt"], "altM": p.get("minAltM"), "art": plane_key(p)}
              for p in journal["planes"] if p["heard"] and p["lastAt"] >= since]
    out_sounds = []
    for e in journal["sounds"]:
        s = sounds.get(e["key"])
        if not s or e["key"] in PRIVATE_SOUNDS or not sound_on(e["key"]) or e["lastAt"] < since:
            continue
        out_sounds.append({"key": e["key"], "label": s["past"], "title": e["title"], "subtitle": e["subtitle"], "count": e["count"],
                           "at": e["at"], "lastAt": e["lastAt"], "art": f"{e['key']}-{e['variant']}" if e["variant"] else e["key"]})
        if e.get("clip") and e.get("clipPublic") and e["lastAt"] >= clip_since:
            out_sounds[-1]["audio"] = e["clip"]
    return {"updatedAt": now_ms(), "title": title, "birds": birds, "planes": planes, "sounds": out_sounds}


def plane_key(p: dict) -> str:
    return f"{p.get('typeCode') or p['title']}-{p.get('airlineIcao') or p['airline'] or 'plain'}"


class Publisher:
    def __init__(self, cfg, app) -> None:
        self.cfg, self.app = cfg, app
        self.sent: set[str] | None = None
        try:  # which version of each engraving the page has (content hash), so a changed one goes up again
            self.art_sent: dict[str, str] = json.loads((cfg.data / "published_art.json").read_text())
        except (OSError, ValueError):
            self.art_sent = {}
        self.error: str | None = None

    def _put(self, path: str, body: bytes, ctype: str) -> bytes:
        req = urllib.request.Request(self.cfg.public_url.rstrip("/") + path, data=body, method="PUT",
                                     headers={"Authorization": f"Bearer {self.cfg.public_token}", "Content-Type": ctype,
                                              "User-Agent": "ryciny-addon"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def run(self) -> None:
        success_key: tuple[int, str] | None = None
        while True:
            time.sleep(EVERY_S)
            if not self.cfg.public_url or not self.cfg.public_token:
                continue
            try:
                with config.SETTINGS_LOCK:
                    # Capture before network work so a title changed mid-publish remains a pending key next round.
                    title = config._validated_station_title(self.cfg.station_title)
                    publication_key = (self.app.store.version, title)
                if publication_key == success_key:
                    continue
                if self.sent is None:
                    self.sent = set(json.loads(self._put("/ingest/has", b"", "text/plain")))
                journal = self.app.store.snapshot()
                state = public_state(journal, self.app.sounds, self.app.sound_on, title)
                st = stats.compute(journal, self.app.store.history_snapshot(), self.app.sounds, self.app.sound_on, PRIVATE_SOUNDS,
                                   best=self.app.store.best_snapshot())
                # Only best recordings without people or music go out; they stay (no 14-day expiry).
                st["birds"]["best"] = {s: {k: v for k, v in b.items() if k != "public"} for s, b in st["birds"]["best"].items() if b["public"]}
                state["stats"] = st
                self._art(state)
                self._clips(state)
                self._best(state)
                self._animations(state)
                state["artv"] = self.art_sent  # versions in the engravings' URLs: a replaced one is not served from cache
                self._put("/ingest/state", json.dumps(state, ensure_ascii=False).encode(), "application/json")
                success_key, self.error = publication_key, None
            except Exception as e:  # noqa: BLE001 - try again next round
                self.error = f"strona publiczna: {e}"
                log.warning("publish: %s", e)

    def _clips(self, state: dict) -> None:
        for b in state["birds"] + state["sounds"]:
            name = b.get("audio")
            if not name or f"clip:{name}" in self.sent:
                continue
            f = self.app.store.clips / name
            if not f.exists():
                b.pop("audio")
                continue
            self._put("/ingest/clip?" + urllib.parse.urlencode({"name": name}), f.read_bytes(), "audio/mpeg" if f.suffix == ".mp3" else "audio/wav")
            self.sent.add(f"clip:{name}")
            log.info("publish: clip %s %s", b.get("sci") or b.get("key"), name)

    def _best(self, state: dict) -> None:
        best = state["stats"]["birds"]["best"]
        for sci, b in list(best.items()):
            name = b["clip"]
            if f"clip:{name}" in self.sent:
                continue
            f = self.app.store.best_dir / name
            if not f.exists():
                best.pop(sci)
                continue
            self._put("/ingest/clip?" + urllib.parse.urlencode({"name": name, "keep": "1"}), f.read_bytes(), "audio/mpeg" if f.suffix == ".mp3" else "audio/wav")
            self.sent.add(f"clip:{name}")
            log.info("publish: best clip %s %s", sci, name)

    def _animations(self, state: dict) -> None:
        """Moving engravings: each prepared six-frame strip goes up once; the state says which subject has one."""
        wanted = [("BIRD", b["sci"]) for b in state["birds"]] + [("PLANE", p["art"]) for p in state["planes"]] + \
                 [("SCENE", s["art"]) for s in state["sounds"]]
        anims = {}
        for kind, key in dict.fromkeys(wanted):
            pack = self.app.animation_registry.match(kind, key, self.app.art.cached(kind, key))
            if pack is None:
                continue
            if f"anim:{pack.id}" not in self.sent:
                sprite = self.app.animation_registry.atlas(pack.id)
                if sprite is None:
                    continue
                self._put("/ingest/anim?" + urllib.parse.urlencode({"id": pack.id}), sprite, "image/png")
                self.sent.add(f"anim:{pack.id}")
            if f"animp:{pack.id}" not in self.sent:
                # The still for small engravings: exactly frame one, so hovering does not make the bird jump.
                with Image.open(pack.frames[0]) as first:
                    poster = first.convert("RGBA")
                    poster.thumbnail((360, 360))
                    buf = io.BytesIO()
                    poster.save(buf, "PNG", optimize=True)
                self._put("/ingest/anim?" + urllib.parse.urlencode({"id": pack.id, "poster": "1"}), buf.getvalue(), "image/png")
                self.sent.add(f"animp:{pack.id}")
                log.info("publish: animation %s %s", kind, key)
            anims[f"{kind}:{key}"] = {"id": pack.id, "w": pack.width, "h": pack.height, "ms": pack.frame_ms}
        state["animations"] = anims

    def _save_art_sent(self) -> None:
        (self.cfg.data / "published_art.json").write_text(json.dumps(self.art_sent))

    def _art(self, state: dict) -> None:
        wanted = [("BIRD", b["sci"]) for b in state["birds"]] + [("PLANE", p["art"]) for p in state["planes"]] + \
                 [("SCENE", s["art"]) for s in state["sounds"]]
        for kind, key in dict.fromkeys(wanted):
            f = self.app.art.cached(kind, key)
            if f is None and kind == "BIRD" and f"{kind}:{key}" not in self.sent:
                # Bird plates are fetched from fugleramme only when someone looks at them: fetch it for the page.
                f = self.app.art.load(kind, key, key, wait=True)
            if f is None:
                continue
            # Sent once, and again when the engraving itself changes (e.g. a bundled one replaces the own one).
            digest = hashlib.sha1(f.read_bytes()).hexdigest()[:12]
            if f"{kind}:{key}" in self.sent and self.art_sent.get(f"{kind}:{key}") == digest:
                continue
            ctype = "image/webp" if f.suffix == ".webp" else "image/png"
            self._put("/ingest/art?" + urllib.parse.urlencode({"kind": kind, "key": key}), f.read_bytes(), ctype)
            self.sent.add(f"{kind}:{key}")
            self.art_sent[f"{kind}:{key}"] = digest
            self._save_art_sent()
            log.info("publish: art %s %s", kind, key)
