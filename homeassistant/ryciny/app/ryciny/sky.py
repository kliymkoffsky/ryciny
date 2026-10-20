"""Live aircraft from adsb.lol, type/airline/route from adsbdb: the same rules as Sky.kt."""

from __future__ import annotations

import logging
import math
import threading

from . import config, net as http
from .store import Store, now_ms

log = logging.getLogger(__name__)
R_KM = 6371.0
OFF_ROUTE_KM = 300.0
NEAR_AIRPORT_KM = 80.0
POLL_S = 10


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    return R_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1, lon1, lat2, lon2) -> float:
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def on_route(lat, lon, origin: dict, dest: dict) -> bool:
    """Near either airport, or within OFF_ROUTE_KM of the great circle between them."""
    if None in (origin.get("lat"), origin.get("lon"), dest.get("lat"), dest.get("lon")):
        return True
    f_lat, f_lon, t_lat, t_lon = origin["lat"], origin["lon"], dest["lat"], dest["lon"]
    if haversine_km(lat, lon, f_lat, f_lon) < NEAR_AIRPORT_KM or haversine_km(lat, lon, t_lat, t_lon) < NEAR_AIRPORT_KM:
        return True
    d13 = haversine_km(f_lat, f_lon, lat, lon) / R_KM
    d12 = haversine_km(f_lat, f_lon, t_lat, t_lon) / R_KM
    delta = math.radians(bearing(f_lat, f_lon, lat, lon) - bearing(f_lat, f_lon, t_lat, t_lon))
    cross = math.asin(math.sin(d13) * math.sin(delta))
    along = math.acos(max(-1.0, min(1.0, math.cos(d13) / math.cos(cross))))
    return abs(cross) * R_KM < OFF_ROUTE_KM and math.cos(delta) > 0 and along <= d12 + NEAR_AIRPORT_KM / R_KM


class Sky:
    def __init__(self, cfg, store: Store, types: dict[str, str]) -> None:
        self.cfg = cfg
        self.store = store
        self.types = types
        self.lock = threading.Lock()
        self.planes: list[dict] = []
        self.overhead: dict | None = None
        self.updated_at = 0
        self.heard_at = 0
        self.error: str | None = None
        self._aircraft: dict[str, dict | None] = {}
        self._routes: dict[str, dict | None] = {}
        self._origin: tuple[float, float] | None = None
        self._error_origin: tuple[float, float] | None = None
        self._attempt: tuple[tuple[float, float], int] | None = None
        self._generation = 0
        self._wake = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, daemon=True, name="sky").start()

    def state(self) -> dict:
        """The app's SkyState as JSON."""
        with config.SETTINGS_LOCK:
            origin = config.location(self.cfg)
            with self.lock:
                if self._origin != origin:
                    error = self.error if self._error_origin == origin else None
                    return {"planes": [], "overhead": None, "updatedAt": 0, "error": error, "heardAt": 0}
                return {"planes": self.planes, "overhead": self.overhead, "updatedAt": self.updated_at,
                        "error": self.error, "heardAt": self.heard_at}

    def near(self, km: float, within_ms: int = 90_000) -> bool:
        """A low plane this close was overhead in the last [within_ms]: its rumble fakes thunder, ships and wind."""
        with config.SETTINGS_LOCK:
            origin = config.location(self.cfg)
            max_alt = self.cfg.overhead_max_alt_m
            with self.lock:
                if self._origin != origin:
                    return False
                o, at = self.overhead, self.updated_at
        return bool(o) and now_ms() - at < within_ms and o["distKm"] <= km and (o["altM"] or 0) <= max_alt

    def heard(self, at: int) -> None:
        with config.SETTINGS_LOCK:
            origin = config.location(self.cfg)
            with self.lock:
                if self._origin != origin:
                    return
                generation = self._generation
                self.heard_at = at
                overhead = self.overhead
        if overhead:
            self._record(overhead, at, heard=True, origin=origin, generation=generation)

    def location_changed(self) -> None:
        """Drop aircraft from the old station and wake the normal poll loop immediately."""
        with config.SETTINGS_LOCK:
            with self.lock:
                self._generation += 1
                self._origin = None
                self.planes = []
                self.overhead = None
                self.updated_at = 0
                self.heard_at = 0
                self.error = None
                self._error_origin = None
                self._attempt = None
        self._wake.set()

    def title(self, p: dict) -> str:
        return self.types.get(p["typeCode"].upper()) or p.get("model") or p["typeCode"] or "Statek powietrzny"

    @staticmethod
    def route(p: dict) -> str:
        o, d = p.get("origin"), p.get("destination")
        return f"{o['city']} ({o['iata']}) → {d['city']} ({d['iata']})" if o and d else ""

    def _loop(self) -> None:
        while True:
            self._wake.clear()
            try:
                self._poll()
            except Exception as e:  # noqa: BLE001 - keep polling whatever happens
                log.warning("sky: %s", e)
                self._mark_error(e)
            self._wake.wait(POLL_S)

    def _poll(self) -> None:
        with config.SETTINGS_LOCK:
            lat, lon = config.location(self.cfg)
            nm = max(1, min(250, round(self.cfg.radius_km / 1.852)))
            max_alt = self.cfg.overhead_max_alt_m
            with self.lock:
                generation = self._generation
                self._attempt = ((lat, lon), generation)
        ac = http.get_json(f"https://api.adsb.lol/v2/point/{lat}/{lon}/{nm}").get("ac", [])
        planes = [p for p in (self._parse(a, lat, lon) for a in ac) if p and not p["onGround"]]
        planes.sort(key=lambda p: math.hypot(p["distKm"], (p["altM"] or 0) / 1000))
        low = [p for p in planes if (p["altM"] if p["altM"] is not None else 10**9) <= max_alt]
        overhead = (low or planes or [None])[0]
        if overhead:
            overhead = self._enrich(overhead)
        now = now_ms()
        with config.SETTINGS_LOCK:
            current = config.location(self.cfg)
            with self.lock:
                if current != (lat, lon) or generation != self._generation:
                    return
                self._origin = (lat, lon)
                self.planes = [overhead if overhead and p["hex"] == overhead["hex"] else p for p in planes]
                self.overhead = overhead
                self.updated_at = now
                self.error = None
                self._error_origin = None
                heard = now - self.heard_at < 20_000
        if overhead:
            self._record(overhead, now, heard, origin=(lat, lon), generation=generation)
        with self.lock:
            if self._attempt == ((lat, lon), generation):
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

    def _record(self, p: dict, at: int, heard: bool, origin: tuple[float, float] | None = None,
                generation: int | None = None) -> bool:
        if origin is None:
            with config.SETTINGS_LOCK:
                origin = config.location(self.cfg)
                with self.lock:
                    generation = self._generation
        with config.SETTINGS_LOCK:
            if config.location(self.cfg) != origin:
                return False
            with self.lock:
                if generation != self._generation or self._origin != origin:
                    return False
                self.store.add_plane({
                    "hex": p["hex"], "callsign": p["callsign"], "title": self.title(p), "airline": p.get("airline", ""),
                    "route": self.route(p), "at": at, "lastAt": at, "minDistKm": p["distKm"], "minAltM": p["altM"],
                    "heard": heard, "typeCode": p["typeCode"], "airlineIcao": p.get("airlineIcao", ""),
                })
        return True

    @staticmethod
    def _parse(o: dict, here_lat: float, here_lon: float) -> dict | None:
        lat, lon = o.get("lat"), o.get("lon")
        if lat is None or lon is None:
            return None
        baro = o.get("alt_baro")
        alt_ft = o.get("alt_geom") if o.get("alt_geom") is not None else (baro if isinstance(baro, (int, float)) else None)
        rate = o.get("baro_rate", o.get("geom_rate"))
        return {
            "hex": o.get("hex", ""), "callsign": (o.get("flight") or "").strip(), "typeCode": o.get("t", ""),
            "registration": o.get("r", ""), "altM": round(alt_ft * 0.3048) if alt_ft is not None else None,
            "onGround": baro == "ground", "distKm": haversine_km(here_lat, here_lon, lat, lon),
            "bearing": bearing(here_lat, here_lon, lat, lon), "track": o.get("track"),
            "speedKmh": round(o["gs"] * 1.852) if o.get("gs") is not None else None,
            "climbMs": rate * 0.00508 if rate is not None else None, "lat": lat, "lon": lon,
            "model": "", "airline": "", "airlineIcao": "", "origin": None, "destination": None,
        }

    def _cached(self, cache: dict, key: str, url: str, field: str) -> dict | None:
        if key in cache:
            return cache[key]
        try:
            value = (http.get_json(url).get("response") or {}).get(field)
            cache[key] = value if isinstance(value, dict) else None
        except http.HttpError:
            cache[key] = None  # unknown aircraft or callsign, remembered
        except Exception:  # noqa: BLE001 - network blip, retried next poll
            return None
        return cache[key]

    def _enrich(self, p: dict) -> dict:
        a = self._cached(self._aircraft, p["hex"], f"https://api.adsbdb.com/v0/aircraft/{p['hex']}", "aircraft")
        r = None
        if p["callsign"]:
            r = self._cached(self._routes, p["callsign"], f"https://api.adsbdb.com/v0/callsign/{p['callsign']}", "flightroute")
        airline = (r or {}).get("airline") or {}

        def airport(x):
            if not isinstance(x, dict):
                return None
            return {"iata": x.get("iata_code") or x.get("icao_code") or "", "city": x.get("municipality") or x.get("name") or "",
                    "lat": x.get("latitude"), "lon": x.get("longitude")}

        origin, dest = airport((r or {}).get("origin")), airport((r or {}).get("destination"))
        plausible = origin is not None and dest is not None and on_route(p["lat"], p["lon"], origin, dest)
        return {
            **p,
            "model": " ".join(x for x in ((a or {}).get("manufacturer"), (a or {}).get("type")) if x).strip(),
            "airline": airline.get("name") or (a or {}).get("registered_owner") or "",
            "airlineIcao": airline.get("icao") or (a or {}).get("registered_owner_operator_flag_code") or "",
            "origin": origin if plausible else None,
            "destination": dest if plausible else None,
        }
