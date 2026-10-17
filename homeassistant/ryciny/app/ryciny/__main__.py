"""Start: python -m ryciny (Home Assistant runs it in the add-on; locally with RYCINY_DATA / RYCINY_ASSETS / RYCINY_AUDIO)."""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading

from . import config
from .analyzer import Analyzer, Live
from .api import App
from .art import Art
from .assets import Assets
from .audio import Listener
from .publish import Publisher
from .rails import Rails
from .sky import Sky
from .store import Store
from .weather import Weather


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config.load()
    assets = Assets(cfg.data, cfg.assets)
    store = Store(cfg.data)

    def stop(*_):
        # Home Assistant stops add-ons with SIGTERM (updates, restarts): keep the last seconds of the journal.
        store.flush()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # Microphone first: it can be tested in the panel while the models (~80 MB on first start) download.
    live = Live()
    listener = Listener(cfg.audio_command, live, cfg=cfg)
    listener.start()
    sky = Sky(cfg, store, json.loads(assets.text("aircraft_types.json")))
    rails = Rails(cfg, store)
    art = Art(cfg, assets)
    app = App(cfg, assets, store, sky, rails, art, live, listener)
    threading.Thread(target=app.serve, daemon=True, name="api").start()
    threading.Thread(target=app.prefetch, daemon=True, name="art").start()
    threading.Thread(target=app.frame_loop, daemon=True, name="frame").start()
    threading.Thread(target=Publisher(cfg, app).run, daemon=True, name="publish").start()
    sky.start()
    rails.start()
    live.sound = "ładuję modele rozpoznawania…"
    try:
        listener.analyzer = Analyzer(cfg, assets, store, sky, rails, live, Weather(cfg))
        live.sound = ""
    except Exception as e:  # noqa: BLE001 - keep the panel and the mic test running
        logging.exception("models")
        live.error = f"nie udało się wczytać modeli: {e}"
    threading.Event().wait()


if __name__ == "__main__":
    main()
