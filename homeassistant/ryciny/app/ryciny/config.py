"""Settings: Home Assistant add-on options (/data/options.json) or environment variables for local runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    data: Path
    assets: Path | None  # a checkout of the repo's android assets + shared/, else downloaded on first start
    port: int = 8099
    lat: float = 54.352
    lon: float = 18.646
    audio_command: str = "parec --format=float32le --rate=48000 --channels=1 --raw"
    image_provider: str = "openai"  # openai | gemini | openrouter | none
    openai_key: str = ""
    openai_model: str = "gpt-image-1"
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
    mic_gain_db: float = 0.0  # a quiet microphone: YAMNet misses planes below about -40 dBFS


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
        if hasattr(cfg, key) and value is not None and value != "":
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
    return cfg


# What the dashboard may change at run time (kept in /data/settings.json, over the add-on options). Keys stay in options.
RUNTIME = {
    "bird_threshold": float, "range_filter": bool, "bark_threshold": float, "dog_match": float,
    "radius_km": float, "overhead_max_alt_m": int, "trains": bool, "sounds_off": list, "sounds_on": list,
    "image_provider": str, "lookback_hours": int, "mic_gain_db": float,
    "frame_on": bool, "frame_host": str, "frame_every_min": int,
}


def runtime(cfg: Config) -> dict:
    return {k: getattr(cfg, k) for k in RUNTIME if hasattr(cfg, k)}


def apply_saved(cfg: Config) -> None:
    f = cfg.data / "settings.json"
    if f.exists():
        update(cfg, json.loads(f.read_text()), save=False)


def update(cfg: Config, values: dict, save: bool = True) -> dict:
    for k, v in values.items():
        kind = RUNTIME.get(k)
        if kind is None:
            continue
        if kind is list:
            v = [str(x) for x in v]
        elif kind is str and k == "image_provider" and v not in ("openai", "gemini", "openrouter", "none"):
            continue
        else:
            v = kind(v)
        setattr(cfg, k, v)
    if save:
        (cfg.data / "settings.json").write_text(json.dumps(runtime(cfg), ensure_ascii=False))
    return runtime(cfg)
