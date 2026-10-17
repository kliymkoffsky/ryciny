"""Optional public page: pushes a trimmed journal and the engravings to the Cloudflare Worker in public-site/.

Only what is fine for anyone to see goes out: birds, heard planes and neighbourhood sounds. No dogs, no speech,
children, music or doorbell, no coordinates and no distances (those would place the house). The only audio is
birds: one recording per species and day, and only one in which YAMNet heard no people and no music; the Worker
drops it after CLIP_DAYS.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

from . import stats
from .store import local, now_ms

log = logging.getLogger(__name__)

PRIVATE_SOUNDS = {"talking", "children", "music", "doorbell"}
EVERY_S = 180  # KV on the free plan takes 1000 writes a day
KEEP_DAYS = 30
CLIP_DAYS = 14


def public_state(journal: dict, sounds: dict, sound_on) -> dict:
    since = now_ms() - KEEP_DAYS * 86_400_000
    birds = [{"name": b["name"], "sci": b["sci"], "conf": round(b["conf"], 2), "count": b["count"], "lastAt": b["lastAt"]}
             for b in journal["birds"] if b["lastAt"] >= since]
    # One public recording per species and day: the most confident one that YAMNet found free of people and music.
    best: dict[tuple[str, str], dict] = {}
    clip_since = now_ms() - CLIP_DAYS * 86_400_000
    for b in journal["birds"]:
        if b.get("clip") and b.get("clipPublic") and b["lastAt"] >= clip_since:
            k = (b["sci"], local(b["lastAt"]).strftime("%Y-%m-%d"))
            if k not in best or b["conf"] > best[k]["conf"]:
                best[k] = b
    audio = {(b["sci"], b["lastAt"]): b["clip"] for b in best.values()}
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
    return {"updatedAt": now_ms(), "birds": birds, "planes": planes, "sounds": out_sounds}


def plane_key(p: dict) -> str:
    return f"{p.get('typeCode') or p['title']}-{p.get('airlineIcao') or p['airline'] or 'plain'}"


class Publisher:
    def __init__(self, cfg, app) -> None:
        self.cfg, self.app = cfg, app
        self.sent: set[str] | None = None
        self.error: str | None = None

    def _put(self, path: str, body: bytes, ctype: str) -> bytes:
        req = urllib.request.Request(self.cfg.public_url.rstrip("/") + path, data=body, method="PUT",
                                     headers={"Authorization": f"Bearer {self.cfg.public_token}", "Content-Type": ctype,
                                              "User-Agent": "ryciny-addon"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def run(self) -> None:
        version = -1
        while True:
            time.sleep(EVERY_S)
            if not self.cfg.public_url or not self.cfg.public_token or self.app.store.version == version:
                continue
            try:
                if self.sent is None:
                    self.sent = set(json.loads(self._put("/ingest/has", b"", "text/plain")))
                journal = self.app.store.snapshot()
                state = public_state(journal, self.app.sounds, self.app.sound_on)
                state["stats"] = stats.compute(journal, self.app.store.history_snapshot(), self.app.sounds, self.app.sound_on, PRIVATE_SOUNDS)
                self._art(state)
                self._clips(state)
                self._put("/ingest/state", json.dumps(state, ensure_ascii=False).encode(), "application/json")
                version, self.error = self.app.store.version, None
            except Exception as e:  # noqa: BLE001 - try again next round
                self.error = f"strona publiczna: {e}"
                log.warning("publish: %s", e)

    def _clips(self, state: dict) -> None:
        for b in state["birds"]:
            name = b.get("audio")
            if not name or f"clip:{name}" in self.sent:
                continue
            f = self.app.store.clips / name
            if not f.exists():
                b.pop("audio")
                continue
            self._put("/ingest/clip?" + urllib.parse.urlencode({"name": name}), f.read_bytes(), "audio/wav")
            self.sent.add(f"clip:{name}")
            log.info("publish: clip %s %s", b["sci"], name)

    def _art(self, state: dict) -> None:
        wanted = [("BIRD", b["sci"]) for b in state["birds"]] + [("PLANE", p["art"]) for p in state["planes"]] + \
                 [("SCENE", s["art"]) for s in state["sounds"]]
        for kind, key in dict.fromkeys(wanted):
            if f"{kind}:{key}" in self.sent:
                continue
            f = self.app.art.cached(kind, key)
            if f is None and kind == "BIRD":
                # Bird plates are fetched from fugleramme only when someone looks at them: fetch it for the page.
                f = self.app.art.load(kind, key, key, wait=True)
            if f is None:
                continue
            ctype = "image/webp" if f.suffix == ".webp" else "image/png"
            self._put("/ingest/art?" + urllib.parse.urlencode({"kind": kind, "key": key}), f.read_bytes(), ctype)
            self.sent.add(f"{kind}:{key}")
            log.info("publish: art %s %s", kind, key)
