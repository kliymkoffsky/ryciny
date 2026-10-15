"""Same checks as the app's JVM tests, on the add-on's Python ports. Run: .venv/bin/python -m pytest tests"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from ryciny import dsp, rails, sky  # noqa: E402
from ryciny.store import Store  # noqa: E402

GDN = {"iata": "GDN", "city": "Gdańsk", "lat": 54.3776, "lon": 18.4662}
WAW = {"iata": "WAW", "city": "Warsaw", "lat": 52.1657, "lon": 20.9671}
AUH = {"iata": "AUH", "city": "Abu Dhabi", "lat": 24.4330, "lon": 54.6511}
BUD = {"iata": "BUD", "city": "Budapest", "lat": 47.4369, "lon": 19.2556}
BER = {"iata": "BER", "city": "Berlin", "lat": 52.3667, "lon": 13.5033}
RIX = {"iata": "RIX", "city": "Riga", "lat": 56.9236, "lon": 23.9711}
OVER = (54.36, 18.57)


def test_routes_like_the_app():
    assert not sky.on_route(*OVER, AUH, BUD)
    assert sky.on_route(*OVER, GDN, WAW)
    assert sky.on_route(*OVER, BER, RIX)
    assert not sky.on_route(*OVER, BUD, WAW)


@pytest.mark.skipif(not os.environ.get("GTFS_ZIP"), reason="GTFS_ZIP=/path/to/polish_trains.zip")
def test_trains_pass_gdansk_bretowo():
    found = rails.passes(Path(os.environ["GTFS_ZIP"]), os.environ.get("GTFS_DATE", "20261009"), 54.3653, 18.5736)
    assert len(found) > 20
    assert all(p["distKm"] < rails.MAX_KM for p in found)
    assert any("Brętowo" in p["between"] for p in found)


def test_journal_merges_like_store_kt():
    s = Store(Path(tempfile.mkdtemp()))
    s.add_bird("Turdus merula", "kos", 0.8, 1_000)
    s.add_bird("Turdus merula", "kos", 0.9, 30_000)
    s.add_bird("Turdus merula", "kos", 0.7, 200_000)  # more than a minute later: a new stretch
    assert [(b["count"], b["conf"]) for b in s.j["birds"]] == [(2, 0.9), (1, 0.7)]
    s.add_sound("train", 0, 0.5, "PolRegio 1", "A → B", "PolRegio")
    s.add_sound("train", 60_000, 0.5, "PolRegio 2", "B → A", "PolRegio")  # another train, not the same event
    assert len(s.j["sounds"]) == 2
    dog = s.new_dog("Burek", "Beagle", "a Beagle", "abcd1234")
    s.add_bark({"id": "b1", "at": 0, "lastAt": 0, "count": 1, "score": 0.9, "pitchHz": 500, "size": "średni",
                "embedding": [0.1, 0.2], "dogId": None, "similarity": 0.0, "clip": None})
    assert s.tag_bark("b1", dog) and s.j["dogs"][0]["samples"] == [[0.1, 0.2]]
    app = s.snapshot()
    assert app["barks"][0]["embedding"] == [] and app["dogs"][0]["samples"] == [[]]


def test_pitch_and_size():
    t = __import__("numpy").arange(16_000) / 16_000
    low = (0.5 * __import__("numpy").sin(2 * 3.14159 * 300 * t)).astype("float32")
    assert 280 < dsp.bark_pitch(low) < 320
    assert dsp.size_of(300) == "duży" and dsp.size_of(500) == "średni" and dsp.size_of(900) == "mały"


def test_public_state_leaves_out_private_things():
    from ryciny.publish import public_state
    from ryciny.store import now_ms
    t = now_ms()
    j = {"birds": [{"name": "sroka", "sci": "Pica pica", "conf": 0.91, "count": 2, "lastAt": t}],
         "planes": [{"title": "Boeing 737-800", "airline": "LOT", "callsign": "LOT1", "route": "WAW → GDN", "at": t, "lastAt": t,
                     "heard": True, "minDistKm": 0.7, "minAltM": 300, "typeCode": "B738", "airlineIcao": "LOT"},
                    {"title": "A320", "airline": "", "callsign": "", "route": "", "at": t, "lastAt": t, "heard": False}],
         "sounds": [{"key": "talking", "at": t, "lastAt": t, "count": 3, "title": "", "subtitle": "", "variant": ""},
                    {"key": "cricket", "at": t, "lastAt": t, "count": 1, "title": "", "subtitle": "", "variant": ""}],
         "barks": [{"id": "x"}], "dogs": [{"id": "d"}]}
    sounds = {"talking": {"past": "Rozmowa"}, "cricket": {"past": "Grały świerszcze"}}
    s = public_state(j, sounds, lambda k: True)
    assert [p["art"] for p in s["planes"]] == ["B738-LOT"]
    assert [e["key"] for e in s["sounds"]] == ["cricket"]
    text = str(s)
    assert "minDistKm" not in text and "barks" not in s and "dogs" not in s and "lat" not in s
