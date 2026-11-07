"""Operator CLI for the curriculum hold list (runs/curriculum_hold.json). Holds are read by seg_sched.Curriculum.choose().

  uv run python tools/curriculum_hold.py add gyarados --hours 24 --reason "training stall fix pending"
  uv run python tools/curriculum_hold.py list
  uv run python tools/curriculum_hold.py clear gyarados
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seg_hold  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="curriculum_hold", description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root holding runs/ (default: this checkout)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="hold a segment for some hours (replaces an existing hold on it)")
    a.add_argument("segment")
    a.add_argument("--hours", type=float, required=True)
    a.add_argument("--reason", required=True)
    sub.add_parser("list", help="show holds, active and expired")
    c = sub.add_parser("clear", help="remove the hold on a segment")
    c.add_argument("segment")
    args = ap.parse_args(argv)

    p = seg_hold.path(args.root)
    holds = seg_hold.read_file(p)
    if args.cmd == "add":
        if not math.isfinite(args.hours) or args.hours <= 0:
            ap.error("--hours must be a finite number greater than 0")
        try:
            until = datetime.now().astimezone() + timedelta(hours=args.hours)
        except OverflowError:
            ap.error("--hours is too large")
        text = until.isoformat(timespec="seconds")
        holds = [h for h in holds if h.segment != args.segment]
        holds.append(seg_hold.Hold(args.segment, text, until, args.reason))
        seg_hold.write_file(p, holds)
        print(f"holding {args.segment} until {text} ({args.reason})")
    elif args.cmd == "list":
        now = datetime.now().astimezone()
        if not holds:
            print("no holds")
        for h in holds:
            state = "active" if h.until > now else "expired"
            print(f"{h.segment}\tuntil {h.until_text}\t{state}\t{h.reason}")
    else:
        kept = [h for h in holds if h.segment != args.segment]
        if len(kept) == len(holds):
            print(f"no hold on {args.segment}")
        else:
            seg_hold.write_file(p, kept)
            print(f"cleared {args.segment}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
