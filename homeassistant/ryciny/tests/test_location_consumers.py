from __future__ import annotations

import datetime as dt
import threading
import time
import types
from pathlib import Path

import numpy as np
import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
import sys

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# The tests replace both model wrappers with fakes; keep collection independent of model wheels.
interpreter_module = types.ModuleType("ai_edge_litert.interpreter")
interpreter_module.Interpreter = object
litert_module = types.ModuleType("ai_edge_litert")
litert_module.interpreter = interpreter_module
sys.modules.setdefault("ai_edge_litert", litert_module)
sys.modules.setdefault("ai_edge_litert.interpreter", interpreter_module)

from ryciny import analyzer, config, ml, rails, sky, weather  # noqa: E402


@pytest.fixture(autouse=True)
def locked_location(monkeypatch):
    def location(cfg):
        with config.SETTINGS_LOCK:
            return float(cfg.lat), float(cfg.lon)

    monkeypatch.setattr(config, "location", location, raising=False)


def make_config(tmp_path, lat=54.3521, lon=18.6461):
    return config.Config(data=tmp_path, assets=None, lat=lat, lon=lon)


class PlaneStore:
    def __init__(self):
        self.planes = []

    def add_plane(self, plane):
        self.planes.append(plane)


class TimetableStore:
    def __init__(self, events=None):
        self.events = events or []
        self.filled = []

    def fill_sounds(self, key, details):
        assert key == "train"
        for event in self.events:
            value = details(event)
            self.filled.append((event["at"], value))


def aircraft(hex_code="abc123", lat=54.36, lon=18.65):
    return {"hex": hex_code, "flight": "LOT123", "t": "B738", "lat": lat, "lon": lon,
            "alt_baro": 2000, "gs": 300, "track": 90}


def test_birdnet_range_mask_keeps_full_coordinate_precision():
    class Meta:
        def __init__(self):
            self.calls = []

        def get_input_details(self):
            return [{"index": 1}]

        def set_tensor(self, index, value):
            self.calls.append(value.copy())

        def invoke(self):
            pass

        def get_output_details(self):
            return [{"index": 2}]

        def get_tensor(self, index):
            return np.array([[1.0]], dtype=np.float32)

    birdnet = ml.BirdNet.__new__(ml.BirdNet)
    birdnet.meta = Meta()
    birdnet._mask_key = None
    birdnet._mask = None
    date = dt.date(2026, 10, 20)

    birdnet.range_mask(54.3521, 18.6461, date)
    birdnet.range_mask(54.3522, 18.6462, date)

    assert len(birdnet.meta.calls) == 2
    assert birdnet._mask_key[:2] == (54.3522, 18.6462)


def test_analyzer_reads_coordinates_through_shared_accessor(monkeypatch):
    seen = []

    class BirdNet:
        labels = [ml.Label("Pica pica", "sroka", True)]

        def range_mask(self, lat, lon):
            seen.append((lat, lon))
            return np.array([True])

    class Store:
        def add_bird(self, *args, **kwargs):
            pass

    cfg = make_config(Path("/tmp"), 54.3521, 18.6461)
    subject = analyzer.Analyzer.__new__(analyzer.Analyzer)
    subject.cfg = cfg
    subject.birdnet = BirdNet()
    subject.store = Store()
    subject._birds(np.array([0.9]), 1, lambda: True, lambda: b"")

    assert seen == [(54.3521, 18.6461)]


def test_sky_discards_an_inflight_poll_after_location_change(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    store = PlaneStore()
    subject = sky.Sky(cfg, store, {})
    subject._enrich = lambda plane: plane
    started = threading.Event()
    release = threading.Event()

    def get_json(url):
        started.set()
        release.wait(2)
        return {"ac": [aircraft()]}

    monkeypatch.setattr(sky.http, "get_json", get_json)
    worker = threading.Thread(target=subject._poll)
    worker.start()
    assert started.wait(1)
    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 51.1079, 17.0385
        subject.location_changed()
    release.set()
    worker.join(2)

    assert subject.state()["planes"] == []
    assert store.planes == []


def test_sky_state_near_and_heard_hide_old_origin(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    store = PlaneStore()
    subject = sky.Sky(cfg, store, {})
    subject._enrich = lambda plane: plane
    monkeypatch.setattr(sky.http, "get_json", lambda url: {"ac": [aircraft()]})
    subject._poll()
    assert subject.state()["planes"]

    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 51.1079, 17.0385
    before = len(store.planes)
    assert subject.state()["planes"] == []
    assert not subject.near(3)
    subject.heard(123)
    assert len(store.planes) == before


def test_sky_location_changed_wakes_polling():
    cfg = make_config(Path("/tmp"))
    subject = sky.Sky(cfg, PlaneStore(), {})
    assert not subject._wake.is_set()
    subject.location_changed()
    assert subject._wake.is_set()


def test_sky_current_error_is_visible_and_stale_error_is_hidden(tmp_path):
    cfg = make_config(tmp_path)
    subject = sky.Sky(cfg, PlaneStore(), {})
    with subject.lock:
        subject._attempt = ((cfg.lat, cfg.lon), subject._generation)
    subject._mark_error(RuntimeError("current failure"))
    assert subject.state()["error"] == "current failure"

    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 51.1079, 17.0385
        subject.location_changed()
    with subject.lock:
        subject._attempt = ((54.3521, 18.6461), subject._generation - 1)
    subject._mark_error(RuntimeError("stale failure"))
    assert subject.state()["error"] is None


def test_rails_cache_key_distinguishes_coordinates_within_rounded_cell(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    subject = rails.Rails(cfg, TimetableStore())
    subject.feed.write_bytes(b"fixture")
    calls = []

    def fake_passes(feed, date, lat, lon):
        calls.append((date, lat, lon))
        return []

    monkeypatch.setattr(rails, "passes", fake_passes)
    subject._ensure_today()
    first_files = set(subject.dir.glob("passes-*.json"))
    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 54.3522, 18.6462
    subject._ensure_today()
    second_files = set(subject.dir.glob("passes-*.json"))

    assert calls == [(calls[0][0], 54.3521, 18.6461), (calls[0][0], 54.3522, 18.6462)]
    assert rails.location_key(54.3521, 18.6461) != rails.location_key(54.3522, 18.6462)
    assert first_files != second_files


def test_rails_discards_stale_inflight_timetable(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    store = TimetableStore()
    subject = rails.Rails(cfg, store)
    subject.feed.write_bytes(b"fixture")
    started = threading.Event()
    release = threading.Event()

    def fake_passes(feed, date, lat, lon):
        started.set()
        release.wait(2)
        return [{"passSec": 1, "agency": "A", "number": "1", "name": "old", "from": "x", "to": "y",
                 "between": "x – y", "distKm": 1.0}]

    monkeypatch.setattr(rails, "passes", fake_passes)
    worker = threading.Thread(target=subject._ensure_today)
    worker.start()
    assert started.wait(1)
    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 51.1079, 17.0385
        subject.location_changed()
    release.set()
    worker.join(2)

    assert subject.state() == {"date": "", "count": 0, "error": None}
    assert subject.match(int(time.time() * 1000)) is None


def test_rails_backfill_obeys_location_change_timestamp(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    today_start = int(dt.datetime.now(rails.ZONE).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    fence = today_start + 1_000
    events = TimetableStore([{"at": today_start + 500}, {"at": today_start + 1_500}])
    cfg.location_changed_at = fence
    subject = rails.Rails(cfg, events)
    assert subject._location_fence == fence
    subject.feed.write_bytes(b"fixture")
    monkeypatch.setattr(rails, "passes", lambda *args: [{"passSec": 0, "agency": "A", "number": "1",
                                                           "name": "train", "from": "x", "to": "y",
                                                           "between": "x – y", "distKm": 1.0}])
    subject.location_changed()
    subject._ensure_today()

    assert events.filled[0][1] is None
    assert events.filled[1][1] is not None
    assert subject.match(today_start + 500) is None


def test_rails_location_changed_wakes_polling(tmp_path):
    subject = rails.Rails(make_config(tmp_path), TimetableStore())
    assert not subject._wake.is_set()
    subject.location_changed()
    assert subject._wake.is_set()


def test_rails_current_error_is_visible_and_stale_error_is_hidden(tmp_path):
    cfg = make_config(tmp_path)
    subject = rails.Rails(cfg, TimetableStore())
    with subject.lock:
        subject._attempt = ((cfg.lat, cfg.lon), subject._generation)
    subject._mark_error(RuntimeError("current failure"))
    assert subject.state()["error"] == "current failure"

    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 51.1079, 17.0385
        subject.location_changed()
    with subject.lock:
        subject._attempt = ((54.3521, 18.6461), subject._generation - 1)
    subject._mark_error(RuntimeError("stale failure"))
    assert subject.state()["error"] is None


def test_weather_refreshes_when_exact_pair_changes_inside_ttl(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    subject = weather.Weather(cfg)
    urls = []

    def get_json(url):
        urls.append(url)
        return {"hourly": {"weather_code": [0]}}

    monkeypatch.setattr(weather.http, "get_json", get_json)
    assert subject.thunder() is False
    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 54.3522, 18.6462
    assert subject.thunder() is False

    assert len(urls) == 2
    assert "54.3521" in urls[0] and "54.3522" in urls[1]
    assert subject.origin == (54.3522, 18.6462)


def test_weather_discards_old_response_after_coordinate_change(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    subject = weather.Weather(cfg)
    started = threading.Event()
    release = threading.Event()

    def get_json(url):
        started.set()
        release.wait(2)
        return {"hourly": {"weather_code": [95]}}

    monkeypatch.setattr(weather.http, "get_json", get_json)
    result = []
    worker = threading.Thread(target=lambda: result.append(subject.thunder()))
    worker.start()
    assert started.wait(1)
    with config.SETTINGS_LOCK:
        cfg.lat, cfg.lon = 51.1079, 17.0385
    release.set()
    worker.join(2)

    assert result == [None]
    assert subject.origin is None
    assert subject.codes is None
    assert subject.checked == 0

    monkeypatch.setattr(weather.http, "get_json", lambda url: {"hourly": {"weather_code": [0]}})
    assert subject.thunder() is False
    assert subject.origin == (51.1079, 17.0385)
