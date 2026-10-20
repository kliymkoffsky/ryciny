# Prepared engraving animations

The browser can play reviewed stop-motion frames over the existing product plate.
The paper, captions, layout, and static-device outputs remain unchanged. Playback
and generation are separate. The browser and Docker build never call an image
model. Missing or invalid bundles use the still image.

## Original seven-atlas pack

The repository ships seven generated atlases and seven prepared bundles from the
original pack:

| atlas | exact binding |
| --- | --- |
| `pies.png` | `DOG / Kundel średni` |
| `kos.png` | `BIRD / Turdus merula` |
| `dzwon.png` | `SCENE / bells` |
| `kosiarka.png` | `SCENE / mower` |
| `cessna-208.png` | `PLANE / C208-plain` |
| `gramofon.png` | `SCENE / music` |
| `embraer-e175-lot.png` | `PLANE / E75S-LOT` |

Raw sheets, prompts, reference hashes, sheet hashes, and provider provenance are
in [`docs/animation-atlases/catalog.json`](animation-atlases/catalog.json).
`moving-images.gif` is the review montage. The canonical prompt is
`homeassistant/ryciny/app/ryciny/animation-prompt.txt`.

![Original seven prepared animations](animation-atlases/moving-images.gif)

## Pack 3: ten canonical bird atlases

The third pack adds ten prepared bundles bound to the exact BirdNET scientific
keys used by the bird journal:

| atlas | exact binding |
| --- | --- |
| `pack-3/aegithalos-caudatus.png` | `BIRD / Aegithalos caudatus` |
| `pack-3/anas-platyrhynchos.png` | `BIRD / Anas platyrhynchos` |
| `pack-3/ardea-cinerea.png` | `BIRD / Ardea cinerea` |
| `pack-3/buteo-buteo.png` | `BIRD / Buteo buteo` |
| `pack-3/columba-palumbus.png` | `BIRD / Columba palumbus` |
| `pack-3/dendrocopos-major.png` | `BIRD / Dendrocopos major` |
| `pack-3/erithacus-rubecula.png` | `BIRD / Erithacus rubecula` |
| `pack-3/hirundo-rustica.png` | `BIRD / Hirundo rustica` |
| `pack-3/pica-pica.png` | `BIRD / Pica pica` |
| `pack-3/upupa-epops.png` | `BIRD / Upupa epops` |

[Review montage for pack 3](animation-atlases/pack-3/moving-images.gif)
contains these ten new atlases. [Pack 3 attribution](animation-atlases/pack-3/ATTRIBUTION.md)
records the canonical restoration and selected historical plate for each item.
Each catalog entry retains the upstream reference URL and both the raw
reference and prepared PNG hashes.

Each runtime pack contains `original.png`, `manifest.json`, and six authored
red, green, blue, and alpha frames under `frames/000.png` through `frames/005.png`. The closing pose is
not stored twice: playback returns to frame zero after frame five. The compact
manifest records the exact kind and key, the original source digest, atlas
sheet digest, provider, optional model, and `frame_ms: 180`.

## Pack 4: ten canonical bird atlases

The fourth pack adds ten prepared bundles for BirdNET scientific keys. The
repository now contains 27 prepared bundles across the original pack and packs
3 and 4.

| atlas | exact binding |
| --- | --- |
| `pack-4/alcedo-atthis.png` | `BIRD / Alcedo atthis` |
| `pack-4/ciconia-ciconia.png` | `BIRD / Ciconia ciconia` |
| `pack-4/strix-aluco.png` | `BIRD / Strix aluco` |
| `pack-4/parus-major.png` | `BIRD / Parus major` |
| `pack-4/cyanistes-caeruleus.png` | `BIRD / Cyanistes caeruleus` |
| `pack-4/passer-domesticus.png` | `BIRD / Passer domesticus` |
| `pack-4/fringilla-coelebs.png` | `BIRD / Fringilla coelebs` |
| `pack-4/carduelis-carduelis.png` | `BIRD / Carduelis carduelis` |
| `pack-4/troglodytes-troglodytes.png` | `BIRD / Troglodytes troglodytes` |
| `pack-4/sturnus-vulgaris.png` | `BIRD / Sturnus vulgaris` |

[Review montage for pack 4](animation-atlases/pack-4/moving-images.gif) shows
the ten new atlases. The feature builds on merged [PR #4](https://github.com/qunabu/ryciny/pull/4),
[PR #3](https://github.com/qunabu/ryciny/pull/3), and
[PR #5](https://github.com/qunabu/ryciny/pull/5).

Each pack keeps the exact `BIRD` key used by BirdNET. The browser and Home
Assistant clients use the cached six-frame bundle when exact key and source
validation pass. They keep the still image when no compatible bundle exists.

## Pack 5: ten everyday scene atlases

The fifth pack adds ten prepared bundles for exact sound keys from
`shared/sounds.json`. The repository now contains 37 prepared bundles across
the original pack and packs 3, 4, and 5.

| atlas | exact binding |
| --- | --- |
| `pack-5/cat.png` | `SCENE / cat` |
| `pack-5/car.png` | `SCENE / car` |
| `pack-5/motorcycle.png` | `SCENE / motorcycle` |
| `pack-5/train.png` | `SCENE / train` |
| `pack-5/rain.png` | `SCENE / rain` |
| `pack-5/wind.png` | `SCENE / wind` |
| `pack-5/storm.png` | `SCENE / storm` |
| `pack-5/doorbell.png` | `SCENE / doorbell` |
| `pack-5/talking.png` | `SCENE / talking` |
| `pack-5/children.png` | `SCENE / children` |

[Review montage for pack 5](animation-atlases/pack-5/moving-images.gif) shows
the ten new atlases. [Pack 5 attribution](animation-atlases/pack-5/ATTRIBUTION.md)
records their generation provenance.

For each new `SCENE`, the prepared bundle includes a canonical default still.
The runtime uses that still only when no cached scene still exists. An existing
cached custom still stays in use. The runtime serves animation frames only when
the exact key and cached source match. It keeps the custom still when they do not.

## Prepare or generate

The command-line tool plans work locally by default and makes no network request:

```bash
python tools/generate_animation.py \
  --source homeassistant/ryciny/app/ryciny/prepared-animations/DOG/kundel-sredni/original.png \
  --kind DOG --key 'Kundel średni' \
  --subject 'a medium-sized mixed-breed dog' \
  --motion 'one bark, then settle' --model gpt-image-2.5-sunburst
```

The command needs `--subject`. `--motion` is optional. The default mode prints a
redacted plan and reads no API key. Add `--generate` only for an explicit keyed
image request.

Use `--sheet path/to/existing-1536x1024.png` to import an atlas for local
preparation. The default mode does not need `--output`. The command requires
`--output` with `--sheet` or `--generate`. That path names a new pack directory.

The checked-in examples came from the built-in OpenAI image tool without a user
API key. Its backend model was unavailable, so the catalog records
`backend_model: null`. The catalog prompts and hash values are the source of
truth. Preparing or playing a checked-in pack does not call a provider.

## Runtime switches and fallbacks

The Docker image includes prepared bundles by default. Runtime playback and
generation stay off until the user enables them.

**Settings matrix**

- **Playback**: `animation_playback` / `Odtwarzaj animacje`. Off by default. Cached frames need no key or rebuild.
- **Generation**: `animation_generate` / `Generuj animacje dla istniejących i nowych rycin`. Off by default. A non-empty `Klucz OpenAI` lets the worker dispatch paid requests.
- **Model**: `animation_model` / `Model generowania animacji`. Defaults to `gpt-image-2.5-sunburst`. It applies only to generation.
- **Assets**: `INCLUDE_ANIMATIONS`. Defaults to `1`. `0` or `false` omits bundles. This advanced setting needs a rebuild.

For normal activation, open the add-on panel and select `Ustawienia`. Under
`Animowana rycina`, turn on `Odtwarzaj animacje`. The setting saves immediately.
Cached playback does not need an API key and does not need a rebuild.

For generation, set `Klucz OpenAI` in the add-on configuration. Then enable
`Generuj animacje dla istniejących i nowych rycin` and select
`Model generowania animacji`. The background worker dispatches only when the
switch is on and the key is non-empty. Enabling the switch without a key does no
paid work.

Use `INCLUDE_ANIMATIONS=0` only when an advanced Docker build must omit prepared
assets. The values `true` and `false` are also accepted. This flag does not
enable playback. The startup variables
`RYCINY_ANIMATION_PLAYBACK`, `RYCINY_ANIMATION_GENERATE`, and
`RYCINY_ANIMATION_MODEL` override the corresponding settings for that process.

The Home Assistant API emits animation descriptors only when
`animation_playback` is on. The public-site exporter publishes prepared
descriptors independently. Its viewer starts paused and stores local browser
opt-in.

The Android client in Home Assistant mode follows the API descriptor gate.
Standalone Android keeps its still-image path. Generic Camera, Picture entity,
e-ink, and Samsung The Frame outputs remain static. Keep the still image when no
compatible pack exists or a pack fails validation. The exact `kind` and `key`
identify a bundle. The runtime never infers a nearby key from a picture.
