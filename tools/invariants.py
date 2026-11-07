"""Invariant checker for the shared learned data in runs/ (read-only).

    uv run python tools/invariants.py check [--json] [--load-states] [--runs DIR]
    uv run python tools/invariants.py fix-plan [--runs DIR]

``check`` prints a summary table and exits 1 when any ERROR-level finding exists. ``--load-states`` also loads each state with a
sidecar in ONE headless PyBoy (slow) and compares RAM (map 0xD35E, respawn 0xD719) with its label and sidecar.
``fix-plan`` prints the safe remediation per finding; it never writes anything.

Supervisor hook (proposed, not wired): in tools/swarm_continuous.py after every Nth finished run (N = 20), add
    if finished % 20 == 0: subprocess.run([sys.executable, "tools/invariants.py", "check", "--json"], stdout=open("runs/invariants.log", "a"))
runs/invariants.log then gets one JSON document per check; grep it for '"level": "ERROR"'.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pokeagent.invariants.fixplan import fix_plan  # noqa: E402
from pokeagent.invariants.runner import has_errors, run_all, summary_table  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "fix-plan"):
        p = sub.add_parser(name)
        p.add_argument("--runs", type=Path, default=ROOT / "runs", help="runs directory (read-only; default <repo>/runs)")
        p.add_argument("--load-states", action="store_true", help="load states in one headless emulator (slow)")
    sub.choices["check"].add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    findings = run_all(a.runs, load_states=a.load_states)
    if a.cmd == "fix-plan":
        print(fix_plan(findings))
        return 0
    if a.json:
        print(json.dumps({"runs": str(a.runs), "ok": not has_errors(findings), "findings": [f.to_json() for f in findings]}, indent=1))
    else:
        print(summary_table(findings))
    return 1 if has_errors(findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
