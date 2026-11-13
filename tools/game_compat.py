"""Game compatibility check: compare two games' map memory (and optional RAM tables); exit 0 pass, 1 fail, 3 insufficient, 2 bad input.

    uv run python tools/game_compat.py --baseline A/maps.json --candidate B/maps.json [--baseline-addresses X --candidate-addresses Y]
        [--thresholds T.json] [--baseline-name N --candidate-name N] [--out report.json]
Reads only the files named; never reads a ROM and never writes under runs/ or kb/ unless --out says so.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.compat.report import build_report, sha256_file, summary  # noqa: E402

EXIT = {"pass": 0, "fail": 1, "insufficient": 3}


def _load(path: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"error: cannot read {path}: {e}") from None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--baseline-addresses")
    ap.add_argument("--candidate-addresses")
    ap.add_argument("--thresholds")
    ap.add_argument("--baseline-name", default="baseline")
    ap.add_argument("--candidate-name", default="candidate")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        if bool(a.baseline_addresses) != bool(a.candidate_addresses):
            raise SystemExit("error: --baseline-addresses and --candidate-addresses come as a pair")
        base, cand = _load(a.baseline), _load(a.candidate)
        for name, doc in (("baseline", base), ("candidate", cand)):
            if not isinstance(doc, dict) or not isinstance(doc.get("maps"), dict):
                raise SystemExit(f"error: {name} is not a maps.json document")
        ba = _load(a.baseline_addresses) if a.baseline_addresses else None
        ca = _load(a.candidate_addresses) if a.candidate_addresses else None
        over = _load(a.thresholds) if a.thresholds else None
    except SystemExit as e:
        print(e.code if isinstance(e.code, str) else "error: bad input")
        return 2
    inputs = {k: {"path": v, "sha256": sha256_file(v)} for k, v in
              (("baseline", a.baseline), ("candidate", a.candidate)) if v}
    rep = build_report(base, cand, baseline_addresses=ba, candidate_addresses=ca, overrides=over,
                       baseline_name=a.baseline_name, candidate_name=a.candidate_name, inputs=inputs)
    text = json.dumps(rep, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    print(summary(rep))
    return EXIT[rep["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
