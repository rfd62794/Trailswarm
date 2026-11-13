"""ROM-gated compat run (the laptop runs this; hashes only are printed): Red vs Blue map headers, WRAM symbol
operand counts, and the version-exclusive wild-encounter overlay.

    uv run python tools/game_compat_rom.py [--red PATH] [--blue PATH] [--write-overlay --kb kb/rom_tables.json]
Exit 0 when headers and symbols agree, 1 otherwise. --write-overlay writes kb/overlay/pokemon-blue/{rom_tables,disagreements}.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pokeagent.compat import rom_check as rc  # noqa: E402
from pokeagent.family.kb_overlay import write_overlay  # noqa: E402
from pokeagent.game import BLUE, RED  # noqa: E402
from pokeagent.game.symbols import symbol_table  # noqa: E402


def wild_tables(data: bytes) -> dict:
    import rom_world
    from rom_tables import text
    p = 7 * 0x4000 + (0x421E - 0x4000)
    names = {i: text(data[p + 10 * (i - 1):p + 10 * i] + b"\x50") for i in range(1, 191)}
    return rom_world.wild(data, names)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--red", default=str(RED.default_rom))
    ap.add_argument("--blue", default=str(BLUE.default_rom))
    ap.add_argument("--kb", default="kb/rom_tables.json")
    ap.add_argument("--write-overlay", action="store_true")
    a = ap.parse_args(argv)
    red, blue = Path(a.red).read_bytes(), Path(a.blue).read_bytes()
    h = rc.compare_headers(red, blue)
    syms = symbol_table(RED)
    s = rc.compare_symbol_counts(rc.symbol_operand_counts(red, syms), rc.symbol_operand_counts(blue, syms))
    rw, bw = wild_tables(red), wild_tables(blue)
    ov = rc.wild_overlay(rw, bw)
    diff_maps = sorted(ov.get("wild_by_map", {}), key=int)
    print(f"headers: {h['maps_red']} red / {h['maps_blue']} blue, different={h['different']}")
    print(f"symbols: {s['symbols']} checked, mismatched={s['mismatched']}")
    print(f"wild (version-exclusive) maps differing: {len(diff_maps)} {diff_maps}")
    if a.write_overlay:
        base_path = Path(a.kb)
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
        write_overlay(base_path, BLUE.key, {**base, "wild_by_map": {str(k): v for k, v in rw.items()}},
                      {**base, "wild_by_map": {str(k): v for k, v in bw.items()}})
    ok = not h["different"] and not h["only_red"] and not h["only_blue"] and not s["mismatched"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
