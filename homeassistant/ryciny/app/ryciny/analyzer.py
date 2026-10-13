"""Runs BirdNET and YAMNet over each 3 s window and writes what they found to the journal (Analyzer.kt)."""

from __future__ import annotations

import collections
import json
import uuid

import numpy as np

from . import dsp
from .ml import BirdNet, Yamnet
from .store import Store

AIRCRAFT_THRESHOLD = 0.25


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
    def __init__(self, cfg, assets, store: Store, sky, rails, live: Live) -> None:
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

    def analyze(self, window: np.ndarray, at: int) -> None:
        self._birds(window, at)
        audio16 = dsp.decimate48to16(window)
        frames = [self.yamnet.run(audio16[i * 16_000:i * 16_000 + Yamnet.SAMPLES]) for i in range(3)]
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
            train = self.rails.match(at) if sound["key"] == "train" else None
            if train:
                self.store.add_sound(sound["key"], at, score, *self.rails.details(train))
            else:
                self.store.add_sound(sound["key"], at, score)
        if max(dog_scores) >= self.cfg.bark_threshold:
            self._bark(audio16, frames, dog_scores, at)

    def _birds(self, window: np.ndarray, at: int) -> None:
        conf = self.birdnet.predict(window)
        mask = self.birdnet.range_mask(self.cfg.lat, self.cfg.lon) if self.cfg.range_filter else None
        for i in np.nonzero(conf >= self.cfg.bird_threshold)[0]:
            label = self.birdnet.labels[i]
            if label.bird and (mask is None or mask[i]):
                self.store.add_bird(label.sci, label.name, float(conf[i]), at)

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
