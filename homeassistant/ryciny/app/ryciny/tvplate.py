"""The plate for Samsung The Frame (3840x2160): what is heard now with a description, and a column of statistics."""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import re
import threading
import urllib.parse
from pathlib import Path

import functools

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import net
from .plate import INK, INK_SOFT, PAPER

log = logging.getLogger(__name__)

RUBRIC = (156, 59, 42)
W, H = 3840, 2160


class Wiki:
    """The first sentences of a species' Polish Wikipedia article, fetched once and kept in /data/wiki.json."""

    def __init__(self, data: Path) -> None:
        self.file = data / "wiki.json"
        self.lock = threading.Lock()
        try:
            self.cache = json.loads(self.file.read_text())
        except (OSError, ValueError):
            self.cache = {}

    def about(self, sci: str) -> str:
        with self.lock:
            if sci in self.cache:
                return self.cache[sci]
        text = ""
        try:
            r = net.get_json("https://pl.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(sci.replace(" ", "_")))
            text = (r.get("extract") or "").strip()
            # Two sentences at most, without the bracketed etymology and Latin.
            text = re.sub(r"\s*\([^()]*\)", "", text)
            sentences = re.split(r"(?<=[.!?])\s+", text)
            text = " ".join(sentences[:2])[:330]
        except Exception as e:  # noqa: BLE001 - no description is fine
            log.info("wiki %s: %s", sci, e)
            return ""
        with self.lock:
            self.cache[sci] = text
            self.file.write_text(json.dumps(self.cache, ensure_ascii=False))
        return text


@functools.lru_cache(maxsize=1)
def aged_paper(w: int = W, h: int = H, seed: int = 7) -> Image.Image:
    """Old paper on fine canvas: uneven tone, a faint weave, fibres, foxing spots and darker edges. Made once."""
    rng = np.random.default_rng(seed)

    def blur_noise(scale: int, radius: float) -> np.ndarray:
        n = Image.fromarray((rng.random((h // scale, w // scale)) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        return np.asarray(n.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255 - 0.5

    base = np.array([238, 226, 200], dtype=np.float32)          # warm, slightly yellowed paper
    tone = blur_noise(48, 60) * 26 + blur_noise(12, 8) * 8       # large stains and smaller cloudiness
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    weave = (np.sin(x * 2 * np.pi / 7.0) * np.sin(y * 2 * np.pi / 7.0)) * 2.2 \
        + np.sin(y * 2 * np.pi / 3.5 + blur_noise(30, 20) * 6) * 1.2  # canvas threads, a little irregular
    grain = rng.normal(0, 3.2, (h, w)).astype(np.float32)
    # Edges darken and yellow with age.
    dx, dy = np.minimum(x, w - 1 - x) / w, np.minimum(y, h - 1 - y) / h
    edge = np.clip(1 - np.minimum(dx, dy) / 0.12, 0, 1) ** 2
    light = tone + weave + grain - edge * 34
    img = base[None, None, :] + light[..., None] * np.array([1.0, 0.96, 0.85], dtype=np.float32)
    img[..., 2] -= edge * 18                                    # browner at the rim
    # Foxing: a few small rust-coloured spots.
    for _ in range(45):
        cx, cy, rad = rng.integers(0, w), rng.integers(0, h), rng.uniform(2, 9)
        x0, x1, y0, y1 = int(max(0, cx - rad * 3)), int(min(w, cx + rad * 3)), int(max(0, cy - rad * 3)), int(min(h, cy + rad * 3))
        yy, xx = np.mgrid[y0:y1, x0:x1]
        a = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * rad ** 2)) * rng.uniform(0.08, 0.22)
        img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - a[..., None]) + np.array([170, 120, 75], dtype=np.float32) * a[..., None]
    # Fibres: short faint strokes.
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(out)
    fibres = Image.new("L", (w, h), 0)
    fd = ImageDraw.Draw(fibres)
    for _ in range(320):
        fx, fy = float(rng.integers(0, w)), float(rng.integers(0, h))
        ang = rng.uniform(0, np.pi)
        pts = [(fx, fy)]
        for _ in range(int(rng.integers(3, 7))):  # short, slightly bent strands
            ang += rng.normal(0, 0.35)
            fx, fy = fx + np.cos(ang) * 6, fy + np.sin(ang) * 6
            pts.append((fx, fy))
        fd.line(pts, fill=int(rng.uniform(30, 70)), width=1)
    fibres = fibres.filter(ImageFilter.GaussianBlur(0.8))
    out = Image.composite(Image.new("RGB", (w, h), (176, 158, 124)), out, fibres)
    return out.filter(ImageFilter.GaussianBlur(0.5))


def print_on(paper: Image.Image, art: Image.Image, xy: tuple[int, int]) -> None:
    """Pastes [art] as if printed on [paper]: multiplied, so its own white paper takes the old paper's tone."""
    art = art.convert("RGBA")
    # The plate's own paper (its brightest tones) is lifted to white first, so only the ink darkens the old paper.
    rgb = np.asarray(art.convert("RGB"), dtype=np.float32)
    alpha = np.asarray(art.split()[3]) > 0
    if alpha.any():
        paper_tone = np.percentile(rgb[alpha], 92, axis=0)
        rgb = np.clip(rgb * (255 / np.maximum(paper_tone, 1)), 0, 255)
    art = Image.merge("RGBA", (*Image.fromarray(rgb.astype(np.uint8)).split(), art.split()[3]))
    x, y = xy
    box = (x, y, x + art.width, y + art.height)
    under = paper.crop(box)
    printed = Image.fromarray((np.asarray(under, dtype=np.float32) * np.asarray(art.convert("RGB"), dtype=np.float32) / 255).astype(np.uint8))
    paper.paste(printed, box, art.split()[3])


def render(plate: dict | None, engraving: Image.Image | None, about: str, stats: dict, fonts: tuple[str, str],
           thumbs: dict[str, Image.Image] | None = None) -> bytes:
    thumbs = thumbs or {}
    regular, italic = fonts
    img = aged_paper().copy()
    d = ImageDraw.Draw(img)
    inset = 70
    d.rectangle((inset, inset, W - inset, H - inset), outline=INK_SOFT, width=3)
    d.rectangle((inset + 16, inset + 16, W - inset - 16, H - inset - 16), outline=(*INK_SOFT,), width=1)
    font = lambda path, size: ImageFont.truetype(path, size)  # noqa: E731

    def line(s: str, path: str, size: int, color, x: float, y: float, max_w: float, anchor: str = "ms") -> None:
        f = font(path, size)
        while d.textlength(s, font=f) > max_w and f.size > size * 0.55:
            f = font(path, f.size - 2)
        d.text((x, y), s, font=f, fill=color, anchor=anchor)

    def wrap(s: str, path: str, size: int, color, x: float, y: float, max_w: float, lines: int, anchor: str = "ms") -> float:
        f = font(path, size)
        words, rows, cur = s.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) <= max_w:
                cur = t
            else:
                rows.append(cur)
                cur = w
        if cur:
            rows.append(cur)
        if len(rows) > lines:
            rows = rows[:lines]
            rows[-1] = rows[-1].rstrip(",;:") + "…"
        for i, r in enumerate(rows):
            d.text((x, y + i * size * 1.3), r, font=f, fill=color, anchor=anchor)
        return y + len(rows) * size * 1.3

    # Left: what is heard, two thirds of the width.
    left_w = W * 0.64
    cx = inset + left_w / 2
    line(dt.datetime.now().strftime("%d.%m.%Y, %H:%M"), italic, 56, INK_SOFT, cx, 220, left_w)
    if plate is None:
        line("Cisza: nic nie przeleciało ani nie zaśpiewało", italic, 90, INK_SOFT, cx, H / 2, left_w * 0.9)
    else:
        if engraving is not None:
            box_w, box_h = left_w * 0.86, H * 0.5
            e = engraving.convert("RGBA")
            f = min(box_w / e.width, box_h / e.height)
            e = e.resize((max(1, round(e.width * f)), max(1, round(e.height * f))), Image.LANCZOS)
            print_on(img, e, (round(cx - e.width / 2), round(300 + (box_h - e.height) / 2)))
        y = 300 + H * 0.5 + 150
        line(plate["title"], regular, 150, INK, cx, y, left_w * 0.9)
        y += 95
        for i, l in enumerate(plate["lines"][:3]):
            line(l, italic, 66, INK if i == 0 else INK_SOFT, cx, y, left_w * 0.9)
            y += 82
        if about:
            wrap(about, italic, 54, INK_SOFT, cx, y + 30, left_w * 0.82, 3)

    # Right: statistics. One left edge for titles and rows, one rhythm: GAP before a section, STEP between rows.
    rule_x = inset + left_w + 30
    d.line((rule_x, 200, rule_x, H - 200), fill=INK_SOFT, width=2)
    x0 = rule_x + 110
    x1 = W - inset - 110
    rw = x1 - x0
    GAP, TITLE = 90, 66
    TH = 100  # engraving thumbnail beside each bird
    tx = x0 + TH + 34

    def title(text: str, y: float) -> float:
        line(text, regular, TITLE, RUBRIC, x0, y, rw, "ls")
        d.line((x0, y + 24, x1, y + 24), fill=(*INK_SOFT,), width=1)
        return y + 24 + 82

    def thumb(sci: str, y_base: float) -> None:
        t = thumbs.get(sci)
        if t is None:
            return
        t = t.convert("RGBA")
        f = min(TH / t.width, TH / t.height)
        t = t.resize((max(1, round(t.width * f)), max(1, round(t.height * f))), Image.LANCZOS)
        print_on(img, t, (round(x0 + (TH - t.width) / 2), round(y_base - TH * 0.7 + (TH - t.height) / 2)))

    b, p, s = stats["birds"], stats["planes"], stats["sounds"]
    y = title("Dziś za oknem", 250)
    for n, label in ((b["today"], "gatunków ptaków"), (p["today"], "usłyszanych samolotów"), (s["trainsToday"], "pociągów")):
        d.text((x0 + TH, y), str(n), font=font(regular, 84), fill=RUBRIC, anchor="rs")
        d.text((tx, y), label, font=font(italic, 56), fill=INK, anchor="ls")
        y += 96
    y = title("Najczęściej w tym tygodniu", y - 96 + GAP + 70)
    top = b["top"][:5]
    most = max([t["count"] for t in top] or [1])
    for t in top:
        thumb(t["sci"], y)
        line(t["name"].capitalize(), italic, 54, INK, tx, y, (x1 - 150) - tx, "ls")
        d.text((x1, y), f"{t['count']}×", font=font(italic, 50), fill=INK_SOFT, anchor="rs")
        d.rectangle((tx, y + 30, tx + max(8, (x1 - 150 - tx) * t["count"] / most), y + 37), fill=RUBRIC)
        y += 120
    if b["chanceNow"]:
        y = title(f"Szansa usłyszenia teraz ({stats['hour']}:00–{stats['hour'] + 1}:00)", y - 120 + GAP + 70)
        for c in b["chanceNow"][:3]:
            thumb(c["sci"], y)
            line(c["name"].capitalize(), italic, 54, INK, tx, y, (x1 - 150) - tx, "ls")
            d.text((x1, y), f"{round(c['now'] * 100)}%", font=font(italic, 50), fill=INK_SOFT, anchor="rs")
            y += 120
    d.text((W - inset - 60, H - inset - 50), "Ryciny · BirdNET, YAMNet, adsb.lol", font=font(italic, 40), fill=INK_SOFT, anchor="rs")

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
