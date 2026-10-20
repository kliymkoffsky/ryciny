"""Engravings, cached for good (Art.kt + Cutout.kt): fugleramme's plates for birds, generated ones for the rest."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

from . import net

log = logging.getLogger(__name__)
PLATES = "https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/assets/artwork/classic/birds"
RETRY_S = 10 * 60
DIRS = {"BIRD": "birds", "PLANE": "planes", "DOG": "dogs", "SCENE": "scenes"}
_PL = str.maketrans("ąćęłńóśźż", "acelnoszz")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower().translate(_PL)).strip("-")


def cutout(img: Image.Image, max_side: int = 1200, tolerance: int = 34) -> Image.Image:
    """Lifts an engraving off its paper: flood-fill the paper colour in from the edges, soften the rim, trim."""
    img = img.convert("RGB")
    if max(img.size) > max_side:
        f = max_side / max(img.size)
        img = img.resize((round(img.width * f), round(img.height * f)), Image.LANCZOS)
    px = np.asarray(img).astype(np.int16)
    h, w, _ = px.shape
    edge = np.concatenate([px[0], px[-1], px[:, 0], px[:, -1]])
    paper = np.median(edge, axis=0)
    near = np.max(np.abs(px - paper), axis=2) <= tolerance
    bg = np.zeros((h, w), dtype=bool)
    q = deque()
    for y, x in [(0, x) for x in range(w)] + [(h - 1, x) for x in range(w)] + [(y, 0) for y in range(h)] + [(y, w - 1) for y in range(h)]:
        if near[y, x] and not bg[y, x]:
            bg[y, x] = True
            q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and near[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                q.append((ny, nx))
    alpha = np.where(bg, 0, 255).astype(np.uint8)
    rim = ~bg & (np.roll(bg, 1, 0) | np.roll(bg, -1, 0) | np.roll(bg, 1, 1) | np.roll(bg, -1, 1))
    dist = np.max(np.abs(px - paper), axis=2)
    alpha[rim] = np.clip(dist[rim] * 255 / (tolerance * 2.5), 60, 255).astype(np.uint8)
    out = Image.fromarray(np.dstack([np.asarray(img), alpha]), "RGBA")
    ys, xs = np.nonzero(~bg)
    if len(xs) == 0:
        return out
    pad = round(max(w, h) * 0.01)
    return out.crop((max(0, xs.min() - pad), max(0, ys.min() - pad), min(w, xs.max() + pad + 1), min(h, ys.max() + pad + 1)))


class Art:
    def __init__(self, cfg, assets) -> None:
        self.cfg = cfg
        self.root = cfg.data / "art"
        self.style = json.loads(assets.text("style.json"))
        self.aliases = json.loads(assets.text("birdnet_aliases.json"))
        self.lock = threading.Lock()  # one generation at a time
        self.inflight: dict[str, threading.Event] = {}
        self.inflight_lock = threading.Lock()
        self.failed: dict[str, float] = {}
        self.no_plate: set[str] = set()
        self.error: str | None = None
        self.bundled_originals: dict[tuple[str, str], Path] = {}

    def _spend(self) -> bool:
        """Counts one paid picture against art_daily_limit; False when today's are used up (the credits stay safe)."""
        limit = int(getattr(self.cfg, "art_daily_limit", 30) or 0)
        if limit <= 0:
            return True
        f = self.cfg.data / "art_budget.json"
        today = time.strftime("%Y-%m-%d")
        try:
            b = json.loads(f.read_text())
        except (OSError, ValueError):
            b = {}
        if b.get("day") != today:
            b = {"day": today, "count": 0}
        if b["count"] >= limit:
            return False
        b["count"] += 1
        f.write_text(json.dumps(b))
        return True

    def _bird_key(self, sci: str) -> str:
        return slug(self.aliases.get(sci, sci))

    def candidates(self, kind: str, key: str) -> list[Path]:
        if kind == "BIRD":
            k = self._bird_key(key)
            return [self.root / "birds" / f"{k}.webp", self.root / "birds-generated" / f"{k}.png"]
        return [self.root / DIRS[kind] / f"{slug(key)}.png"]

    def cached(self, kind: str, key: str) -> Path | None:
        bundled = self.bundled_originals.get((kind, key))
        if bundled is not None and getattr(self.cfg, "prefer_bundled_art", False) and bundled.exists():
            return bundled  # the bundled engraving, so its prepared animation plays; the own one stays on disk
        found = next((p for p in self.candidates(kind, key) if p.exists()), None)
        if found is not None:
            return found
        return bundled if bundled is not None and bundled.exists() else None

    def load(self, kind: str, key: str, subject: str, airline: str = "", prompt: str = "", wait: bool = True) -> Path | None:
        """The engraving's file; fetches or generates it if missing (each one only ever once)."""
        found = self.cached(kind, key)
        if found:
            return found
        if kind == "BIRD":
            got = self._fugleramme(key)
            if got or key not in self.no_plate:
                return got
        target = self.candidates(kind, key)[-1]
        with self.inflight_lock:
            event = self.inflight.get(str(target))
            owner = event is None
            if owner:
                event = self.inflight[str(target)] = threading.Event()
        if owner:
            threading.Thread(target=self._produce, args=(kind, key, subject, airline, prompt, target, event), daemon=True).start()
        if wait:
            event.wait(240)
        return target if target.exists() else None

    def _fugleramme(self, sci: str) -> Path | None:
        target = self.candidates("BIRD", sci)[0]
        if self.failed.get("fugl:" + sci, 0) > time.time():
            return None
        try:
            data = net.get(f"{PLATES}/{self._bird_key(sci)}.webp")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return target
        except net.HttpError as e:
            self.failed["fugl:" + sci] = time.time() + 24 * 3600
            if e.code == 404:
                self.no_plate.add(sci)
        except Exception:  # noqa: BLE001
            self.failed["fugl:" + sci] = time.time() + RETRY_S
        return None

    def _produce(self, kind, key, subject, airline, prompt, target: Path, event: threading.Event) -> None:
        try:
            with self.lock:
                if target.exists():
                    return
                source = self.root / "source" / target.parent.name / target.name
                if not source.exists():
                    if self.cfg.image_provider == "none" or self.failed.get("gen:" + key, 0) > time.time():
                        return
                    if not self._spend():
                        self.error = f"Dzienny limit generowanych rycin ({self.cfg.art_daily_limit}) wyczerpany; kolejne jutro"
                        self.failed["gen:" + key] = time.time() + RETRY_S
                        return
                    data = self._generate(self.prompt(kind, subject, airline, prompt), wide=kind == "PLANE")
                    if not data:
                        return
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(data)
                cut = cutout(Image.open(source))
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(".tmp.png")
                cut.save(tmp, "PNG")
                tmp.replace(target)
                self.error = None
        except Exception as e:  # noqa: BLE001
            log.warning("art %s: %s", key, e)
            self.failed["gen:" + key] = time.time() + RETRY_S
            self.error = f"Generowanie ryciny ({subject}): {e}"
        finally:
            with self.inflight_lock:
                self.inflight.pop(str(target), None)
            event.set()

    def prompt(self, kind: str, subject: str, airline: str, prompt: str) -> str:
        t = self.style
        if kind == "PLANE":
            livery = t["livery"].replace("{airline}", airline) if airline else ""
            body = t["plane"].replace("{aircraft}", f"a {subject}").replace("{livery}", livery)
        elif kind == "DOG":
            body = t["dog"].replace("{breed}", subject)
        elif kind == "BIRD":
            body = t["bird"].replace("{bird}", f"the bird species {subject}")
        else:
            body = prompt
        return f"{t['base']} {body}"

    def _generate(self, prompt: str, wide: bool) -> bytes | None:
        c = self.cfg
        if c.image_provider == "gemini" and c.gemini_key:
            res = net.post_json(
                f"https://generativelanguage.googleapis.com/v1beta/models/{c.gemini_model}:generateContent",
                {"contents": [{"parts": [{"text": prompt}]}],
                 "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "3:2" if wide else "1:1"}}},
                {"x-goog-api-key": c.gemini_key})
            parts = res["candidates"][0]["content"]["parts"]
            return base64.b64decode(next(p["inlineData"]["data"] for p in parts if "inlineData" in p))
        if c.image_provider == "openrouter" and c.openrouter_key:
            res = net.post_json(
                "https://openrouter.ai/api/v1/chat/completions",
                {"model": c.openrouter_model, "messages": [{"role": "user", "content": prompt}], "modalities": ["image", "text"],
                 "image_config": {"aspect_ratio": "3:2" if wide else "1:1"}},
                {"Authorization": f"Bearer {c.openrouter_key}", "X-Title": "Ryciny"})
            url = res["choices"][0]["message"]["images"][0]["image_url"]["url"]
            return base64.b64decode(url.split(",", 1)[1]) if url.startswith("data:") else net.get(url)
        if c.image_provider == "openai" and c.openai_key:
            body = {"model": c.openai_model, "prompt": prompt, "n": 1, "size": "1536x1024" if wide else "1024x1024"}
            body.update({"response_format": "b64_json"} if c.openai_model.startswith("dall-e") else {"quality": "medium"})
            res = net.post_json("https://api.openai.com/v1/images/generations", body, {"Authorization": f"Bearer {c.openai_key}"})
            return base64.b64decode(res["data"][0]["b64_json"])
        return None

    def png(self, path: Path) -> bytes:
        if path.suffix == ".png":
            return path.read_bytes()
        buf = io.BytesIO()
        Image.open(path).save(buf, "PNG")
        return buf.getvalue()
