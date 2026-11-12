"""Build the per-game measured RAM address table (and optional stable-retro data.json files) from observation files.

    uv run python tools/ram_address_table.py OBS.json [OBS2.json ...] [--out docs/data/gen1_ram_addresses.json]
        [--retro-dir DIR] [--retro-include measured|believed]

Exit 0 on success, 2 on a malformed observation file (nothing is written).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from pokeagent.ram_lookup import load_map  # noqa: E402
from pokeagent.ramlab.address_table import build_table, status_counts  # noqa: E402
from pokeagent.ramlab.observations import GAMES, ObservationError, load_observations  # noqa: E402
from pokeagent.ramlab.retro_vars import build_retro_data, untyped_count  # noqa: E402

DEFAULT_OUT = Path("docs/data/gen1_ram_addresses.json")
INCLUDE = {"measured": ("measured",), "believed": ("measured", "believed")}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("observations", nargs="+", type=Path, help="observation JSON files")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--retro-dir", type=Path, help="also write <dir>/<game>/data.json per game")
    ap.add_argument("--retro-include", choices=sorted(INCLUDE), default="measured")
    args = ap.parse_args(argv)
    try:
        samples = load_observations(args.observations)
    except ObservationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    table = build_table(load_map(), samples)
    include = INCLUDE[args.retro_include]
    _write_json(args.out, table)
    if args.retro_dir is not None:
        for game in GAMES:
            _write_json(args.retro_dir / game / "data.json", build_retro_data(table, game, include))
    for game in GAMES:
        c = status_counts(table, game)
        unmapped = sum(1 for u in table["unmapped"] if u["samples"][game])
        print(f"{game}: measured={c['measured']} believed={c['believed']} not-exercised={c['not-exercised']} "
              f"unmapped={unmapped} retro-skipped-untyped={untyped_count(table, game, include)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
