"""Runs BirdNET and YAMNet over each 3 s window and writes what they found to the journal (Analyzer.kt)."""

from __future__ import annotations

import collections
import json
import uuid

import numpy as np

from . import config, dsp
from .ml import BirdNet, Yamnet
from .store import Store

AIRCRAFT_THRESHOLD = 0.25
NO_AUDIO = {"talking", "children"}  # only the fact is kept, never a recording of people
PLANE_MASK_KM = 3.0
# YAMNet classes of people (speech, shouts, laughter, crying, singing, coughs, sneezes, crowds, children playing)
# and music. Whistling (35) is left out: birdsong is often called whistling. So are breathing, wheeze, snoring, gasp,
# pant, snort and sniff (36-41, 45): on a quiet night YAMNet hears them in plain background noise (about 0.2).
PEOPLE = [*range(0, 35), 42, 43, 44, *range(61, 67), 132, 133]
PEOPLE_MAX = 0.15  # GDN is 2 km away: jets on approach rumble like thunder, ships and wind


class Live:
    """What the microphone hears right now, for the app's live strip (the app's Live)."""

    def __init__(self) -> None:
        self.listening = False
        self.level = 0.0
        self.sound = ""
        self.at = 0
        self.error: str | None = None

    def json(self) -> dict:
        return {"listening": self.listening, "level": self.level, "sound": self.sound, "at": self.at, "error": self.error}

    def level_db(self) -> float:
        import math

        return round(20 * math.log10(max(self.level, 1e-6)), 1)


class Analyzer:
    def __init__(self, cfg, assets, store: Store, sky, rails, live: Live, weather=None) -> None:
        self.weather = weather
        self.cfg = cfg
        self.store = store
        self.sky = sky
        self.rails = rails
        self.live = live
        self.birdnet = BirdNet(assets)
        self.yamnet = Yamnet(assets)
        self.sounds = json.loads(assets.text("sounds.json"))["sounds"]
        self.hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)

    def _sound_on(self, sound: dict) -> bool:
        if sound["key"] in self.cfg.sounds_off:
            return False
        if sound["key"] in self.cfg.sounds_on:
            return True
        return sound.get("enabled", True)

    def _people(self, x: np.ndarray) -> float:
        """The strongest people/music score in [x] (48 kHz), second by second."""
        a16 = dsp.decimate48to16(x)
        best = 0.0
        for i in range(0, max(1, len(a16) - Yamnet.SAMPLES + 1), 16_000):
            s = self.yamnet.run(a16[i:i + Yamnet.SAMPLES])[0]
            best = max(best, float(max(s[k] for k in PEOPLE)))
        return best

    def recheck_public(self) -> int:
        """Judges again the saved bird recordings that were kept off the public page; returns how many may go now."""
        import soundfile as sf

        ok = 0
        for e, folder in self.store.recordings_to_recheck():
            try:
                x, rate = sf.read(str(folder / e["clip"]), dtype="float32")
            except Exception:  # noqa: BLE001
                continue
            if x.ndim > 1:
                x = x.mean(axis=1)
            if rate != 48_000:
                x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * 48_000 / rate)), np.arange(len(x)), x).astype(np.float32)
            if self._people(x) < PEOPLE_MAX:
                self.store.mark_public(e)
                ok += 1
        return ok

    def analyze(self, window: np.ndarray, at: int, before: np.ndarray | None = None, after: np.ndarray | None = None) -> None:
        audio16 = dsp.decimate48to16(window)
        frames = [self.yamnet.run(audio16[i * 16_000:i * 16_000 + Yamnet.SAMPLES]) for i in range(3)]
        # The recording: 3 s before, the detection, 3 s after (9 s), as MP3; made only when a recording is kept.
        nine = np.concatenate([w for w in (before, window, after) if w is not None])
        clip = lambda: dsp.mp3_bytes(nine)  # noqa: E731
        # A bird's recording may go on the public page only when YAMNet hears no people and no music in all 9 s.
        people = max(float(max(s[k] for k in PEOPLE)) for s, _ in frames)
        conf = self.birdnet.predict(window)
        # Whether the 9 s may be public: the neighbours are checked only once something is about to be recorded.
        checked: list[bool] = []

        def public() -> bool:
            if not checked:
                checked.append(people < PEOPLE_MAX and all(self._people(w) < PEOPLE_MAX for w in (before, after) if w is not None))
            return checked[0]
        self._birds(conf, at, public, clip)
        dog_scores = [float(max(s[k] for k in Yamnet.DOG)) for s, _ in frames]
        aircraft = max(float(max(s[k] for k in Yamnet.AIRCRAFT)) for s, _ in frames)
        top = max(((int(np.argmax(s)), float(np.max(s))) for s, _ in frames), key=lambda t: t[1])
        self.live.level, self.live.sound, self.live.at = dsp.rms(window), self.yamnet.classes[top[0]], at

        if aircraft >= AIRCRAFT_THRESHOLD:
            self.sky.heard(at)
        for sound in self.sounds:
            if not self._sound_on(sound):
                continue
            score = max(float(max(s[c] for c in sound["classes"])) for s, _ in frames)
            if score < sound["threshold"]:
                continue
            recent = self.hits[sound["key"]]
            recent.append(at)
            while recent[0] < at - 60_000:
                recent.popleft()
            if len(recent) < sound.get("minHits", 1):
                continue
            if sound.get("notNearPlane") and self.sky.near(PLANE_MASK_KM):
                continue
            if sound.get("weather") == "thunder" and self.weather and self.weather.thunder() is False:
                continue
            sound_clip = None if sound["key"] in NO_AUDIO else clip
            train = self.rails.match(at) if sound["key"] == "train" else None
            if train:
                self.store.add_sound(sound["key"], at, score, *self.rails.details(train), clip=sound_clip, public=public)
            else:
                self.store.add_sound(sound["key"], at, score, clip=sound_clip, public=public)
        if max(dog_scores) >= self.cfg.bark_threshold:
            self._bark(audio16, frames, dog_scores, at)

    def _birds(self, conf: np.ndarray, at: int, public, clip) -> None:
        mask = None
        if self.cfg.range_filter:
            lat, lon = config.location(self.cfg)
            mask = self.birdnet.range_mask(lat, lon)
        for i in np.nonzero(conf >= self.cfg.bird_threshold)[0]:
            label = self.birdnet.labels[i]
            if label.bird and (mask is None or mask[i]):
                self.store.add_bird(label.sci, label.name, float(conf[i]), at, clip=clip, public=public)

    def _bark(self, audio16, frames, dog_scores, at: int) -> None:
        barking = [i for i, s in enumerate(dog_scores) if s >= self.cfg.bark_threshold * 0.7] or [int(np.argmax(dog_scores))]
        embedding = np.mean([frames[i][1] for i in barking], axis=0)
        pitch = dsp.bark_pitch(audio16)
        best = None
        with self.store.lock:
            dogs = [(d["id"], d.get("samples", [])) for d in self.store.j["dogs"]]
        for dog_id, samples in dogs:
            sim = max((dsp.cosine(s, embedding) for s in samples if s), default=0.0)
            if best is None or sim > best[1]:
                best = (dog_id, sim)
        bark_id = uuid.uuid4().hex[:8]
        clip = f"{bark_id}.wav"
        (self.store.clips / clip).write_bytes(dsp.wav_bytes(audio16, 16_000))
        self.store.add_bark({
            "id": bark_id, "at": at, "lastAt": at, "count": 1, "score": max(dog_scores), "pitchHz": pitch,
            "size": dsp.size_of(pitch), "embedding": [round(float(x), 4) for x in embedding],
            "dogId": best[0] if best and best[1] >= self.cfg.dog_match else None,
            "similarity": best[1] if best else 0.0, "clip": clip,
        })
