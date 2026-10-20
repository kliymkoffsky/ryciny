from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ryciny import config, publish  # noqa: E402
from ryciny.publish import Publisher, public_state  # noqa: E402


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    monkeypatch.setenv("RYCINY_DATA", str(tmp_path))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    return tmp_path


def _config(tmp_path, *, title=config.DEFAULT_STATION_TITLE):
    return config.Config(data=tmp_path, assets=None, station_title=title)


def _journal_app(tmp_path, title=config.DEFAULT_STATION_TITLE):
    cfg = _config(tmp_path, title=title)
    journal = {"birds": [], "planes": [], "sounds": []}
    store = SimpleNamespace(
        version=1,
        snapshot=lambda: journal,
        history_snapshot=lambda: {},
        best_snapshot=lambda: {},
    )
    app = SimpleNamespace(
        cfg=cfg,
        store=store,
        sounds={},
        sound_on=lambda _key: True,
    )
    return app


def _run_rounds(monkeypatch, publisher, before_sleep=None, rounds=3):
    sleeps = 0

    def sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if before_sleep is not None:
            before_sleep(sleeps)
        if sleeps >= rounds:
            raise StopIteration

    monkeypatch.setattr(publish.time, "sleep", sleep)
    with pytest.raises(StopIteration):
        publisher.run()


def test_default_title_is_canonical_and_public_state_keeps_it_a_string(tmp_path):
    cfg = _config(tmp_path)
    state = public_state({"birds": [], "planes": [], "sounds": []}, {}, lambda _key: True)

    assert cfg.station_title == "Dźwięki Dolnego Migowa"
    assert state["title"] == "Dźwięki Dolnego Migowa"
    assert isinstance(state["title"], str)
    assert "lat" not in state and "lon" not in state


def test_title_is_trimmed_persisted_and_reloaded(local_data):
    cfg = config.load()

    result = config.update(cfg, {"station_title": "  Dom <script>  "})
    reloaded = config.load()

    assert result["station_title"] == "Dom <script>"
    assert cfg.station_title == reloaded.station_title == "Dom <script>"
    assert json.loads((local_data / "settings.json").read_text())["station_title"] == "Dom <script>"


@pytest.mark.parametrize(
    "value",
    [None, True, 12, "", "   ", "x" * 121, "line\nbreak", "line\rbreak", "line\tbreak", "bad\x00title", "bad\u2028title"],
)
def test_invalid_runtime_title_is_rejected_before_mutation_or_save(tmp_path, value):
    cfg = _config(tmp_path)
    before = cfg.station_title

    with pytest.raises(ValueError, match="station_title"):
        config.update(cfg, {"station_title": value})

    assert cfg.station_title == before
    assert not (tmp_path / "settings.json").exists()


def test_load_rejects_invalid_final_title(local_data):
    (local_data / "options.json").write_text(json.dumps({"station_title": "bad\nname"}))

    with pytest.raises(ValueError, match="station_title"):
        config.load()


@pytest.mark.parametrize("saved", [{"station_title": "bad\nname"}, {"station_title": 12}, {"station_title": ""}])
def test_invalid_saved_title_does_not_mutate_config(tmp_path, saved):
    cfg = _config(tmp_path, title="Before")
    (tmp_path / "settings.json").write_text(json.dumps(saved))

    with pytest.raises(ValueError, match="station_title"):
        config.apply_saved(cfg)

    assert cfg.station_title == "Before"


def test_failed_title_write_leaves_config_and_disk_unchanged(tmp_path, monkeypatch):
    cfg = _config(tmp_path, title="Before")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"station_title": "Before"}) + "\n")
    before_disk = settings.read_text()
    monkeypatch.setattr(config.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk failure")))

    with pytest.raises(OSError, match="disk failure"):
        config.update(cfg, {"station_title": "After"})

    assert cfg.station_title == "Before"
    assert settings.read_text() == before_disk


def test_public_state_validates_and_trims_title_without_exposing_location():
    journal = {"birds": [], "planes": [], "sounds": []}

    state = public_state(journal, {}, lambda _key: True, "  Łąka <&>  ")
    encoded = json.dumps(state, ensure_ascii=False)

    assert state["title"] == "Łąka <&>"
    assert isinstance(state["title"], str)
    assert "lat" not in state and "lon" not in state
    assert "Łąka <&>" in encoded


def _quiet_publisher(tmp_path, title="One"):
    app = _journal_app(tmp_path, title)
    publisher = Publisher(app.cfg, app)
    publisher._art = lambda _state: None
    publisher._clips = lambda _state: None
    publisher._best = lambda _state: None
    publisher._animations = lambda _state: None
    return app, publisher


def test_publisher_sends_two_title_only_changes_without_journal_changes(tmp_path, monkeypatch):
    app, publisher = _quiet_publisher(tmp_path)
    app.cfg.public_url = "https://example.test"
    app.cfg.public_token = "token"
    uploads = []

    def put(path, body, _ctype):
        uploads.append((path, body))
        return b"[]" if path == "/ingest/has" else b""

    publisher._put = put

    def change_title(round_number):
        if round_number == 2:
            with config.SETTINGS_LOCK:
                app.cfg.station_title = "Two"

    monkeypatch.setattr(publish.stats, "compute", lambda *args, **kwargs: {"birds": {"best": {}}})
    _run_rounds(monkeypatch, publisher, before_sleep=change_title)

    states = [json.loads(body) for path, body in uploads if path == "/ingest/state"]
    assert [state["title"] for state in states] == ["One", "Two"]
    assert app.store.version == 1


def test_publisher_retries_failed_title_publication(tmp_path, monkeypatch):
    app, publisher = _quiet_publisher(tmp_path, "Retry")
    app.cfg.public_url = "https://example.test"
    app.cfg.public_token = "token"
    state_attempts = []

    def put(path, body, _ctype):
        if path == "/ingest/has":
            return b"[]"
        if path == "/ingest/state":
            state_attempts.append(body)
            if len(state_attempts) == 1:
                raise OSError("send failed")
        return b""

    publisher._put = put
    monkeypatch.setattr(publish.stats, "compute", lambda *args, **kwargs: {"birds": {"best": {}}})
    _run_rounds(monkeypatch, publisher)

    assert len(state_attempts) == 2
    assert all(json.loads(body)["title"] == "Retry" for body in state_attempts)
    assert publisher.error is None


def test_publisher_captures_title_before_send_and_publishes_mid_send_change_next_cycle(tmp_path, monkeypatch):
    app, publisher = _quiet_publisher(tmp_path, "Before")
    app.cfg.public_url = "https://example.test"
    app.cfg.public_token = "token"
    states = []

    def put(path, body, _ctype):
        if path == "/ingest/has":
            return b"[]"
        if path == "/ingest/state":
            states.append(json.loads(body))
            if len(states) == 1:
                with config.SETTINGS_LOCK:
                    app.cfg.station_title = "After"
        return b""

    publisher._put = put
    monkeypatch.setattr(publish.stats, "compute", lambda *args, **kwargs: {"birds": {"best": {}}})
    _run_rounds(monkeypatch, publisher)

    assert [state["title"] for state in states] == ["Before", "After"]
