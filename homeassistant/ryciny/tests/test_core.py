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


def test_clips_kept_for_the_best_detection_and_pruned_after_14_days(tmp_path):
    from ryciny import store as st
    s = st.Store(tmp_path)
    t = st.now_ms()
    s.add_bird("Pica pica", "sroka", 0.7, t, clip=lambda: b"first")
    first = s.j["birds"][-1]["clip"]
    s.add_bird("Pica pica", "sroka", 0.6, t + 1000, clip=lambda: b"worse")
    assert s.j["birds"][-1]["clip"] == first
    s.add_bird("Pica pica", "sroka", 0.9, t + 2000, clip=lambda: b"better")
    best = s.j["birds"][-1]["clip"]
    assert best != first and not (s.clips / first).exists() and (s.clips / best).read_bytes() == b"better"
    s.add_sound("talking", t, 0.9)  # no recording of people
    assert s.j["sounds"][-1].get("clip") is None
    s.add_sound("train", t, 0.5, clip=lambda: b"train")
    assert (s.clips / s.j["sounds"][-1]["clip"]).exists()
    s._prune_clips(t + st.CLIP_KEEP_MS + 5000, force=True)
    assert not any(s.clips.iterdir()) and s.j["birds"][-1]["clip"] is None
    assert sum(s.history[st.local(t).strftime("%Y-%m-%d")]["Pica pica"]["h"]) == 3


def test_chance_of_hearing_a_bird():
    from ryciny import stats
    from ryciny.store import local, now_ms
    t = now_ms()
    days = [local(t - i * 86_400_000).strftime("%Y-%m-%d") for i in range(1, 5)]
    h = [0] * 24
    h[local(t).hour] = 3
    history = {days[0]: {"Pica pica": {"n": "sroka", "h": h}}, days[1]: {"Pica pica": {"n": "sroka", "h": [1] + [0] * 23}},
               days[2]: {"Parus major": {"n": "bogatka", "h": [0] * 23 + [1]}}, days[3]: {}}
    j = {"planes": [], "sounds": [], "birds": [], "barks": [], "dogs": []}
    s = stats.compute(j, history, {}, lambda k: True)
    assert s["daysObserved"] == 4
    day = {c["sci"]: c["day"] for c in s["birds"]["chanceDay"]}
    assert day == {"Pica pica": 0.5, "Parus major": 0.25}
    assert s["birds"]["chanceNow"][0]["sci"] == "Pica pica" and s["birds"]["chanceNow"][0]["now"] == 0.25


def test_public_audio_for_every_entry_without_people():
    from ryciny.publish import public_state
    from ryciny.store import now_ms
    t = now_ms()
    bird = lambda conf, at, clip, ok: {"name": "sroka", "sci": "Pica pica", "conf": conf, "count": 1, "at": at, "lastAt": at,  # noqa: E731
                                       "clip": clip, "clipPublic": ok}
    j = {"birds": [bird(0.8, t - 3000, "a.wav", True), bird(0.95, t - 2000, "b.wav", False), bird(0.9, t - 1000, "c.wav", True)],
         "planes": [], "sounds": [], "barks": [], "dogs": []}
    s = public_state(j, {}, lambda k: True)
    assert [b.get("audio") for b in s["birds"]] == ["a.wav", None, "c.wav"]
    assert "clip" not in str(s).replace("'audio'", "")


def test_best_recording_of_a_species_is_kept_for_good(tmp_path):
    from ryciny import store as st
    s = st.Store(tmp_path)
    t = st.now_ms()
    s.add_bird("Anser albifrons", "gęś białoczelna", 0.97, t, clip=lambda: b"best", public=True)
    s.add_bird("Anser albifrons", "gęś białoczelna", 0.80, t + 120_000, clip=lambda: b"worse")
    b = s.best["Anser albifrons"]
    assert b["conf"] == 0.97 and (s.best_dir / b["clip"]).read_bytes() == b"best" and b["public"]
    s._prune_clips(t + st.CLIP_KEEP_MS + 200_000, force=True)
    assert not any(s.clips.iterdir()) and (s.best_dir / b["clip"]).exists()
    s.add_bird("Anser albifrons", "gęś białoczelna", 0.99, t + 300_000, clip=lambda: b"better")
    nb = s.best["Anser albifrons"]
    assert nb["conf"] == 0.99 and not (s.best_dir / b["clip"]).exists() and len(list(s.best_dir.iterdir())) == 1
    s.flush()
    assert st.Store(tmp_path).best["Anser albifrons"]["clip"] == nb["clip"]


def test_tv_plate_renders_4k_jpeg():
    from pathlib import Path
    from PIL import Image
    import io
    from ryciny import tvplate, stats
    root = Path(__file__).resolve().parents[3] / "android/app/src/main/res/font"
    fonts = (str(root / "garamond.ttf"), str(root / "garamond_italic.ttf"))
    st = stats.compute({"planes": [], "sounds": [], "birds": [], "barks": [], "dogs": []}, {}, {}, lambda k: True)
    jpeg = tvplate.render({"kind": "BIRD", "key": "Pica pica", "title": "Sroka", "lines": ["Pica pica", "ostatnio 12:00"]},
                          Image.new("RGBA", (300, 200), (0, 0, 0, 255)), "Sroka – ptak z rodziny krukowatych.", st, fonts)
    assert Image.open(io.BytesIO(jpeg)).size == (3840, 2160)


def test_paid_engravings_stop_at_the_daily_limit(tmp_path):
    from types import SimpleNamespace
    from ryciny.art import Art
    art = Art.__new__(Art)
    art.cfg = SimpleNamespace(data=tmp_path, art_daily_limit=2)
    assert [art._spend() for _ in range(3)] == [True, True, False]
