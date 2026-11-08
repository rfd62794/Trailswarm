"""Scorecard/grade steering for tools/seg_sched.py's Curriculum: pure functions over the doc.

The Curriculum keeps the state (the doc under txn, ROM grids, the hold file, session counters,
logging); these functions take all of it as arguments and answer: which segments are unsolved /
frontier / polish candidates, which category wins this slot, which pending replay or reproduction
job outranks the shares, and which split goals rejoin. In/out arguments (doc, picked, tries, seen,
confirming) are mutated the same way seg_ingest.ingest mutates the doc it is handed.
"""
from __future__ import annotations

import seg_split
import seg_store as ss
from pokeagent import segment_grades as sg
from pokeagent import statefp


def resolve_suite(suite, doc: dict, root, grades, log) -> dict | None:
    """None, a suite NAME resolved through seg_suites, or a ready {key: starter} member map."""
    if suite is None or isinstance(suite, dict):
        return dict(suite) if suite is not None else None
    import seg_suites
    members = seg_suites.resolve(suite, doc, list(grades), root, log=log)
    if members is None:
        raise ValueError(f"unknown or malformed suite {suite!r} (runs/segment_sets.json)")
    return {m["key"]: m.get("starter") for m in members}


def log_refusals(root, segs, refused: set, log) -> None:
    """Say once per checkpoint when a ship-stage state is skipped for a respawn behind Vermilion."""
    for name in {s.start for s in segs} | {s.end for s in segs}:
        why = ss.refusal(root, name)
        if why and name not in refused:
            refused.add(name)
            log(f"curriculum: refusing checkpoint {name}: {why}; the frontier remakes it")


def frontier_seg(doc: dict, root, suite: dict | None = None):
    """The EARLIEST segment whose end checkpoint is not (validly) there yet, once its start is valid.
    A stray checkpoint further up the ladder (a goal reached out of order) never moves it."""
    nxt = next((s for s in ss.layout(doc)
                if not ss.ckpt_valid(root, s.end) and (suite is None or s.key in suite)), None)
    return nxt if nxt is not None and ss.ckpt_valid(root, nxt.start) else None


def grade_groups(doc: dict, root, gm: dict, suite: dict | None = None) -> dict[str, list]:
    """The unsolved/frontier/polish candidate lists (in-order checkpoints only).
    effective-solved: a synthetic_only hypothesis is not a solve for the shares; a broken segment is
    work to redo (unsolved rotation), never polish. Without grade data every flag is off: today's
    behaviour."""
    segs = [s for s in ss.layout(doc)
            if ss.ckpt_valid(root, s.start) and (suite is None or s.key in suite)]
    st = lambda s: ss.stat(doc, s.key)  # noqa: E731

    def eff_solved(s):
        g = gm.get(s.key)
        return ss.is_solved(st(s)) and not (g and g.synthetic_only)

    def broken(s):
        g = gm.get(s.key)
        return bool(g and g.broken)

    def stale(s):
        g = gm.get(s.key)
        return bool(g and g.stale)

    unsolved = sorted((s for s in segs if not eff_solved(s) or broken(s)),
                      key=lambda s: (ss.rate(st(s)) or 0.0, st(s)["n"]))
    per = ss.fps(doc)
    polish = sorted((s for s in segs if eff_solved(s) and not broken(s)),
                    key=lambda s: (not stale(s), -ss.potential_gain(st(s), per)))   # stale first, then most to win
    f = frontier_seg(doc, root, suite)
    return {"unsolved": unsolved, "frontier": [f] if f is not None else [], "polish": polish}


def live_holds(holds, seen: dict, now, log) -> list:
    """Unexpired holds from the hold file (read at most once per call). Logs each new hold once, and
    each expiry once. A hold cleared by the operator before it expires is dropped silently."""
    on_disk = {(h.segment, h.until_text): h for h in holds.current()}
    for key, h in list(seen.items()):
        if h.until <= now:
            log(f"curriculum: hold on {h.segment} expired")
            del seen[key]
        elif key not in on_disk:
            del seen[key]
    live = []
    for key, h in on_disk.items():
        if h.until <= now:
            continue
        if key not in seen:
            seen[key] = h
            log(f"curriculum: holding {h.segment} until {h.until_text} ({h.reason})")
        live.append(h)
    return live


def rejoin_goals(doc: dict, grades: list) -> list[str]:
    """Split goals whose pieces are all solved+optimized with in-tolerance probes (should_rejoin)."""
    return [goal for goal in list(doc["splits"])
            if seg_split.should_rejoin(doc, goal, grades,
                                       [s for s in ss.layout(doc) if s.goal == goal])]


def rejoin_candidates(doc: dict, root, gm: dict, live: list, suite) -> list:
    """Parent segments whose split pieces are all solved+optimized: they earn probe jobs at
    REJOIN_SHARE until the parent's own probes prove the joined segment (should_rejoin then undoes
    the split)."""
    out = []
    for goal in doc["splits"]:
        if any(h.covers(goal) for h in live):
            continue
        pieces = [s for s in ss.layout(doc) if s.goal == goal]
        if suite is not None and goal not in suite and not any(p.key in suite for p in pieces):
            continue
        if not all((g := gm.get(p.key)) is not None and g.solved and g.optimized
                   and not g.synthetic_only for p in pieces):
            continue
        parent = seg_split.parent_segment(doc, goal)
        if parent is not None and ss.ckpt_valid(root, parent.start):
            out.append(parent)
    return out


def pick(avail: dict, eff: dict, picked: dict, tries: dict) -> tuple:
    """The category most behind its effective share, then its candidate: fewest-picks-first for
    unsolved (``cands`` arrives weakest-first), round-robin over the top 3 for polish, first of the
    rest. ``picked``/``tries`` are the session counters, updated here."""
    norm = sum(eff[k] for k in avail)
    total = sum(picked.values())
    cat = max(avail, key=lambda k: (eff[k] / norm * (total + 1) - picked.get(k, 0), eff[k]))
    cands = avail[cat]
    if cat == "unsolved":
        i = min(range(len(cands)), key=lambda j: (tries.get(cands[j].key, 0), j))
    elif cat == "polish":
        i = picked.get(cat, 0) % min(3, len(cands))
    else:
        i = 0
    picked[cat] = picked.get(cat, 0) + 1
    if cat == "unsolved":
        tries[cands[i].key] = tries.get(cands[i].key, 0) + 1
    return cat, cands[i]


def choose(doc: dict, root, gm: dict, live: list, picked: dict, tries: dict, suite,
           base: dict) -> tuple[str, object] | None:
    """The share-weighted slot pick: groups minus held segments, effective shares, rejoin probes off
    the top. Returns (category, segment) or None when no candidate is available."""
    g = grade_groups(doc, root, gm, suite)
    if live:   # a held segment is dropped from every category; an emptied category falls out of the shares
        g = {k: [s for s in v if not any(h.covers(s.key) for h in live)] for k, v in g.items()}
    eff = sg.effective_shares(list(gm.values()), base)
    rejoin = rejoin_candidates(doc, root, gm, live, suite)
    if rejoin:  # probes take their 5% off the top; the other shares keep their proportions
        eff = {k: v * (1 - sg.REJOIN_SHARE) for k, v in eff.items()} | {"rejoin": sg.REJOIN_SHARE}
        g["rejoin"] = rejoin
    avail = {k: v for k, v in g.items() if v}
    if not avail:
        return None
    return pick(avail, eff, picked, tries)


def pending_confirm(doc: dict, suite, confirming: set, confirm_tries: int):
    """The first unconfirmed, unrejected, replayable accepted best under the try cap: a new best is
    only accepted once it re-solves from the same start, seed and memory."""
    for seg in ss.layout(doc):
        if suite is not None and seg.key not in suite:
            continue
        st = ss.stat(doc, seg.key)
        b = st["best"]
        if (b and not b["confirmed"] and not b["rejected"] and ss.replayable(b)
                and b["tries"] < confirm_tries and seg.key not in confirming):
            return seg, st
    return None


def pending_broken_replay(doc: dict, gm: dict, suite, confirming: set, now: float):
    """A BROKEN segment whose accepted best is still replayable earns a confirm-style regression
    replay right after pending confirms: re-run the recorded input to see if the solve survives.
    At most one per segment per BROKEN_RECHECK_HOURS. Not replayable -> the scorecard still shows
    it broken and the normal unsolved rotation carries it."""
    for seg in ss.layout(doc):
        if suite is not None and seg.key not in suite:
            continue
        g = gm.get(seg.key)
        if not g or not g.broken or g.held:
            continue
        st = ss.stat(doc, seg.key)
        if not ss.replayable(ss.accepted(st)) or seg.key in confirming:
            continue
        if now - st.get("recheck_at", 0) < sg.BROKEN_RECHECK_HOURS * 3600:
            continue
        st["recheck_at"] = now
        return seg, st
    return None


def pending_repro(doc: dict, gm: dict, root, suite, now: float):
    """A synthetic_only hypothesis earns an organic-reproduction job (a normal attempt from an
    organic start) just below the broken-replay priority, at most once per BROKEN_RECHECK_HOURS."""
    for seg in ss.layout(doc):
        if suite is not None and seg.key not in suite:
            continue
        g = gm.get(seg.key)
        if not g or not g.synthetic_only or g.held:
            continue
        st = ss.stat(doc, seg.key)
        if now - st.get("repro_at", 0) < sg.BROKEN_RECHECK_HOURS * 3600:
            continue
        start = ss.ckpt(root, seg.start)
        if start is None or not statefp.is_organic(start):
            continue                      # the reproduction must be organic; a promoted start doesn't prove it
        st["repro_at"] = now
        return seg, st
    return None
