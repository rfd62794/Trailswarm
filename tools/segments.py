"""Segment curriculum report: per-segment solve rate, best and expected frames, confirmation, share of slots,
and the chained personal best.

    uv run python tools/segments.py            # ingest finished segment runs, then print the table
    uv run python tools/segments.py --no-ingest

Columns: attempts (lifetime), rate (solves over the last 20), best (fastest accepted solve, frames; * = not yet
confirmed by a replay, ~ = frames estimated from an old run's press count), expected (mean frames per solve counting each failure at the frames it burned + half a typical solve),
confirmed, share (of the slots the curriculum has handed out). The personal best is the sum of the accepted bests along
the chain; it is only complete once every segment has one.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seg_ingest  # noqa: E402
import seg_split  # noqa: E402
import seg_store as ss  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _fmt(v, spec="{:,.0f}") -> str:
    return "-" if v is None else spec.format(v)


def render(doc: dict) -> list[str]:
    segs = ss.layout(doc)
    per = ss.fps(doc)
    jobs = sum(ss.stat(doc, s.key).get("jobs", 0) for s in segs) or 1
    out = [f"{'segment':<22}{'tries':>6}{'rate':>6}{'best':>10}{'expected':>10}  {'confirmed':<10}{'share':>6}"]
    for s in segs:
        st = ss.stat(doc, s.key)
        r = ss.rate(st)
        b = ss.accepted(st)
        star = "" if st["confirmed"] or not b else "~" if b.get("est") else "*"
        conf = "yes" if st["confirmed"] else ("rejected" if b and b.get("rejected") else "pending" if ss.replayable(b) else "no replay" if b else "-")
        mark = " solved" if ss.is_solved(st) else ""
        out.append(f"{s.key:<22}{st['n']:>6}{_fmt(r, '{:.0%}'):>6}{(_fmt(b['frames']) + star) if b else '-':>10}"
                   f"{_fmt(ss.expected_frames(st, per)):>10}  {conf:<10}{st.get('jobs', 0) / jobs:>6.0%}{mark}")
    c = ss.chain(doc)
    if c["complete"]:
        out.append(f"chained personal best: {c['total']:,} frames ({c['total'] / 60:,.0f} s game time) over {len(c['rows'])} segments"
                   + (f"; unconfirmed: {', '.join(c['unconfirmed'])}" if c["unconfirmed"] else "; all confirmed"))
    else:
        done = len(c["rows"]) - len(c["missing"])
        out.append(f"chained best so far: {c['total']:,} frames over {done} of {len(c['rows'])} segments "
                   f"(first gap: {c['missing'][0] if c['missing'] else '-'})")
    return out


def summary(root: Path = ROOT, do_ingest: bool = True) -> list[str]:
    doc = ss.load(root)
    if do_ingest and seg_ingest.ingest(root, doc):
        ss.save(root, doc)
    return render(doc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ingest", action="store_true", help="read runs/segments.json as it is; do not scan run folders")
    ap.add_argument("--root", default=str(ROOT), help="repo root holding runs/ (default: this checkout)")
    ap.add_argument("--reset-splits", nargs="*", metavar="GOAL", help="undo auto-splits (no names = all) and exit")
    a = ap.parse_args(argv)
    if a.reset_splits is not None:
        doc = ss.load(Path(a.root))
        print("reset splits:", seg_split.reset(doc, a.reset_splits or None) or "none")
        ss.save(Path(a.root), doc)
        return 0
    print("\n".join(summary(Path(a.root), not a.no_ingest)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
