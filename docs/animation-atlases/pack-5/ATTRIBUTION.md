# Pack 5 attribution

Pack 5 contains ten generated canonical stills, six-pose atlases, prepared
runtime bundles, and a review montage. The OpenAI built-in image generation tool
produced each canonical still and its atlas. The tool did not expose a backend
model identifier, so the catalog records `backend_model: null`.

Each bundle uses its own canonical still as the atlas identity reference. The
catalog records the exact still prompt, atlas prompt, source and sheet `SHA-256`
hashes, exact `SCENE` key, and observed motion.

- [`cat.png`](cat.png): `SCENE / cat`
- [`car.png`](car.png): `SCENE / car`
- [`motorcycle.png`](motorcycle.png): `SCENE / motorcycle`
- [`train.png`](train.png): `SCENE / train`
- [`rain.png`](rain.png): `SCENE / rain`
- [`wind.png`](wind.png): `SCENE / wind`
- [`storm.png`](storm.png): `SCENE / storm`
- [`doorbell.png`](doorbell.png): `SCENE / doorbell`
- [`talking.png`](talking.png): `SCENE / talking`
- [`children.png`](children.png): `SCENE / children`

Pack 5 uses generated project artwork. It does not copy a historical image or
carry a historical-reference attribution. Repository code and other assets
retain their existing terms.
