from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ryciny import config  # noqa: E402


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    monkeypatch.setenv("RYCINY_DATA", str(tmp_path))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    return tmp_path


def _config(tmp_path, *, lat=54.352, lon=18.646):
    return config.Config(data=tmp_path, assets=None, lat=lat, lon=lon)


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(-90, -180), (90, 180), (0, 0), (54.352, 18.646)],
)
def test_runtime_location_accepts_finite_inclusive_boundaries(tmp_path, lat, lon):
    cfg = _config(tmp_path)

    result = config.update(cfg, {"lat": lat, "lon": lon})

    assert config.location(cfg) == (float(lat), float(lon))
    assert (result["lat"], result["lon"]) == (float(lat), float(lon))


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"lat": 1}, "provided together"),
        ({"lon": 2}, "provided together"),
        ({"lat": "1", "lon": 2}, "lat"),
        ({"lat": True, "lon": 2}, "lat"),
        ({"lat": float("nan"), "lon": 2}, "lat"),
        ({"lat": 1, "lon": float("inf")}, "lon"),
        ({"lat": -90.0001, "lon": 0}, "lat"),
        ({"lat": 0, "lon": 180.0001}, "lon"),
    ],
)
def test_invalid_runtime_location_is_rejected_before_mutation_or_save(tmp_path, values, message):
    cfg = _config(tmp_path)
    settings = tmp_path / "settings.json"
    before = config.location(cfg)

    with pytest.raises(ValueError, match=message):
        config.update(cfg, values)

    assert config.location(cfg) == before
    assert not settings.exists()


def test_saved_location_overrides_options_and_survives_reload(local_data):
    (local_data / "options.json").write_text(json.dumps({"lat": 1, "lon": 2}))
    cfg = config.load()

    config.update(cfg, {"lat": 12.5, "lon": 34.75})
    reloaded = config.load()

    assert config.location(cfg) == (12.5, 34.75)
    assert config.location(reloaded) == (12.5, 34.75)
    assert json.loads((local_data / "settings.json").read_text())["lat"] == 12.5


def test_coordinate_change_stamps_and_reloads_the_move_fence(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    monkeypatch.setattr(config.time, "time", lambda: 1234.5)

    result = config.update(cfg, {"lat": 12.5, "lon": 34.75})
    saved = json.loads((tmp_path / "settings.json").read_text())
    reloaded = _config(tmp_path)
    config.apply_saved(reloaded)

    assert result["location_changed_at"] == 1_234_500
    assert cfg.location_changed_at == 1_234_500
    assert saved["location_changed_at"] == 1_234_500
    assert config.location(reloaded) == (12.5, 34.75)
    assert reloaded.location_changed_at == 1_234_500


def test_saved_move_fence_is_restored_without_refreshing_time(tmp_path, monkeypatch):
    (tmp_path / "settings.json").write_text(json.dumps({
        "lat": 12.5,
        "lon": 34.75,
        "location_changed_at": 1_234_500,
    }))
    cfg = _config(tmp_path)
    monkeypatch.setattr(config.time, "time", lambda: (_ for _ in ()).throw(AssertionError("fresh timestamp")))

    config.apply_saved(cfg)

    assert config.location(cfg) == (12.5, 34.75)
    assert cfg.location_changed_at == 1_234_500


def test_same_pair_and_unrelated_save_preserve_the_move_fence(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    cfg.location_changed_at = 321
    monkeypatch.setattr(config.time, "time", lambda: 9999)

    config.update(cfg, {"lat": cfg.lat, "lon": cfg.lon})
    config.update(cfg, {"bird_threshold": 0.8})

    assert cfg.location_changed_at == 321
    assert json.loads((tmp_path / "settings.json").read_text())["location_changed_at"] == 321


def test_location_changed_at_is_read_only_for_runtime_and_options(local_data, monkeypatch):
    cfg = _config(local_data)
    cfg.location_changed_at = 321
    monkeypatch.setattr(config.time, "time", lambda: 9999)

    result = config.update(cfg, {"location_changed_at": 999, "bird_threshold": 0.8})

    assert "location_changed_at" not in config.RUNTIME
    assert result["location_changed_at"] == 321
    assert cfg.location_changed_at == 321
    (local_data / "settings.json").unlink()
    (local_data / "options.json").write_text(json.dumps({"location_changed_at": 999}))
    assert config.load().location_changed_at == 0


@pytest.mark.parametrize(
    "saved",
    [
        {"lat": 12},
        {"lat": "12", "lon": 34},
        {"lat": 91, "lon": 34},
        {"lat": 12, "lon": None},
    ],
)
def test_invalid_saved_location_is_rejected_without_partial_config_mutation(tmp_path, saved):
    cfg = _config(tmp_path, lat=10, lon=20)
    (tmp_path / "settings.json").write_text(json.dumps(saved))
    before = config.location(cfg)

    with pytest.raises(ValueError):
        config.apply_saved(cfg)

    assert config.location(cfg) == before


@pytest.mark.parametrize("metadata", [True, -1, 1.0, "123", None])
def test_invalid_saved_move_fence_is_rejected_before_any_mutation(tmp_path, metadata):
    cfg = _config(tmp_path, lat=10, lon=20)
    cfg.location_changed_at = 7
    (tmp_path / "settings.json").write_text(json.dumps({
        "lat": 12,
        "lon": 34,
        "location_changed_at": metadata,
    }))
    before = (config.location(cfg), cfg.location_changed_at)

    with pytest.raises(ValueError, match="location_changed_at"):
        config.apply_saved(cfg)

    assert (config.location(cfg), cfg.location_changed_at) == before


def test_old_saved_settings_default_the_move_fence_to_zero(tmp_path):
    cfg = _config(tmp_path, lat=10, lon=20)
    cfg.location_changed_at = 7
    (tmp_path / "settings.json").write_text(json.dumps({"lat": 12, "lon": 34}))

    config.apply_saved(cfg)

    assert config.location(cfg) == (12.0, 34.0)
    assert cfg.location_changed_at == 0


def test_load_validates_final_coordinates_from_options(local_data):
    (local_data / "options.json").write_text(json.dumps({"lat": 91, "lon": 0}))

    with pytest.raises(ValueError, match="lat"):
        config.load()


def test_failed_atomic_write_leaves_location_and_settings_unchanged(tmp_path, monkeypatch):
    cfg = _config(tmp_path, lat=10, lon=20)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"lat": 10.0, "lon": 20.0}) + "\n")
    before_disk = settings.read_text()

    def fail_replace(*_args):
        raise OSError("disk failure")

    monkeypatch.setattr(config.os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        config.update(cfg, {"lat": 30, "lon": 40})

    assert config.location(cfg) == (10, 20)
    assert cfg.location_changed_at == 0
    assert settings.read_text() == before_disk


def test_location_returns_an_immutable_snapshot(tmp_path):
    cfg = _config(tmp_path, lat=10, lon=20)

    snapshot = config.location(cfg)
    config.update(cfg, {"lat": 30, "lon": 40})

    assert snapshot == (10, 20)
    assert config.location(cfg) == (30.0, 40.0)
