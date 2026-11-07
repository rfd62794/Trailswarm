"""stalls: diagnose swarm stalls from dossiers (JSON output).

    uv run python tools/stalls.py backfill                     # dossiers for runs/swarm/stalls.jsonl (writes runs/stalls/ only)
    uv run python tools/stalls.py top [--since H] [--segment S] [--coarse] [--limit N]   # signature clusters, biggest first
    uv run python tools/stalls.py show <run>                   # one dossier (a unique fragment of the run name works)

``--root`` (or POKEAGENT_ROOT) is the checkout whose runs/ to read.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent import stalls  # noqa: E402


def since_cutoff(hours: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - hours * 3600)) if hours else None


def find_run(root: Path, frag: str) -> str:
    names = [p.stem for p in (root / "runs" / "stalls").glob("*.json")]
    hits = [n for n in names if n == frag] or [n for n in names if frag in n]
    if len(hits) != 1:
        raise SystemExit(json.dumps({"error": f"{len(hits)} dossiers match {frag!r}", "matches": hits[:10]}))
    return hits[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stalls", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.environ.get("POKEAGENT_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("top")
    t.add_argument("--since", type=float, default=None, help="only stalls from the last H hours")
    t.add_argument("--segment", default=None)
    t.add_argument("--coarse", action="store_true", help="group by map+behaviour+rule only (merges outcome/adjacency noise)")
    t.add_argument("--limit", type=int, default=15)
    sub.add_parser("show").add_argument("run")
    sub.add_parser("backfill")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.cmd == "backfill":
        out = stalls.backfill(root)
    elif a.cmd == "top":
        ds = stalls.load_dossiers(root)
        rows = stalls.cluster(ds, since_cutoff(a.since), a.segment, coarse=a.coarse)
        out = {"dossiers": len(ds), "clusters": len(rows), "top": rows[: a.limit]}
    else:
        out = json.loads((root / "runs" / "stalls" / f"{find_run(root, a.run)}.json").read_text(encoding="utf-8"))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
