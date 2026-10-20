"""BirdNET 6K v2.4 with its range filter, and YAMNet: the same models and preprocessing as the app."""

from __future__ import annotations

import csv
import threading
import datetime as dt
from dataclasses import dataclass

import numpy as np

try:
    from ai_edge_litert.interpreter import Interpreter
except ImportError:  # pragma: no cover - fallback for older installs
    from tflite_runtime.interpreter import Interpreter  # type: ignore

from .assets import Assets

NON_BIRD_GENERA = set("""
dog engine environmental fireworks gun human noise power siren
acris anaxyrus dryophytes eleutherodactylus gastrophryne hyliola incilius
lithobates pseudacris scaphiopus spea
allonemobius amblycorypha anaxipha apis atlanticus conocephalus cyrtoxipha
eunemobius gryllus hapithus microcentrum miogryllus neoconocephalus neonemobius
oecanthus orchelimum orocharis phyllopalpus pterophylla scudderia
alouatta canis odocoileus sciurus tamias tamiasciurus
""".split())


@dataclass(frozen=True)
class Label:
    sci: str
    name: str
    bird: bool


class BirdNet:
    SAMPLES = 144_000
    RANGE_THRESHOLD = 0.03

    def __init__(self, assets: Assets) -> None:
        self.model = Interpreter(str(assets.path("birdnet.tflite")), num_threads=2)
        self.model.allocate_tensors()
        self.meta = Interpreter(str(assets.path("birdnet_meta.tflite")))
        self.meta.allocate_tensors()
        self.labels: list[Label] = []
        for line in assets.text("birdnet_labels_pl.txt").splitlines():
            if not line.strip():
                continue
            sci, _, name = line.partition("_")
            self.labels.append(Label(sci, name or sci, sci.split(" ")[0].lower() not in NON_BIRD_GENERA))
        self._mask_key = None
        self._mask = None

    def predict(self, window: np.ndarray) -> np.ndarray:
        inp = self.model.get_input_details()[0]
        self.model.set_tensor(inp["index"], window.reshape(1, -1).astype(np.float32))
        self.model.invoke()
        out = self.model.get_tensor(self.model.get_output_details()[0]["index"])[0]
        return 1.0 / (1.0 + np.exp(-out))

    def range_mask(self, lat: float, lon: float, date: dt.date | None = None) -> np.ndarray:
        date = date or dt.date.today()
        week = (date.month - 1) * 4 + min(4, (date.day - 1) // 7 + 1)
        # Keep the full coordinate pair in the key: nearby locations can share a rounded cell.
        key = (lat, lon, week)
        if key != self._mask_key:
            inp = self.meta.get_input_details()[0]
            self.meta.set_tensor(inp["index"], np.array([[lat, lon, week]], dtype=np.float32))
            self.meta.invoke()
            self._mask = self.meta.get_tensor(self.meta.get_output_details()[0]["index"])[0] >= self.RANGE_THRESHOLD
            self._mask_key = key
        return self._mask


class Yamnet:
    SAMPLES = 15_600
    DOG = range(69, 76)
    AIRCRAFT = range(329, 335)

    def __init__(self, assets: Assets) -> None:
        self.model = Interpreter(str(assets.path("yamnet.tflite")))
        self.lock = threading.Lock()
        inp = self.model.get_input_details()[0]
        self.model.resize_tensor_input(inp["index"], [self.SAMPLES])
        self.model.allocate_tensors()
        outs = self.model.get_output_details()
        self._scores = next(o["index"] for o in outs if o["shape"][-1] == 521)
        self._embedding = next(o["index"] for o in outs if o["shape"][-1] == 1024)
        with assets.path("yamnet_class_map.csv").open(encoding="utf-8") as f:
            self.classes = [row["display_name"] for row in csv.DictReader(f)]

    def run(self, chunk: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        # One interpreter, used by live analysis and by the panel's recheck: one call at a time.
        with self.lock:
            self.model.set_tensor(self.model.get_input_details()[0]["index"], chunk.astype(np.float32))
            self.model.invoke()
            return self.model.get_tensor(self._scores)[0].copy(), self.model.get_tensor(self._embedding)[0].copy()
