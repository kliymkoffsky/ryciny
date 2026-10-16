"""The journal, in exactly the JSON the Android app keeps (Store.kt), so the app can show it unchanged."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

BIRD_GAP_MS = 60_000
BARK_GAP_MS = 30_000
PLANE_GAP_MS = 10 * 60_000
SOUND_GAP_MS = 5 * 60_000
KEEP_MS = 7 * 24 * 3600_000
MAX_SOUNDS = 1_000
MAX_BARKS = 300
MAX_PLANES = 500
MAX_SAMPLES = 30


def now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, data: Path) -> None:
        self.file = data / "journal.json"
        self.clips = data / "clips"
        self.clips.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.version = 0
        self.j = self._load()
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

    def add_bird(self, sci: str, name: str, conf: float, at: int) -> None:
        with self.lock:
            birds = self.j["birds"]
            last = next((b for b in reversed(birds) if b["sci"] == sci), None)
            if last is not None and at - last["lastAt"] < BIRD_GAP_MS:
                last.update(lastAt=at, count=last["count"] + 1, conf=max(last["conf"], conf))
            else:
                birds.append({"sci": sci, "name": name, "conf": conf, "at": at, "lastAt": at, "count": 1})
            self.j["birds"] = [b for b in birds if at - b["lastAt"] < KEEP_MS]
            self._changed()

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
            kept = [b for b in barks if bark["at"] - b["lastAt"] < KEEP_MS][-MAX_BARKS:]
            clips = {b.get("clip") for b in kept}
            for f in self.clips.iterdir():
                if f.name not in clips:
                    f.unlink(missing_ok=True)
            self.j["barks"] = kept
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

    def add_sound(self, key: str, at: int, score: float, title: str = "", subtitle: str = "", variant: str = "") -> None:
        with self.lock:
            sounds = self.j["sounds"]
            last = next((s for s in reversed(sounds) if s["key"] == key), None)
            same = last is not None and at - last["lastAt"] < SOUND_GAP_MS and (not title or not last["title"] or title == last["title"])
            if same:
                last.update(lastAt=at, count=last["count"] + 1, score=max(last["score"], score),
                            title=last["title"] or title, subtitle=last["subtitle"] or subtitle, variant=last["variant"] or variant)
            else:
                sounds.append({"key": key, "at": at, "lastAt": at, "count": 1, "score": score,
                               "title": title, "subtitle": subtitle, "variant": variant})
            self.j["sounds"] = [s for s in sounds if at - s["lastAt"] < KEEP_MS][-MAX_SOUNDS:]
            self._changed()

    def delete_sounds(self, key: str, since: int, until: int) -> int:
        """Drops false events of one sound (e.g. jets taken for thunder) between two times; returns how many."""
        with self.lock:
            before = len(self.j["sounds"])
            self.j["sounds"] = [s for s in self.j["sounds"] if not (s["key"] == key and since <= s["at"] <= until)]
            n = before - len(self.j["sounds"])
            if n:
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

    def flush(self) -> None:
        with self.lock:
            if not self._dirty:
                return
            text = json.dumps(self.j, ensure_ascii=False)
            self._dirty = False
            tmp = self.file.with_suffix(".json.tmp")
            tmp.write_text(text)
            tmp.replace(self.file)

    def _saver(self) -> None:
        while True:
            time.sleep(3)
            self.flush()
