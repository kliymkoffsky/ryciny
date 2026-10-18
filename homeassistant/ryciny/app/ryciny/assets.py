"""Models and shared lists: from a local checkout (RYCINY_ASSETS) or downloaded once from the repo at this version's tag."""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

from . import __version__

log = logging.getLogger(__name__)

RAW = "https://raw.githubusercontent.com/qunabu/ryciny/v{version}/{path}"
MODELS = "android/app/src/main/assets/models"
ASSETS = "android/app/src/main/assets"

FILES = {
    "birdnet.tflite": f"{MODELS}/birdnet.tflite",
    "birdnet_meta.tflite": f"{MODELS}/birdnet_meta.tflite",
    "birdnet_labels_pl.txt": f"{MODELS}/birdnet_labels_pl.txt",
    "yamnet.tflite": f"{MODELS}/yamnet.tflite",
    "yamnet_class_map.csv": f"{MODELS}/yamnet_class_map.csv",
    "birdnet_aliases.json": f"{ASSETS}/birdnet_aliases.json",
    "bird_sizes.csv": f"{ASSETS}/bird_sizes.csv",
    "garamond.ttf": "android/app/src/main/res/font/garamond.ttf",
    "garamond_italic.ttf": "android/app/src/main/res/font/garamond_italic.ttf",
    "style.json": "shared/style.json",
    "sounds.json": "shared/sounds.json",
    "dog_breeds.json": "shared/dog_breeds.json",
    "aircraft_types.json": "shared/aircraft_types.json",
}


STABLE = (".tflite", ".ttf", ".csv", ".txt")


class Assets:
    def __init__(self, data: Path, checkout: Path | None) -> None:
        self.dir = data / "assets" / __version__
        self.checkout = checkout

    def path(self, name: str) -> Path:
        if self.checkout is not None:
            return self.checkout / FILES[name]
        target = self.dir / name
        if not target.exists() and name.endswith(STABLE):
            # Models and fonts do not change between versions: move them over instead of 80 MB of downloads.
            old = sorted(p for p in self.dir.parent.glob(f"*/{name}") if p.parent != self.dir)
            if old:
                self.dir.mkdir(parents=True, exist_ok=True)
                old[-1].replace(target)
        if not target.exists():
            self.dir.mkdir(parents=True, exist_ok=True)
            url = RAW.format(version=__version__, path=FILES[name])
            log.info("downloading %s", url)
            tmp = target.with_suffix(target.suffix + ".tmp")
            urllib.request.urlretrieve(url, tmp)
            tmp.rename(target)
        return target

    def text(self, name: str) -> str:
        return self.path(name).read_text(encoding="utf-8")
