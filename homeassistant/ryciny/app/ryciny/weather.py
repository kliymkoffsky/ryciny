"""Is there a thunderstorm around? Open-Meteo (free, no key), so a jet's rumble is not written down as thunder."""

from __future__ import annotations

import logging
import threading
import time

from . import config, net as http

log = logging.getLogger(__name__)

CACHE_S = 15 * 60


class Weather:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.lock = threading.Lock()
        self.checked = 0.0
        self.codes: list[int] | None = None
        self.origin: tuple[float, float] | None = None

    def thunder(self) -> bool | None:
        """True or False from the weather around the last 3 hours and the next one; None when it cannot be checked."""
        with config.SETTINGS_LOCK:
            origin = config.location(self.cfg)
            with self.lock:
                if self.origin == origin and time.time() - self.checked <= CACHE_S:
                    return self._thunder_locked()

        # Do not hold either lock over the request: settings updates must wake consumers promptly.
        lat, lon = origin
        try:
            r = http.get_json(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat!r}&longitude={lon!r}"
                "&hourly=weather_code&past_hours=3&forecast_hours=1&timezone=UTC")
            codes = [int(c) for c in r["hourly"]["weather_code"] if c is not None]
        except Exception as e:  # noqa: BLE001 - fall back to the microphone alone
            log.warning("weather: %s", e)
            codes = None

        with config.SETTINGS_LOCK:
            if config.location(self.cfg) != origin:
                return None
            with self.lock:
                self.checked = time.time()
                self.codes = codes
                self.origin = origin
                return self._thunder_locked()

    def _thunder_locked(self) -> bool | None:
        """Read the cached result while the caller holds the weather lock."""
        if self.codes is None:
            return None
        return any(c >= 95 for c in self.codes)  # WMO 95-99: thunderstorm
