#!/usr/bin/env python3
"""Plan, generate, or prepare one six-frame reference animation pack."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPOSITORY_ROOT / "homeassistant" / "ryciny" / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ryciny.animation_outlines import OutlineStore  # noqa: E402
from ryciny.sticker_renderer import StickerError  # noqa: E402
from ryciny.animation import (  # noqa: E402
    AnimationError,
    DEFAULT_MODEL,
    KINDS,
    generate_atlas,
    prepare_atlas,
    request_plan,
)


def _parser() -> argparse.ArgumentParser:
    """Build the small single-pack command-line interface."""

    parser = argparse.ArgumentParser(description="Plan or prepare one Ryciny animation pack.")
    parser.add_argument("--source", type=Path, required=True, help="Reference PNG or WebP image.")
    parser.add_argument("--kind", choices=sorted(KINDS), required=True, help="Exact runtime kind.")
    parser.add_argument("--key", required=True, help="Exact runtime key.")
    parser.add_argument("--subject", required=True, help="Subject text for the image prompt.")
    parser.add_argument("--motion", default="", help="Optional activity instruction.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI image model.")
    parser.add_argument("--output", type=Path, help="New pack destination for --sheet or --generate.")
    parser.add_argument("--outline-cache", type=Path, default=REPOSITORY_ROOT / "output" / "animation-outlines",
                        help="Persistent derived pack cache; raw --output remains unchanged.")
    parser.add_argument("--sheet", type=Path, help="Existing six-cell atlas to prepare without a provider call.")
    parser.add_argument("--generate", action="store_true", help="Send one request using OPENAI_API_KEY.")
    return parser


def _print(value: object) -> None:
    """Write one bounded JSON result for shell workflows and evidence capture."""

    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    """Run a no-network plan by default, or explicitly prepare one new pack."""

    args = _parser().parse_args(argv)
    if args.sheet is not None and args.generate:
        raise SystemExit("--sheet and --generate are mutually exclusive")
    try:
        if args.sheet is None and not args.generate:
            _print(
                request_plan(
                    args.source,
                    subject=args.subject,
                    motion=args.motion,
                    model=args.model,
                )
            )
            return 0
        if args.output is None:
            raise SystemExit("--output is required with --sheet or --generate")
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"output already exists: {args.output}")
        if args.sheet is not None:
            pack = prepare_atlas(
                args.source,
                args.sheet,
                args.output,
                kind=args.kind,
                key=args.key,
                provider="local-atlas-import",
            )
        else:
            with tempfile.TemporaryDirectory(prefix="ryciny-atlas-") as temporary:
                sheet = Path(temporary) / "sheet.png"
                sheet.write_bytes(
                    generate_atlas(
                        args.source,
                        subject=args.subject,
                        motion=args.motion,
                        model=args.model,
                        api_key=os.environ.get("OPENAI_API_KEY"),
                    )
                )
                pack = prepare_atlas(
                    args.source,
                    sheet,
                    args.output,
                    kind=args.kind,
                    key=args.key,
                    model=args.model,
                )
        raw = pack
        pack = OutlineStore(args.outline_cache).ensure(raw)
        _print({"path": str(pack.path), "id": pack.id, "kind": pack.kind, "key": pack.key,
                "raw_path": str(raw.path), "raw_id": raw.id})
        return 0
    except (AnimationError, StickerError, FileExistsError, OSError) as error:
        print(f"generate_animation: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
