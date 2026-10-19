"""Settings: Home Assistant add-on options (/data/options.json) or environment variables for local runs."""

from __future__ import annotations

import json
import os
import tempfile
import threading
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
    art_daily_limit: int = 30  # paid engravings a day at most (0 = no limit)
    mic_gain_db: float = 0.0  # a quiet microphone: YAMNet misses planes below about -40 dBFS


SETTINGS_LOCK = threading.RLock()


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
    "frame_on": bool, "frame_host": str, "frame_every_min": int, "art_daily_limit": int,
    "animation_playback": bool, "animation_generate": bool, "animation_model": str,
}


def runtime(cfg: Config) -> dict:
    with SETTINGS_LOCK:
        return {k: getattr(cfg, k) for k in RUNTIME if hasattr(cfg, k)}


def apply_saved(cfg: Config) -> None:
    f = cfg.data / "settings.json"
    if f.exists():
        update(cfg, json.loads(f.read_text()), save=False)


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
    """Stage runtime values before mutation so invalid animation requests remain all-or-nothing."""

    if not isinstance(values, dict):
        raise ValueError("settings body must be an object")
    staged = {}
    for key, value in values.items():
        kind = RUNTIME.get(key)
        if kind is None:
            continue
        if key in ("animation_playback", "animation_generate"):
            if type(value) is not bool:
                raise ValueError(f"{key} must be a boolean")
            staged[key] = value
        elif key == "animation_model":
            staged[key] = _validated_animation_model(value)
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
        updated = runtime(cfg)
        updated.update(staged)
        if save:
            _save_runtime(cfg.data / "settings.json", updated)
        for key, value in staged.items():
            setattr(cfg, key, value)
        return runtime(cfg)
