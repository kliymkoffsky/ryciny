from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ryciny import config, runtime_animation  # noqa: E402
from ryciny.config import load  # noqa: E402


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    monkeypatch.setenv("RYCINY_DATA", str(tmp_path))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    for name in ("RYCINY_ANIMATION_PLAYBACK", "RYCINY_ANIMATION_GENERATE", "RYCINY_ANIMATION_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_animation_defaults_and_environment_override(local_config, monkeypatch):
    cfg = load()
    assert (cfg.animation_playback, cfg.animation_generate) == (False, False)
    assert cfg.animation_model == "gpt-image-2.5-sunburst"

    (local_config / "options.json").write_text(json.dumps({
        "animation_playback": True,
        "animation_generate": True,
        "animation_model": "custom-image-model",
    }))
    monkeypatch.setenv("RYCINY_ANIMATION_PLAYBACK", "false")
    monkeypatch.setenv("RYCINY_ANIMATION_MODEL", "gpt-image-2.5-flare")
    cfg = load()
    assert cfg.animation_playback is False
    assert cfg.animation_generate is True
    assert cfg.animation_model == "gpt-image-2.5-flare"


def test_animation_settings_persist_atomically_and_reject_invalid_values(local_config, monkeypatch):
    cfg = load()
    config.update(cfg, {
        "animation_playback": True,
        "animation_generate": True,
        "animation_model": "custom-runtime-model",
    })
    assert json.loads((local_config / "settings.json").read_text())["animation_generate"] is True
    assert cfg.animation_model == load().animation_model == "custom-runtime-model"

    with pytest.raises(ValueError, match="animation_generate must be a boolean"):
        config.update(cfg, {"animation_generate": "true"})
    assert cfg.animation_generate is True
    with pytest.raises(ValueError, match="animation_model"):
        config.update(cfg, {"animation_generate": False, "animation_model": "bad model"})
    assert cfg.animation_generate is True
    monkeypatch.setattr(config.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError):
        config.update(cfg, {"animation_generate": False})
    assert cfg.animation_generate is True
    assert json.loads((local_config / "settings.json").read_text())["animation_generate"] is True


def test_settings_epoch_cancels_stale_work_and_rescans_when_enabled():
    app = SimpleNamespace(_prefetch_epoch=0, animation_revision=0)
    off = {"animation_playback": False, "animation_generate": False, "animation_model": "sunburst"}
    enabled = {**off, "animation_generate": True}
    runtime_animation.settings_changed(app, off, enabled)
    assert app._prefetch_epoch == 1
    changed = {**enabled, "animation_model": "custom"}
    runtime_animation.settings_changed(app, enabled, changed)
    assert app._prefetch_epoch == 2
    disabled = {**changed, "animation_generate": False}
    runtime_animation.settings_changed(app, changed, disabled)
    assert app._prefetch_epoch == 3
    runtime_animation.settings_changed(app, disabled, {**disabled, "animation_playback": True})
    assert app.animation_revision == 1 and app._prefetch_epoch == 3
