# Ryciny (dodatek Home Assistant)

Nasłuch, rozpoznawanie i Dziennik Rycin na komputerze z Home Assistant; telefon tylko wyświetla. Opis: [DOCS.md](DOCS.md).

Lokalnie, bez Home Assistant:

```bash
python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt pytest
cd app && RYCINY_DATA=/tmp/ryciny RYCINY_ASSETS=../../.. \
  RYCINY_AUDIO="../.venv/bin/python ../tests/feed.py nagranie.wav" ../.venv/bin/python -m ryciny
# http://localhost:8099
.venv/bin/python -m pytest tests
```

Animation settings and the pack matrix are in [the animation preparation guide](../../docs/animation-preparation.md).
In the add-on panel, `Ustawienia` saves runtime changes immediately in
`/data/settings.json` and keeps them after restart. Saved settings override add-on
options, and `RYCINY_ANIMATION_*` startup variables override saved values when the
process loads. Cached playback needs no key. You can enable generation without a
key, but the worker does no paid work until you set `Klucz OpenAI`.
