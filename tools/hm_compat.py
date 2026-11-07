"""Generate kb/hm_compat.json (HM learnability per species, ROM-derived, gitignored) from the ROM.

    uv run python tools/hm_compat.py ["roms/Pokemon Red.gb"]

The extraction lives in pokeagent.knowledge.hm_compat (catch_list also builds the file on first use when the ROM exists).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.knowledge import hm_compat  # noqa: E402

if __name__ == "__main__":
    hms = hm_compat.build(Path(sys.argv[1]) if len(sys.argv) > 1 else hm_compat.ROM_PATH)
    print({h: len(v) for h, v in hms.items()})
