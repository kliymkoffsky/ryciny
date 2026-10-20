# Pack 6 attribution

Pack 6 contains ten generated `SCENE` atlases and prepared runtime bundles:

- [`tools.png`](tools.png): `SCENE / tools`
- [`chainsaw.png`](chainsaw.png): `SCENE / chainsaw`
- [`helicopter.png`](helicopter.png): `SCENE / helicopter`
- [`ambulance.png`](ambulance.png): `SCENE / ambulance`
- [`police.png`](police.png): `SCENE / police`
- [`fire.png`](fire.png): `SCENE / fire`
- [`caralarm.png`](caralarm.png): `SCENE / caralarm`
- [`rooster.png`](rooster.png): `SCENE / rooster`
- [`frog.png`](frog.png): `SCENE / frog`
- [`bee.png`](bee.png): `SCENE / bee`

The OpenAI built-in image generation tool produced one atlas for each subject.
The tool did not expose a backend model identifier, so each catalog entry uses
`provider: openai-built-in-imagegen` and `backend_model: null`. The runtime
`original.png` for each bundle is derived from its first registered atlas pose;
the pack does not claim a separate still-generation request.

The catalog keeps one canonical prompt per asset, the exact `SCENE` binding,
source derivation, and source and atlas `SHA-256` hashes. Prompt, description,
and provenance receipts remain in the external `stop-motion/sixth-pack/<key>/`
evidence packet.

Pack 6 uses generated project artwork. It does not copy a historical image or
carry a historical-reference attribution. Repository code and other assets
retain their existing terms.
