"""Which train was heard, from the timetable of every Polish train (mkuran.pl GTFS of PKP PLK open data); as Rails.kt."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import logging
import math
import threading
import time
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, net

log = logging.getLogger(__name__)
FEED_URL = "https://mkuran.pl/gtfs/polish_trains.zip"
FEED_MAX_AGE_S = 3 * 24 * 3600
MAX_KM = 1.5
WINDOW_S = 5 * 60
ZONE = ZoneInfo("Europe/Warsaw")


def _secs(t: str) -> int:
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def passes(feed: Path, date: str, home_lat: float, home_lon: float) -> list[dict]:
    """Every train today whose route passes within MAX_KM of home, with the time it passes (Timetable.kt)."""
    kx = 111.32 * math.cos(math.radians(home_lat))
    ky = 110.57
    with zipfile.ZipFile(feed) as z:
        def rows(name):
            with z.open(name) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))

        stops = {r["stop_id"]: (r["parent_station"] or r["stop_id"], (float(r["stop_lon"]) - home_lon) * kx,
                                (float(r["stop_lat"]) - home_lat) * ky, r["stop_name"]) for r in rows("stops.txt")}
        services = {r["service_id"] for r in rows("calendar_dates.txt") if r["date"] == date and r["exception_type"] == "1"}
        agencies = {r["route_id"]: r["route_long_name"] for r in rows("routes.txt")}
        trips = {r["trip_id"]: (r["route_id"], r["trip_short_name"], r.get("plk_train_name", ""))
                 for r in rows("trips.txt") if r["service_id"] in services}
        best: dict[str, tuple[float, float, str]] = {}
        first: dict[str, str] = {}
        last: dict[str, str] = {}
        prev = None  # (stop, departure, trip)
        prev_trip = ""
        for r in rows("stop_times.txt"):
            trip = r["trip_id"]
            if trip not in trips:
                continue
            stop = stops.get(r["stop_id"])
            if stop is None:
                continue
            if trip != prev_trip:
                first[trip] = stop[3]
                prev = None
                prev_trip = trip
            last[trip] = stop[3]
            if prev is not None and prev[2] == trip and min(math.hypot(prev[0][1], prev[0][2]), math.hypot(stop[1], stop[2])) < 8:
                ax, ay = prev[0][1], prev[0][2]
                dx, dy = stop[1] - ax, stop[2] - ay
                length = dx * dx + dy * dy
                f = 0.0 if length == 0 else max(0.0, min(1.0, (-ax * dx - ay * dy) / length))
                dist = math.hypot(ax + f * dx, ay + f * dy)
                if dist < MAX_KM and best.get(trip, (math.inf,))[0] > dist:
                    best[trip] = (dist, prev[1] + f * (_secs(r["arrival_time"]) - prev[1]), f"{prev[0][3]} – {stop[3]}")
            prev = (stop, _secs(r["departure_time"]), trip)
    out = []
    for trip_id, (dist, sec, between) in best.items():
        route, number, name = trips[trip_id]
        out.append({"passSec": int(sec) % 86_400, "agency": agencies.get(route, ""), "number": number, "name": name,
                    "from": first.get(trip_id, ""), "to": last.get(trip_id, ""), "between": between, "distKm": dist})
    return sorted(out, key=lambda p: p["passSec"])


def title(p: dict) -> str:
    return " ".join(x for x in (p["agency"], p["number"], p["name"]) if x)


def hhmm(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


def location_key(lat: float, lon: float) -> str:
    """Stable cache identity for the exact floating-point coordinate pair."""
    payload = f"{lat!r},{lon!r}".encode("ascii")
    return hashlib.sha256(payload).hexdigest()


class Rails:
    def __init__(self, cfg, store) -> None:
        self.cfg = cfg
        self.store = store
        self.dir = cfg.data / "rails"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.feed = self.dir / "polish_trains.zip"
        self.date = ""
        self.list: list[dict] = []
        self.error: str | None = None
        self.lock = threading.Lock()
        self.origin: tuple[float, float] | None = None
        self._error_origin: tuple[float, float] | None = None
        self._attempt: tuple[tuple[float, float], int] | None = None
        self._generation = 0
        self._location_fence = cfg.location_changed_at
        self._wake = threading.Event()

    def start(self) -> None:
        if self.cfg.trains:
            threading.Thread(target=self._loop, daemon=True, name="rails").start()

    def state(self) -> dict:
        with config.SETTINGS_LOCK:
            origin = config.location(self.cfg)
            with self.lock:
                if self.origin != origin:
                    error = self.error if self._error_origin == origin else None
                    return {"date": "", "count": 0, "error": error}
                return {"date": self.date, "count": len(self.list), "error": self.error}

    def match(self, at_ms: int) -> dict | None:
        sec = dt.datetime.fromtimestamp(at_ms / 1000, ZONE).time()
        sec = sec.hour * 3600 + sec.minute * 60 + sec.second
        with config.SETTINGS_LOCK:
            origin = config.location(self.cfg)
            with self.lock:
                if self.origin != origin or at_ms < self._location_fence:
                    return None
                best = min(self.list, key=lambda p: abs(p["passSec"] - sec), default=None)
        return best if best is not None and abs(best["passSec"] - sec) <= WINDOW_S else None

    def details(self, p: dict) -> tuple[str, str, str]:
        return title(p), f"{p['from']} → {p['to']} · planowo {hhmm(p['passSec'])}", p["agency"]

    def _loop(self) -> None:
        while True:
            self._wake.clear()
            try:
                self._ensure_today()
            except Exception as e:  # noqa: BLE001
                log.warning("rails: %s", e)
                self._mark_error(e)
            self._wake.wait(30 * 60)

    def location_changed(self) -> None:
        """Invalidate the timetable and wake the long interval poll after a station move."""
        with config.SETTINGS_LOCK:
            with self.lock:
                self._generation += 1
                self.origin = None
                self.date = ""
                self.list = []
                self.error = None
                self._error_origin = None
                self._attempt = None
                self._location_fence = self.cfg.location_changed_at
        self._wake.set()

    def _ensure_today(self) -> None:
        today = dt.datetime.now(ZONE).strftime("%Y%m%d")
        with config.SETTINGS_LOCK:
            origin = config.location(self.cfg)
            with self.lock:
                generation = self._generation
                if today == self.date and self.origin == origin:
                    return
                fence = self._location_fence
                self._attempt = (origin, generation)
        lat, lon = origin
        index = self.dir / f"passes-{today}-{location_key(lat, lon)}.json"
        if index.exists():
            found = json.loads(index.read_text())
        else:
            if not self.feed.exists() or time.time() - self.feed.stat().st_mtime > FEED_MAX_AGE_S:
                log.info("downloading %s", FEED_URL)
                tmp = self.feed.with_suffix(".tmp")
                tmp.write_bytes(net.get(FEED_URL, timeout=300))
                tmp.replace(self.feed)
            started = time.time()
            found = passes(self.feed, today, lat, lon)
            log.info("rails: %d passes in %.1f s", len(found), time.time() - started)
            index.write_text(json.dumps(found, ensure_ascii=False))
            for old in self.dir.glob("passes-*.json"):
                if old != index:
                    old.unlink(missing_ok=True)
        with config.SETTINGS_LOCK:
            if config.location(self.cfg) != origin:
                return
            with self.lock:
                if generation != self._generation:
                    return
                self.date, self.list, self.error, self.origin = today, found, None, origin
                self._error_origin = None
                fence = self._location_fence
            # Keep the global settings lock while backfilling so a station update cannot mix origins.
            today_start = int(dt.datetime.now(ZONE).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            self.store.fill_sounds("train", lambda e: self.details(m) if e["at"] >= today_start and e["at"] >= fence and (m := self.match(e["at"])) else None)
        with self.lock:
            if self._attempt == (origin, generation):
                self._attempt = None

    def _mark_error(self, error: Exception) -> None:
        """Expose a failed request only when its captured origin is still current."""
        with config.SETTINGS_LOCK:
            current = config.location(self.cfg)
            with self.lock:
                attempt = self._attempt
                if attempt is None or current != attempt[0] or self._generation != attempt[1]:
                    return
                self.error = str(error)
                self._error_origin = attempt[0]
