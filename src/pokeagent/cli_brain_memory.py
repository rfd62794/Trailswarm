"""``pokeagent brain audit`` and ``pokeagent brain clean``: argparse and emit only.

``audit`` is read-only. ``clean`` is a dry run by default; ``--write`` appends the plan to the edit
journal (never to maps.json) and refuses while any agent is alive. The journal must then be folded
with ``brain apply --backup`` before any agent starts: until the fold, every agent load/save and the
swarm merge re-apply the clear ops and would wipe ``done``/``type`` values agents set again.
Logic lives in ``pokeagent.brain.audit`` / ``pokeagent.brain.cleanplan`` / ``pokeagent.explorer.edits``.
"""
from __future__ import annotations

import copy
import json
from collections import Counter

from pokeagent.brain import fileops
from pokeagent.brain.audit import audit, summary
from pokeagent.brain.cleanplan import plan_clean, unreachable_npcs
from pokeagent.explorer import edits as edit_journal

FOLD_REMINDER = ("journal written, maps.json untouched: fold it now with 'brain apply --backup' while no agent "
                 "is alive, before any agent starts (unfolded, agents and the swarm merge keep re-applying it)")


def _emit(obj, args, text_out: str | None = None) -> None:
    if getattr(args, "text", False) and text_out is not None:
        print(text_out)
    else:
        print(json.dumps(obj, indent=1, sort_keys=True))


def _cmd_audit(args) -> int:
    report = audit(fileops.effective_data(args.maps)[0])
    _emit(report, args, summary(report))
    return 0


def _dry_run(data, plan) -> dict:
    return {"dry_run": True, "planned": len(plan), "by_reason": dict(sorted(Counter(p["note"] for p in plan).items())),
            "npc_unreachable_skipped": unreachable_npcs(data),
            "edits": [{"op": p["op"], "map": p["map"], "key": p["key"], "value": p["value"], "reason": p["note"]}
                      for p in plan]}


def _write(data, jpath, plan) -> dict:
    work, written, skipped = copy.deepcopy(data), 0, 0
    for p in plan:
        mid, key, value = edit_journal.prepare(p["op"], p["map"], p["key"], p["value"])
        prior = edit_journal.prior_state(work, p["op"], mid, key, value)
        if prior is None:
            skipped += 1
            continue
        rec = edit_journal.append_edit(jpath, op=p["op"], map_id=mid, key=key, value=value,
                                       note=p["note"], by="brain-clean", prior=prior)
        edit_journal.apply(work, [rec])
        written += 1
    return {"ok": True, "written": written, "skipped_noop": skipped, "journal": str(jpath),
            "reminder": FOLD_REMINDER}


def _cmd_clean(args) -> int:
    data, jpath = fileops.effective_data(args.maps)
    plan = plan_clean(data)
    if not args.write:
        out = _dry_run(data, plan)
        _emit(out, args, "\n".join([f"dry run: {out['planned']} edit(s); nothing written",
                                    *(f"  {r}: {n}" for r, n in out["by_reason"].items()),
                                    f"  npc_unreachable_skipped: {out['npc_unreachable_skipped']}",
                                    *(f"  {e['op']} map={e['map']} key={e['key']} ({e['reason']})"
                                      for e in out["edits"])]))
        return 0
    live = fileops.live_agents(args.maps)
    if live:
        msg = f"refusing to write while agents are alive: {live}"
        _emit({"error": msg}, args, f"error: {msg}")
        return 1
    out = _write(data, jpath, plan)
    _emit(out, args, f"wrote {out['written']} edit(s) to {out['journal']} "
                     f"(skipped_noop {out['skipped_noop']})\n{FOLD_REMINDER}")
    return 0


def add_commands(bsub, common) -> None:
    """Attach ``audit`` and ``clean`` to the brain subparsers (``common`` carries --maps/--text)."""
    bsub.add_parser("audit", parents=[common],
                    help="read-only memory audit: counts and locations per finding class").set_defaults(func=_cmd_audit)
    c = bsub.add_parser("clean", parents=[common],
                        help="plan journal edits that strip playthrough state and noise (dry run unless --write)")
    c.add_argument("--write", action="store_true",
                   help="append the plan to the journal (never maps.json); refuses while agents are alive")
    c.set_defaults(func=_cmd_clean)
