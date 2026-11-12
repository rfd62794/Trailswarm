"""Write a sanitized, allow-list progress export from a maps.json file (no game text, no paths).

    uv run python tools/export_progress.py [MAPS_JSON] --game pokemon-red --out OUT.json

See docs/directives/Progress_Export_Sanitized_Directive.md. Never modifies the input file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from pokeagent.share.progress_export import GAMES, export_progress


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export map progress by allow-list (no game text).")
    ap.add_argument("maps_json", nargs="?", default="runs/maps.json")
    ap.add_argument("--game", required=True, choices=GAMES)
    ap.add_argument("--out", required=True)
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    src, out_path = Path(args.maps_json), Path(args.out)
    if out_path.resolve() == src.resolve():
        print("error: --out must not be the input file", file=sys.stderr)
        return 2
    try:
        doc = json.loads(src.read_text(encoding="utf-8"))
        out, st = export_progress(doc, args.game)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        _write_atomic(out_path, json.dumps(out, indent=1) + "\n")
    except OSError as e:
        print(f"error: cannot write {out_path}: {e}", file=sys.stderr)
        return 2
    t = out["totals"]
    print(f"kept maps={t['maps']} tiles={t['walkable_tiles']} blocked={t['blocked_edges']} "
          f"warps={t['warps']}; dropped maps={st.maps_dropped} tiles={st.tiles_dropped} "
          f"blocked={st.blocked_dropped} warps={st.warps_dropped}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
