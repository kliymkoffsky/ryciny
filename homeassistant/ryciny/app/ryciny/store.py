"""The journal, in exactly the JSON the Android app keeps (Store.kt), so the app can show it unchanged."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

try:
    from zoneinfo import ZoneInfo

    ZONE = ZoneInfo(__import__("os").environ.get("TZ") or "Europe/Warsaw")
except Exception:  # noqa: BLE001 - no tz database: the container's local time
    ZONE = None

Clip = Callable[[], bytes] | None

BIRD_GAP_MS = 60_000
BARK_GAP_MS = 30_000
PLANE_GAP_MS = 10 * 60_000
SOUND_GAP_MS = 5 * 60_000
KEEP_MS = 14 * 24 * 3600_000
CLIP_KEEP_MS = 14 * 24 * 3600_000  # recordings of what was detected, on the add-on's disk only
HISTORY_DAYS = 400  # birds per day and hour, for the chance of hearing a species
MAX_SOUNDS = 1_000
MAX_BARKS = 300
MAX_PLANES = 500
MAX_SAMPLES = 30


def now_ms() -> int:
    return int(time.time() * 1000)


def _ext(data: bytes) -> str:
    return ".wav" if data[:4] == b"RIFF" else ".mp3"


def local(ms: int):
    import datetime as dt

    return dt.datetime.fromtimestamp(ms / 1000, ZONE) if ZONE else dt.datetime.fromtimestamp(ms / 1000)


class Store:
    def __init__(self, data: Path) -> None:
        self.file = data / "journal.json"
        self.history_file = data / "history.json"
        self.clips = data / "clips"
        self.clips.mkdir(parents=True, exist_ok=True)
        # The most confident recording of each species ever: never pruned, replaced only by a better one.
        self.best_dir = data / "best"
        self.best_dir.mkdir(parents=True, exist_ok=True)
        self.best_file = data / "best.json"
        self.lock = threading.RLock()
        self.version = 0
        self.j = self._load()
        self.history = self._load_history()
        self.best = self._load_best()
        self._pruned = 0.0
        self._dirty = False
        threading.Thread(target=self._saver, daemon=True).start()

    # --- reading -----------------------------------------------------------------------------------

    def snapshot(self, for_app: bool = True) -> dict:
        """The journal as JSON; for the app without the 1024-number embeddings (a dog keeps its sample count)."""
        with self.lock:
            if not for_app:
                return json.loads(json.dumps(self.j))
            j = dict(self.j)
            j["barks"] = [{**b, "embedding": []} for b in self.j["barks"]]
            j["dogs"] = [{**d, "samples": [[] for _ in d.get("samples", [])]} for d in self.j["dogs"]]
            return j

    # --- writing (same rules as Store.kt) ----------------------------------------------------------

    def _changed(self) -> None:
        self.version += 1
        self._dirty = True

    def add_bird(self, sci: str, name: str, conf: float, at: int, clip: Clip = None, public: bool = False) -> None:
        with self.lock:
            birds = self.j["birds"]
            last = next((b for b in reversed(birds) if b["sci"] == sci), None)
            if last is not None and at - last["lastAt"] < BIRD_GAP_MS:
                better = conf > last["conf"]
                last.update(lastAt=at, count=last["count"] + 1, conf=max(last["conf"], conf))
                if better or not last.get("clip"):
                    self._keep_clip(last, clip, public)
            else:
                last = {"sci": sci, "name": name, "conf": conf, "at": at, "lastAt": at, "count": 1}
                self._keep_clip(last, clip, public)
                birds.append(last)
            self._count_bird(sci, name, at, conf=conf)
            self._keep_best(sci, name, conf, at, clip, public)
            self.j["birds"] = [b for b in birds if at - b["lastAt"] < KEEP_MS]
            self._prune_clips(at)
            self._changed()

    # --- recordings: the best 3 s of each event, kept CLIP_KEEP_MS ----------------------------------

    def _keep_clip(self, entry: dict, clip: Clip, public=False) -> None:
        """[public]: a bool or a function giving it (computed only when a recording is actually written)."""
        """Writes [clip] as the entry's recording (only now, at the detection), replacing a worse one."""
        if clip is None:
            return
        try:
            data = clip()
        except Exception:  # noqa: BLE001 - a recording is a bonus, never a reason to lose the detection
            return
        name = uuid.uuid4().hex[:8] + _ext(data)
        (self.clips / name).write_bytes(data)
        old = entry.get("clip")
        entry["clip"] = name
        entry["clipPublic"] = bool(public() if callable(public) else public)  # no people or music in it: may be public
        if old:
            (self.clips / old).unlink(missing_ok=True)

    def _prune_clips(self, now: int, force: bool = False) -> None:
        """Deletes recordings older than CLIP_KEEP_MS or no longer in the journal; at most every 10 minutes."""
        if not force and time.time() - self._pruned < 600:
            return
        self._pruned = time.time()
        for key in ("birds", "sounds", "barks"):
            for e in self.j[key]:
                if e.get("clip") and now - e["lastAt"] >= CLIP_KEEP_MS:
                    (self.clips / e["clip"]).unlink(missing_ok=True)
                    e["clip"] = None
        used = {e.get("clip") for key in ("birds", "sounds", "barks") for e in self.j[key]}
        for f in self.clips.iterdir():
            if f.name not in used and (f.suffix in (".wav", ".mp3") or now - f.stat().st_mtime * 1000 > CLIP_KEEP_MS):
                f.unlink(missing_ok=True)

    def _keep_best(self, sci: str, name: str, conf: float, at: int, clip: Clip, public: bool) -> None:
        best = self.best.get(sci)
        if clip is None or (best and conf <= best["conf"]):
            return
        try:
            data = clip()
        except Exception:  # noqa: BLE001
            return
        file = uuid.uuid4().hex[:8] + _ext(data)
        (self.best_dir / file).write_bytes(data)
        if best:
            (self.best_dir / best["clip"]).unlink(missing_ok=True)
        self.best[sci] = {"sci": sci, "name": name, "conf": round(conf, 4), "at": at, "clip": file,
                          "public": bool(public() if callable(public) else public)}
        self._best_dirty = True

    def recordings_to_recheck(self) -> list[tuple[dict, Path]]:
        with self.lock:
            out = [(b, self.clips) for key in ("birds", "sounds") for b in self.j[key] if b.get("clip") and not b.get("clipPublic")]
            out += [(b, self.best_dir) for b in self.best.values() if not b.get("public")]
            return [(dict(e), d) for e, d in out]

    def mark_public(self, e: dict) -> None:
        with self.lock:
            for b in self.j["birds"] + self.j["sounds"]:
                if b.get("clip") == e["clip"]:
                    b["clipPublic"] = True
            for b in self.best.values():
                if b.get("clip") == e["clip"]:
                    b["public"] = True
                    self._best_dirty = True
            self._changed()

    def best_snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.best))

    def _load_best(self) -> dict:
        self._best_dirty = False
        try:
            return json.loads(self.best_file.read_text())
        except (OSError, ValueError):
            pass
        # First start: the best of the recordings the journal still has.
        best: dict = {}
        for b in sorted((b for b in self.j["birds"] if b.get("clip") and (self.clips / b["clip"]).exists()), key=lambda b: b["conf"]):
            old = best.get(b["sci"])
            file = uuid.uuid4().hex[:8] + Path(b["clip"]).suffix
            (self.best_dir / file).write_bytes((self.clips / b["clip"]).read_bytes())
            if old:
                (self.best_dir / old["clip"]).unlink(missing_ok=True)
            best[b["sci"]] = {"sci": b["sci"], "name": b["name"], "conf": round(b["conf"], 4), "at": b["lastAt"], "clip": file,
                              "public": bool(b.get("clipPublic"))}
        self._best_dirty = bool(best)
        return best

    # --- history: birds per day and hour, kept HISTORY_DAYS ----------------------------------------

    def _count_bird(self, sci: str, name: str, at: int, n: int = 1, conf: float = 0.0) -> None:
        t = local(at)
        day = self.history.setdefault(t.strftime("%Y-%m-%d"), {})
        b = day.setdefault(sci, {"n": name, "h": [0] * 24, "c": 0.0})
        b["h"][t.hour] += n
        b["c"] = round(b.get("c", 0.0) + conf * n, 3)  # sum of BirdNET confidences, for the average

    def history_snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.history))

    def add_bark(self, bark: dict) -> None:
        with self.lock:
            barks = self.j["barks"]
            last = barks[-1] if barks else None
            same = last is not None and bark["at"] - last["lastAt"] < BARK_GAP_MS and \
                last.get("dogId") == bark.get("dogId") and (bark.get("dogId") is not None or last["size"] == bark["size"])
            if same:
                keep_new_clip = bark["score"] > last["score"] and bark.get("clip")
                last.update(lastAt=bark["at"], count=last["count"] + 1, score=max(last["score"], bark["score"]),
                            clip=bark["clip"] if keep_new_clip else last.get("clip"))
            else:
                barks.append(bark)
            self.j["barks"] = [b for b in barks if bark["at"] - b["lastAt"] < KEEP_MS][-MAX_BARKS:]
            self._prune_clips(bark["at"])
            self._changed()

    def tag_bark(self, bark_id: str, dog_id: str) -> bool:
        with self.lock:
            bark = next((b for b in self.j["barks"] if b["id"] == bark_id), None)
            dog = next((d for d in self.j["dogs"] if d["id"] == dog_id), None)
            if bark is None or dog is None:
                return False
            bark.update(dogId=dog_id, similarity=1.0)
            dog["samples"] = (dog.get("samples", []) + [bark["embedding"]])[-MAX_SAMPLES:]
            self._changed()
            return True

    def new_dog(self, name: str, breed: str, breed_en: str, dog_id: str | None = None) -> str:
        with self.lock:
            # The app may pick the id itself, so it can tag a bark to the new dog without waiting for the answer.
            dog_id = dog_id if dog_id and re.fullmatch(r"[0-9a-f-]{4,40}", dog_id) else uuid.uuid4().hex[:8]
            self.j["dogs"].append({"id": dog_id, "name": name, "breed": breed, "breedEn": breed_en, "samples": []})
            self._changed()
            return dog_id

    def edit_dog(self, dog_id: str, name: str, breed: str, breed_en: str) -> None:
        with self.lock:
            for d in self.j["dogs"]:
                if d["id"] == dog_id:
                    d.update(name=name, breed=breed, breedEn=breed_en)
            self._changed()

    def delete_dog(self, dog_id: str) -> None:
        with self.lock:
            self.j["dogs"] = [d for d in self.j["dogs"] if d["id"] != dog_id]
            for b in self.j["barks"]:
                if b.get("dogId") == dog_id:
                    b.update(dogId=None, similarity=0.0)
            self._changed()

    def add_sound(self, key: str, at: int, score: float, title: str = "", subtitle: str = "", variant: str = "",
                  clip: Clip = None, public=False) -> None:
        with self.lock:
            sounds = self.j["sounds"]
            last = next((s for s in reversed(sounds) if s["key"] == key), None)
            same = last is not None and at - last["lastAt"] < SOUND_GAP_MS and (not title or not last["title"] or title == last["title"])
            if same:
                better = score > last["score"]
                last.update(lastAt=at, count=last["count"] + 1, score=max(last["score"], score),
                            title=last["title"] or title, subtitle=last["subtitle"] or subtitle, variant=last["variant"] or variant)
                if better or not last.get("clip"):
                    self._keep_clip(last, clip, public)
            else:
                last = {"key": key, "at": at, "lastAt": at, "count": 1, "score": score,
                        "title": title, "subtitle": subtitle, "variant": variant}
                self._keep_clip(last, clip, public)
                sounds.append(last)
            self.j["sounds"] = [s for s in sounds if at - s["lastAt"] < KEEP_MS][-MAX_SOUNDS:]
            self._prune_clips(at)
            self._changed()

    def delete_sounds(self, key: str, since: int, until: int) -> int:
        """Drops false events of one sound (e.g. jets taken for thunder) between two times; returns how many."""
        with self.lock:
            before = len(self.j["sounds"])
            self.j["sounds"] = [s for s in self.j["sounds"] if not (s["key"] == key and since <= s["at"] <= until)]
            n = before - len(self.j["sounds"])
            if n:
                self._prune_clips(now_ms(), force=True)
                self._changed()
            return n

    def fill_sounds(self, key: str, details) -> None:
        """Re-derives events' details from the current timetable; details(event) -> (title, subtitle, variant) or None."""
        with self.lock:
            changed = False
            for e in self.j["sounds"]:
                if e["key"] != key:
                    continue
                d = details(e)
                if d and (e["title"], e["subtitle"], e["variant"]) != d:
                    e["title"], e["subtitle"], e["variant"] = d
                    changed = True
            if changed:
                self._changed()

    def add_plane(self, p: dict) -> None:
        with self.lock:
            planes = self.j["planes"]
            last = next((x for x in reversed(planes) if x["hex"] == p["hex"]), None)
            if last is not None and p["at"] - last["lastAt"] < PLANE_GAP_MS:
                alts = [a for a in (last.get("minAltM"), p.get("minAltM")) if a is not None]
                last.update(
                    lastAt=p["at"], minDistKm=min(last["minDistKm"], p["minDistKm"]),
                    minAltM=min(alts) if alts else None, heard=last["heard"] or p["heard"],
                    route=p["route"] or last["route"], airline=p["airline"] or last["airline"], title=p["title"] or last["title"],
                    typeCode=p["typeCode"] or last.get("typeCode", ""), airlineIcao=p["airlineIcao"] or last.get("airlineIcao", ""),
                )
            else:
                planes.append(p)
            self.j["planes"] = [x for x in planes if p["at"] - x["lastAt"] < KEEP_MS][-MAX_PLANES:]
            self._changed()

    def merge_import(self, journal: dict) -> None:
        """Takes a journal exported from the phone: its dogs (with bark samples) and its history."""
        with self.lock:
            known = {d["id"] for d in self.j["dogs"]}
            self.j["dogs"] += [d for d in journal.get("dogs", []) if d["id"] not in known]
            for key in ("birds", "barks", "planes", "sounds"):
                seen = {json.dumps(x, sort_keys=True) for x in self.j[key]}
                self.j[key] = sorted(self.j[key] + [x for x in journal.get(key, []) if json.dumps(x, sort_keys=True) not in seen],
                                     key=lambda x: x.get("at", 0))
            self._changed()

    # --- persistence -------------------------------------------------------------------------------

    def _load(self) -> dict:
        empty = {"birds": [], "barks": [], "dogs": [], "planes": [], "sounds": [], "mowing": []}
        try:
            j = json.loads(self.file.read_text())
        except (OSError, ValueError):
            return empty
        return {**empty, **j}

    def _load_history(self) -> dict:
        try:
            return json.loads(self.history_file.read_text())
        except (OSError, ValueError):
            # First start with history: what the journal still has (the newest moment of each entry).
            self.history = {}
            for b in self.j["birds"]:
                self._count_bird(b["sci"], b["name"], b["lastAt"], b.get("count", 1), b["conf"])
            return self.history

    def flush(self) -> None:
        with self.lock:
            if not self._dirty:
                return
            self._dirty = False
            cutoff = local(now_ms() - HISTORY_DAYS * 86_400_000).strftime("%Y-%m-%d")
            self.history = {d: v for d, v in self.history.items() if d >= cutoff}
            files = [(self.file, self.j), (self.history_file, self.history)]
            if self._best_dirty:
                files.append((self.best_file, self.best))
                self._best_dirty = False
            for path, data in files:
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False))
                tmp.replace(path)

    def _saver(self) -> None:
        while True:
            time.sleep(3)
            self.flush()
