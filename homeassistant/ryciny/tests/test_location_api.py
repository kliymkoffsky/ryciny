from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from ryciny import config
from ryciny.api import App


@pytest.fixture
def settings_server(tmp_path):
    app = App.__new__(App)
    app.cfg = config.Config(data=tmp_path, assets=None, port=0, image_provider='none')
    changes = []
    app.sky = SimpleNamespace(location_changed=lambda: changes.append(('sky', config.location(app.cfg))))
    app.rails = SimpleNamespace(location_changed=lambda: changes.append(('rails', config.location(app.cfg))))
    app.animation_revision = app._prefetch_epoch = 0
    app.server = None
    thread = threading.Thread(target=app.serve, args=('127.0.0.1',), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while app.server is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert app.server is not None
    try:
        yield app, changes, f'http://127.0.0.1:{app.server.server_port}'
    finally:
        app.server.shutdown()
        app.server.server_close()
        thread.join(timeout=5)


def put(base, values):
    request = urllib.request.Request(base + '/api/settings', data=json.dumps(values).encode(), method='PUT',
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def test_settings_http_roundtrip_and_refresh(settings_server):
    app, changes, base = settings_server
    result = put(base, {'lat': 52.1, 'lon': 21.2})
    assert (result['lat'], result['lon']) == (52.1, 21.2)
    assert changes == [('sky', (52.1, 21.2)), ('rails', (52.1, 21.2))]
    with urllib.request.urlopen(base + '/api/settings') as response:
        saved = json.load(response)
    assert (saved['lat'], saved['lon']) == (52.1, 21.2)
    reloaded = config.Config(data=app.cfg.data, assets=None)
    config.apply_saved(reloaded)
    assert config.location(reloaded) == (52.1, 21.2)
    put(base, {'lat': 52.1, 'lon': 21.2})
    put(base, {'bird_threshold': .8})
    assert len(changes) == 2
    with urllib.request.urlopen(base + '/location.js') as response:
        assert 'javascript' in response.headers['Content-Type']
        assert b'parseCoordinates' in response.read()


def test_invalid_http_pair_does_not_mutate_or_refresh(settings_server):
    app, changes, base = settings_server
    before = config.location(app.cfg)
    for values in ({'lat': 51}, {'lat': 91, 'lon': 0}, {'lat': False, 'lon': 1}, {'lat': float('nan'), 'lon': 1}):
        with pytest.raises(urllib.error.HTTPError) as caught:
            put(base, values)
        assert caught.value.code == 400
        assert config.location(app.cfg) == before
    assert changes == []
    assert not (app.cfg.data / 'settings.json').exists()


def test_failed_http_save_does_not_refresh(settings_server, monkeypatch):
    app, changes, base = settings_server
    before = config.location(app.cfg)
    monkeypatch.setattr(config.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(urllib.error.HTTPError) as caught:
        put(base, {'lat': 52.1, 'lon': 21.2})
    assert caught.value.code == 500
    assert config.location(app.cfg) == before
    assert changes == []
