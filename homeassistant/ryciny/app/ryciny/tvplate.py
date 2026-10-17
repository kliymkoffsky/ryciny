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

from PIL import Image, ImageDraw, ImageFont

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


def render(plate: dict | None, engraving: Image.Image | None, about: str, stats: dict, fonts: tuple[str, str],
           thumbs: dict[str, Image.Image] | None = None) -> bytes:
    thumbs = thumbs or {}
    regular, italic = fonts
    img = Image.new("RGB", (W, H), PAPER)
    noise = Image.effect_noise((W // 4, H // 4), 6).convert("L").resize((W, H))
    img = Image.composite(img, Image.new("RGB", (W, H), (232, 222, 200)), noise.point(lambda v: 255 if v > 118 else 235))
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
            img.paste(e, (round(cx - e.width / 2), round(300 + (box_h - e.height) / 2)), e)
        y = 300 + H * 0.5 + 150
        line(plate["title"], regular, 150, INK, cx, y, left_w * 0.9)
        y += 95
        for i, l in enumerate(plate["lines"][:3]):
            line(l, italic, 66, INK if i == 0 else INK_SOFT, cx, y, left_w * 0.9)
            y += 82
        if about:
            wrap(about, italic, 54, INK_SOFT, cx, y + 30, left_w * 0.82, 3)

    # Right: statistics.
    x0 = inset + left_w + 40
    d.line((x0 - 40, 260, x0 - 40, H - 260), fill=INK_SOFT, width=2)
    rw = W - inset - 90 - x0
    y = 260
    line("Dziś za oknem", regular, 84, RUBRIC, x0, y, rw, "ls")
    y += 110
    b, p, s = stats["birds"], stats["planes"], stats["sounds"]
    for n, label in ((b["today"], "gatunków ptaków"), (p["today"], "usłyszanych samolotów"), (s["trainsToday"], "pociągów")):
        d.text((x0, y), str(n), font=font(regular, 96), fill=RUBRIC, anchor="ls")
        d.text((x0 + 190, y), label, font=font(italic, 58), fill=INK, anchor="ls")
        y += 105
    y += 40
    line("Najczęściej w tym tygodniu", regular, 66, RUBRIC, x0, y, rw, "ls")
    y += 85
    TH = 104  # engraving thumbnail beside each bird

    def thumb(sci: str, y_base: float) -> None:
        t = thumbs.get(sci)
        if t is None:
            return
        t = t.convert("RGBA")
        f = min(TH / t.width, TH / t.height)
        t = t.resize((max(1, round(t.width * f)), max(1, round(t.height * f))), Image.LANCZOS)
        img.paste(t, (round(x0 + (TH - t.width) / 2), round(y_base - TH * 0.72 + (TH - t.height) / 2)), t)

    tx = x0 + TH + 26
    top = b["top"][:5]
    most = max([t["count"] for t in top] or [1])
    for t in top:
        thumb(t["sci"], y)
        line(t["name"].capitalize(), italic, 54, INK, tx, y, rw * 0.62, "ls")
        d.text((x0 + rw, y), f"{t['count']}×", font=font(italic, 50), fill=INK_SOFT, anchor="rs")
        d.rectangle((tx, y + 22, tx + max(8, (x0 + rw * 0.9 - tx) * t["count"] / most), y + 30), fill=RUBRIC)
        y += 122
    y += 30
    if b["chanceNow"]:
        line(f"Szansa usłyszenia teraz ({stats['hour']}:00–{stats['hour'] + 1}:00)", regular, 60, RUBRIC, x0, y, rw, "ls")
        y += 80
        for c in b["chanceNow"][:3]:
            thumb(c["sci"], y + 10)
            line(c["name"].capitalize(), italic, 52, INK, tx, y + 10, rw * 0.6, "ls")
            d.text((x0 + rw, y + 10), f"{round(c['now'] * 100)}%", font=font(italic, 52), fill=INK_SOFT, anchor="rs")
            y += 118
    d.text((W - inset - 60, H - inset - 50), "Ryciny · BirdNET, YAMNet, adsb.lol", font=font(italic, 40), fill=INK_SOFT, anchor="rs")

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()
