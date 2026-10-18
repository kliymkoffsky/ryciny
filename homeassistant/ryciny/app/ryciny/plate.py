"""One plate as a picture, for a browser, an e-ink frame or a TV: the newest thing seen or heard, on laid paper."""

from __future__ import annotations

import datetime as dt
import io

from PIL import Image, ImageDraw, ImageFont

from .store import now_ms

PAPER = (243, 234, 215)
INK = (43, 33, 24)
INK_SOFT = (107, 91, 74)
# E Ink Spectra 6: the panel's own six inks, for frames that take the picture 1:1.
SPECTRA6 = [(0, 0, 0), (255, 255, 255), (255, 255, 0), (255, 0, 0), (0, 0, 255), (0, 255, 0)]


def hhmm(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000).strftime("%H:%M")


def newest(journal: dict, sounds: dict, lookback_h: int = 12, sounds_on=lambda key: True) -> dict | None:
    """The newest plate: a heard plane, a bird, a dog or a sound, with what to draw and say."""
    since = now_ms() - lookback_h * 3600_000
    found = []
    planes = [p for p in journal["planes"] if p["heard"] and p["lastAt"] >= since]
    if planes:
        p = max(planes, key=lambda x: x["lastAt"])
        found.append((p["at"], {"kind": "PLANE", "key": f"{p.get('typeCode') or p['title']}-{p.get('airlineIcao') or p['airline'] or 'plain'}",
                                 "subject": p["title"], "airline": p["airline"], "title": p["title"],
                                 "lines": [" · ".join(x for x in (p["airline"], p["callsign"]) if x), p["route"], f"słychać było o {hhmm(p['at'])}"]}))
    birds = [b for b in journal["birds"] if b["lastAt"] >= since]
    if birds:
        b = max(birds, key=lambda x: x["lastAt"])
        found.append((b["lastAt"], {"kind": "BIRD", "key": b["sci"], "subject": b["sci"], "title": b["name"].capitalize(),
                                     "lines": [b["sci"], f"ostatnio {hhmm(b['lastAt'])}"]}))
    for e in journal["sounds"]:
        s = sounds.get(e["key"])
        if s and e["lastAt"] >= since and sounds_on(e["key"]):
            key = f"{e['key']}-{e['variant']}" if e["variant"] else e["key"]
            found.append((e["at"], {"kind": "SCENE", "key": key, "subject": s["now"], "prompt": s["prompt"], "title": s["past"],
                                     "lines": [e["title"], e["subtitle"], f"{hhmm(e['at'])}–{hhmm(e['lastAt'])}"]}))
    if not found:
        return None
    at, plate = max(found, key=lambda x: x[0])
    plate["at"] = at
    plate["lines"] = [x for x in plate["lines"] if x]
    return plate


def render(plate: dict | None, engraving: Image.Image | None, fonts: tuple[str, str], w: int, h: int, palette: str = "full") -> bytes:
    # On a 6-colour panel the paper tint only dithers into coloured speckle: draw on plain white there.
    img = Image.new("RGB", (w, h), PAPER if palette == "full" else (255, 255, 255))
    if palette == "full":
        noise = Image.effect_noise((w, h), 6).convert("L")
        img = Image.composite(img, Image.new("RGB", (w, h), (232, 222, 200)), noise.point(lambda v: 255 if v > 118 else 235))
    d = ImageDraw.Draw(img)
    inset = round(h * 0.035)
    d.rectangle((inset, inset, w - inset, h - inset), outline=INK_SOFT, width=max(1, h // 700))
    regular, italic = fonts
    unit = h / 100

    def text(s: str, path: str, size: float, color, y: float) -> None:
        font = ImageFont.truetype(path, max(8, round(size)))
        while d.textlength(s, font=font) > w * 0.86 and font.size > size * 0.5:
            font = ImageFont.truetype(path, font.size - 1)
        d.text((w / 2, y), s, font=font, fill=color, anchor="ms")

    text(dt.datetime.now().strftime("%d.%m.%Y, %H:%M"), italic, 2.8 * unit, INK_SOFT, 9 * unit)
    if plate is None:
        text("Cisza: nic nie przeleciało, nie zaśpiewało ani nie zaszczekało", italic, 3.6 * unit, INK_SOFT, 50 * unit)
    else:
        if engraving is not None:
            box_w, box_h = w * 0.64, 59 * unit
            e = engraving.convert("RGBA")
            f = min(box_w / e.width, box_h / e.height)
            e = e.resize((max(1, round(e.width * f)), max(1, round(e.height * f))), Image.LANCZOS)
            img.paste(e, (round((w - e.width) / 2), round(72 * unit - e.height)), e)
        text(plate["title"], regular, 6.2 * unit, INK, 81 * unit)
        for i, line in enumerate(plate["lines"][:3]):
            text(line, italic, 3.2 * unit, INK if i == 0 else INK_SOFT, (86.5 + i * 4.2) * unit)
    if palette == "spectra6":
        pal = Image.new("P", (1, 1))
        pal.putpalette([c for rgb in SPECTRA6 for c in rgb] + [0] * (768 - 18))
        img = img.quantize(palette=pal, dither=Image.FLOYDSTEINBERG).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
