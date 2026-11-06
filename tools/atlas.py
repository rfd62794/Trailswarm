"""Render the ROM's Kanto world and overlay the agents' learning on it (HEADLESS: writes PNG files only).

    uv run python tools/atlas.py render --out runs/atlas/world.png [--links]
    uv run python tools/atlas.py overlay --maps runs/maps.json --transitions "runs/explore-*/transitions.jsonl" \
        --agents runs/agents --out runs/atlas/overlay.png [--base world.png] [--layers heat,walls,...]

Outputs are rendered from ROM bytes: keep them out of git (runs/ is ignored).
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from pokeagent.atlas.agents_io import load_agents
from pokeagent.atlas.overlay import LAYERS, overlay
from pokeagent.atlas.rom_maps import all_headers, load
from pokeagent.atlas.world import build_layout
from pokeagent.atlas.world_render import render_world

Image.MAX_IMAGE_PIXELS = None


def _save(img: np.ndarray, out: str) -> None:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(out)
    print(f"wrote {out} ({img.shape[1]}x{img.shape[0]})")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="atlas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("render", "overlay"):
        p = sub.add_parser(name)
        p.add_argument("--rom", default="roms/Pokemon Red.gb")
        p.add_argument("--out", required=True)
        p.add_argument("--links", action="store_true", help="draw interior-to-door link lines")
    o = sub.choices["overlay"]
    o.add_argument("--maps", required=True)
    o.add_argument("--transitions", nargs="*", default=[], help="transitions.jsonl files (globs ok)")
    o.add_argument("--agents", default=None, help="runs/agents registry dir (names agents by id)")
    o.add_argument("--base", default=None, help="a previously rendered world.png (skips the ROM render)")
    o.add_argument("--layers", default=",".join(LAYERS))
    o.add_argument("--trail", type=int, default=80)
    a = ap.parse_args(argv)
    rom = load(a.rom)
    headers = all_headers(rom)
    layout = build_layout(headers)
    if a.cmd == "overlay" and a.base:
        base = np.asarray(Image.open(a.base).convert("RGB"))
    else:
        base = render_world(rom, headers, layout, a.links)
    if a.cmd == "render":
        _save(base, a.out)
        return 0
    files = [Path(f) for pat in a.transitions for f in sorted(glob.glob(pat))]
    model = json.loads(Path(a.maps).read_text(encoding="utf-8"))
    agents = load_agents(files, Path(a.agents) if a.agents else None, a.trail)
    _save(overlay(base, layout, model, headers, agents, tuple(a.layers.split(","))), a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
