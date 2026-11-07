"""Generate kb/items.json (item catalog, Mart stocks, trainer prize money; ROM-derived, gitignored) from the ROM.

    uv run python tools/items_catalog.py ["roms/Pokemon Red.gb"]

Needs kb/rom_tables.json (tools/rom_tables.py). The extraction lives in pokeagent.knowledge.items_catalog.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.knowledge import items_catalog as ic  # noqa: E402
from pokeagent.knowledge.kb import ROM_KB  # noqa: E402

if __name__ == "__main__":
    rom = Path(sys.argv[1]) if len(sys.argv) > 1 else ic.ROM_PATH
    cat = ic.build(rom.read_bytes(), ROM_KB)
    ic.KB_PATH.parent.mkdir(exist_ok=True)
    ic.KB_PATH.write_text(json.dumps(cat), encoding="utf-8")
    print(len(cat["items"]), "items;", len(cat["mart_stocks"]), "mart stocks;", dict(Counter(r["use_class"] for r in cat["items"].values())))
