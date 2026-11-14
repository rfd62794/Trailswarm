"""Add the ROM-derived ``semantic`` class to every row of an existing samples.jsonl.

    uv run --frozen python tools/vision_relabel.py --root runs/vision/pokemon-red \
        --rom <path-to-rom> [--dry-run]

Reads no images; rewrites samples.jsonl atomically after copying the original to
samples.jsonl.pre-semantic (kept once). Idempotent: a second run labels the same.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.vision.dataset import iter_samples
from pokeagent.vision_model.semantic import SEMANTIC, row_class
from pokeagent.vision_model.semantic_rom import tables_from_rom


def out_in_runs(out: Path, cwd: Path) -> bool:
    """``out`` must resolve inside a ``runs`` directory under the cwd: the dataset stays local,
    never a tracked path."""
    try:
        rel = out.resolve().relative_to(cwd.resolve())
    except ValueError:
        return False
    return rel.parts[:1] == ("runs",) or "runs" in rel.parts[:-1]


def relabel(rows: list[dict], tables: dict[int, dict[int, str]]) -> list[dict]:
    """Each row plus ``semantic`` as its last key; every other field untouched."""
    for row in rows:
        row["semantic"] = row_class(row, tables)
    return rows


def summarise(rows: list[dict]) -> str:
    """Class counts per kind (rows and summed ``count``) plus the tile ``other`` fallback."""
    by_kind: dict[str, dict[str, list[int]]] = {}
    for r in rows:
        c = by_kind.setdefault(r["kind"], {}).setdefault(r["semantic"], [0, 0])
        c[0] += 1
        c[1] += int(r.get("count", 1))
    lines = [f"{'kind':<7} {'class':<10} {'rows':>6} {'count':>8}"]
    for kind in sorted(by_kind):
        for cls in SEMANTIC:
            if cls in by_kind[kind]:
                n, total = by_kind[kind][cls]
                lines.append(f"{kind:<7} {cls:<10} {n:>6} {total:>8}")
    other = by_kind.get("tile", {}).get("other", [0, 0])[0]
    lines.append(f"tile rows fell back to other (no table or tile id): {other}")
    return "\n".join(lines)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Re-label samples.jsonl with the semantic class.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = parse_args(argv)
    root = Path(a.root)
    if not out_in_runs(root, Path.cwd()):
        print(f"error: --root {root} is not inside a runs directory under {Path.cwd()}",
              file=sys.stderr)
        return 2
    src = root / "samples.jsonl"
    rom = Path(a.rom)
    if not src.is_file() or not rom.is_file():
        print(f"error: {src if not src.is_file() else rom} is missing", file=sys.stderr)
        return 2
    tables, ambiguous = tables_from_rom(rom.read_bytes())
    rows = relabel(list(iter_samples(root)), tables)
    print(summarise(rows))
    print("ambiguous tile ids per tileset: "
          + ", ".join(f"{ts}:{n}" for ts, n in sorted(ambiguous.items())))
    if a.dry_run:
        return 0
    backup = root / "samples.jsonl.pre-semantic"
    if not backup.exists():
        backup.write_bytes(src.read_bytes())
    tmp = root / "samples.jsonl.tmp"
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows),
                   encoding="utf-8")
    tmp.replace(src)
    return 0


if __name__ == "__main__":
    sys.exit(main())
