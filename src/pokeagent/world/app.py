"""``pokeagent world``: open the viewer in world mode, or (``--png``) render the current world state to an image (headless)."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from pokeagent.game.pokemon_red import RED
from pokeagent.game.stores import store_path
from pokeagent.world import layers as layerdata
from pokeagent.world.model import WorldModel


MODE_ALIAS = {"inset": "inset", "inplace": "inplace", "inplace-full": "inplace_full", "auto": "auto", "stretch": "stretch"}


def png(args: argparse.Namespace) -> int:
    from pokeagent.world.export import export_png, fake_tracks, load_world
    from pokeagent.viewer.sources import discover
    world = load_world(args.rom, base=args.base, tint=not args.no_tint)
    wm = WorldModel()
    if args.fake:
        tracks = fake_tracks(world.layout, args.fake)
    else:
        wm.poll(discover(Path(args.root)))
        wm.drain()                                        # poll is async: land the reads before exporting
        tracks = wm.tracks()
        now = time.monotonic()
        for t in tracks:
            t.moved_at = now - 10                       # a still image: no mid-step poses
    layers = tuple(a for a in args.layers.split(",") if a)
    model = wm.union_model()
    if layers and not layerdata.has_data(model, layers):    # --fake / no live agent reports nothing: use the saved maps.json
        saved = layerdata.load_model(args.model or store_path("runs/maps.json", root=Path(args.root)))
        model = saved if layerdata.has_data(saved, layers) else model
    if layers and not layerdata.has_data(model, layers):
        print(f"no learning data for layers {','.join(layers)} (no live agents, no maps.json; try --model PATH)")
    size = export_png(args.png, world, tracks, model, layers, scale=args.scale, interiors=MODE_ALIAS[args.interiors])
    print(f"wrote {args.png} ({size[0]}x{size[1]}, {len(tracks)} agents)")
    return 0


def main(args: argparse.Namespace) -> int:
    if args.png:
        return png(args)
    from pokeagent.viewer.app import run
    return run(args.root, fake=args.fake, mode=args.mode)


def add_parser(sub) -> None:
    p = sub.add_parser("world", help="World view: every agent on one ROM-rendered Kanto (or --png to export)")
    p.add_argument("--root", default=".", metavar="DIR", help="agent registry root (default: cwd)")
    p.add_argument("--fake", type=int, default=0, metavar="N", help="N animated fake agents")
    p.add_argument("--png", metavar="OUT", help="render the world state to a PNG (headless) instead of opening a window")
    p.add_argument("--rom", default=str(RED.default_rom).replace("\\", "/"))
    p.add_argument("--base", metavar="PNG", help="a previously rendered world.png (skips the ROM render)")
    p.add_argument("--layers", default="", help="comma list of learning layers for --png (heat,walls,warps,disagree,...)")
    p.add_argument("--model", metavar="JSON", help="--png layers: a maps.json to draw (default: live agents, else <root>/runs/maps.json)")
    p.add_argument("--no-tint", action="store_true", help="plain map colours instead of the Game Boy green palette")
    p.add_argument("--scale", type=float, default=1.0, help="output scale for --png")
    p.add_argument("--interiors", choices=list(MODE_ALIAS), default="inset",
                   help="--png: interiors inset (grid), inplace (fit to building), inplace-full, auto, or stretch (stretch the outdoor world so rooms fit full size)")
    p.add_argument("--mode", choices=("tiles", "world"), default="world", help="start view (default world; same window as `view`)")
    p.set_defaults(func=main)
