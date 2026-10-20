"""Settings: Home Assistant add-on options (/data/options.json) or environment variables for local runs."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_STATION_TITLE = "Dźwięki Dolnego Migowa"


@dataclass
class Config:
    data: Path
    assets: Path | None  # a checkout of the repo's android assets + shared/, else downloaded on first start
    port: int = 8099
    lat: float = 54.352
    lon: float = 18.646
    location_changed_at: int = 0
    station_title: str = DEFAULT_STATION_TITLE
    audio_command: str = "parec --format=float32le --rate=48000 --channels=1 --raw"
    image_provider: str = "openai"  # openai | gemini | openrouter | none
    openai_key: str = ""
    openai_model: str = "gpt-image-1"
    animation_playback: bool = False
    animation_generate: bool = False
    animation_model: str = "gpt-image-2.5-sunburst"
    gemini_key: str = ""
    gemini_model: str = "gemini-2.5-flash-image"
    openrouter_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash-image"
    bird_threshold: float = 0.7
    range_filter: bool = True
    bark_threshold: float = 0.35
    dog_match: float = 0.85
    radius_km: float = 15.0
    overhead_max_alt_m: int = 3500
    trains: bool = True
    sounds_off: list[str] = field(default_factory=lambda: ["sheep", "goat"])
    sounds_on: list[str] = field(default_factory=list)
    lookback_hours: int = 12
    public_url: str = ""  # the Worker in public-site/, e.g. https://dzwieki-migowa.<konto>.workers.dev
    public_token: str = ""
    frame_on: bool = False  # Samsung The Frame: send the TV plate (tvplate.py)
    frame_host: str = ""
    frame_every_min: int = 5
    prefer_bundled_art: bool = False  # bundled engravings (with animations) instead of the add-on's own ones
    art_daily_limit: int = 30  # paid engravings a day at most (0 = no limit)
    mic_gain_db: float = 0.0  # a quiet microphone: YAMNet misses planes below about -40 dBFS


SETTINGS_LOCK = threading.RLock()

_LOCATION_LIMITS = {
    "lat": (-90.0, 90.0),
    "lon": (-180.0, 180.0),
}


def _validated_coordinate(name: str, value: object) -> float:
    """Validate one runtime GPS coordinate and return its normalized float value."""

    limits = _LOCATION_LIMITS[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number between {limits[0]:g} and {limits[1]:g}")
    try:
        coordinate = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number between {limits[0]:g} and {limits[1]:g}") from error
    if not math.isfinite(coordinate) or not limits[0] <= coordinate <= limits[1]:
        raise ValueError(f"{name} must be a finite number between {limits[0]:g} and {limits[1]:g}")
    return coordinate


def _validated_location(lat: object, lon: object) -> tuple[float, float]:
    """Validate and normalize a complete GPS pair."""

    return _validated_coordinate("lat", lat), _validated_coordinate("lon", lon)


def _validated_location_changed_at(value: object) -> int:
    """Validate the persisted move fence without accepting client numeric coercions."""

    if type(value) is not int or value < 0:
        raise ValueError("location_changed_at must be a non-negative integer")
    return value


def _validated_station_title(value: object) -> str:
    """Validate and canonicalize the public listening-station title."""

    if not isinstance(value, str):
        raise ValueError("station_title must be a non-empty string of at most 120 characters without control characters")
    if any(unicodedata.category(character) in ("Cc", "Zl", "Zp") for character in value):
        raise ValueError("station_title must be a non-empty string of at most 120 characters without control characters")
    title = value.strip()
    if not title or len(title) > 120:
        raise ValueError("station_title must be a non-empty string of at most 120 characters without control characters")
    return title


def location(cfg: Config) -> tuple[float, float]:
    """Return one lock-protected snapshot of the current GPS pair."""

    with SETTINGS_LOCK:
        return cfg.lat, cfg.lon


def load() -> Config:
    data = Path(os.environ.get("RYCINY_DATA", "/data"))
    data.mkdir(parents=True, exist_ok=True)
    options: dict = {}
    options_file = data / "options.json"
    if options_file.exists():
        options = json.loads(options_file.read_text())
    assets = os.environ.get("RYCINY_ASSETS")
    cfg = Config(data=data, assets=Path(assets) if assets else None)
    for key, value in options.items():
        if key != "location_changed_at" and hasattr(cfg, key) and value is not None and value != "":
            setattr(cfg, key, value)
    # In Home Assistant, the home location comes from HA itself unless the options set one.
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token and ("lat" not in options or "lon" not in options):
        try:
            import urllib.request

            req = urllib.request.Request("http://supervisor/core/api/config", headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                ha = json.loads(r.read())
            cfg.lat, cfg.lon = float(ha["latitude"]), float(ha["longitude"])
        except Exception:  # noqa: BLE001 - fall back to the defaults
            pass
    if os.environ.get("RYCINY_PORT"):
        cfg.port = int(os.environ["RYCINY_PORT"])
    if os.environ.get("RYCINY_AUDIO"):
        cfg.audio_command = os.environ["RYCINY_AUDIO"]
    apply_saved(cfg)
    cfg.lat, cfg.lon = _validated_location(cfg.lat, cfg.lon)
    cfg.location_changed_at = _validated_location_changed_at(cfg.location_changed_at)
    cfg.station_title = _validated_station_title(cfg.station_title)
    for option in ("animation_playback", "animation_generate"):
        if type(getattr(cfg, option)) is not bool:
            raise ValueError(f"{option} must be a boolean")
        env_name = "RYCINY_" + option.upper()
        animation_env = os.environ.get(env_name)
        if animation_env is not None:
            normalized = animation_env.strip().lower()
            if normalized not in ("1", "0", "true", "false"):
                raise ValueError(f"{env_name} must be 1, 0, true, or false")
            setattr(cfg, option, normalized in ("1", "true"))
    cfg.animation_model = _validated_animation_model(os.environ.get("RYCINY_ANIMATION_MODEL", cfg.animation_model))
    return cfg


# What the dashboard may change at run time (kept in /data/settings.json, over the add-on options). Keys stay in options.
RUNTIME = {
    "bird_threshold": float, "range_filter": bool, "bark_threshold": float, "dog_match": float,
    "radius_km": float, "overhead_max_alt_m": int, "trains": bool, "sounds_off": list, "sounds_on": list,
    "image_provider": str, "lookback_hours": int, "mic_gain_db": float,
    "frame_on": bool, "frame_host": str, "frame_every_min": int, "art_daily_limit": int, "prefer_bundled_art": bool,
    "animation_playback": bool, "animation_generate": bool, "animation_model": str,
    "lat": float, "lon": float, "station_title": str,
}


def runtime(cfg: Config) -> dict:
    with SETTINGS_LOCK:
        values = {k: getattr(cfg, k) for k in RUNTIME if hasattr(cfg, k)}
        values["location_changed_at"] = cfg.location_changed_at
        return values


def apply_saved(cfg: Config) -> None:
    f = cfg.data / "settings.json"
    if not f.exists():
        return
    saved = json.loads(f.read_text())
    if not isinstance(saved, dict):
        raise ValueError("settings body must be an object")
    saved_location_changed_at = _validated_location_changed_at(saved.get("location_changed_at", 0))
    values = {key: value for key, value in saved.items() if key != "location_changed_at"}
    with SETTINGS_LOCK:
        update(cfg, values, save=False)
        cfg.location_changed_at = saved_location_changed_at


def _validated_animation_model(value: object) -> str:
    """Validate a bounded provider model identifier without restricting configured custom IDs."""

    if not isinstance(value, str):
        raise ValueError("animation_model must be a non-empty model ID of at most 160 characters")
    model = value.strip()
    if (not model or len(model) > 160 or
            any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in model)):
        raise ValueError("animation_model must be a non-empty model ID of at most 160 characters")
    return model


def _validated_runtime(values: dict) -> dict:
    """Stage runtime values before mutation so invalid settings requests remain all-or-nothing."""

    if not isinstance(values, dict):
        raise ValueError("settings body must be an object")
    coordinates = {key for key in ("lat", "lon") if key in values}
    if coordinates and coordinates != {"lat", "lon"}:
        raise ValueError("lat and lon must be provided together")
    staged = {}
    for key, value in values.items():
        kind = RUNTIME.get(key)
        if kind is None:
            continue
        if key in ("lat", "lon"):
            staged[key] = _validated_coordinate(key, value)
        elif key in ("animation_playback", "animation_generate"):
            if type(value) is not bool:
                raise ValueError(f"{key} must be a boolean")
            staged[key] = value
        elif key == "animation_model":
            staged[key] = _validated_animation_model(value)
        elif key == "station_title":
            staged[key] = _validated_station_title(value)
        elif kind is list:
            staged[key] = [str(item) for item in value]
        elif kind is str and key == "image_provider" and value not in ("openai", "gemini", "openrouter", "none"):
            continue
        else:
            staged[key] = kind(value)
    return staged


def _save_runtime(path: Path, values: dict) -> None:
    """Replace settings.json atomically so readers never observe a partial document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as output:
            temporary = Path(output.name)
            json.dump(values, output, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def update(cfg: Config, values: dict, save: bool = True) -> dict:
    with SETTINGS_LOCK:
        staged = _validated_runtime(values)
        before_location = location(cfg)
        if save and "lat" in staged and "lon" in staged and (staged["lat"], staged["lon"]) != before_location:
            staged["location_changed_at"] = int(time.time() * 1000)
        updated = runtime(cfg)
        updated.update(staged)
        if save:
            _save_runtime(cfg.data / "settings.json", updated)
        for key, value in staged.items():
            setattr(cfg, key, value)
        return runtime(cfg)
