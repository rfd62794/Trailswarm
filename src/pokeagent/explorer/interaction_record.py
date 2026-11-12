"""interaction_record: close an interaction - classify it, memorise its conversation, count it for the metrics.

Called by press_interact when a text box closes. Adds to the interaction entry: ``type`` (+ votes, confidence, why),
``pages`` (the ordered, de-duplicated text pages), ``best_presses`` (fewest presses that completed it) and, for a
giver, ``done``. Per-type totals go to maps.json ``interaction_stats`` (presses, talks, re-talks, heals)."""
from __future__ import annotations

from pokeagent.explorer.decisions import goal_stage
from pokeagent.explorer.interaction_types import GIVER, HEALER, SIGN, INFO, TYPES, read_effects, record_type
from pokeagent.explorer.perceive import EFFECT_WINDOW

MAX_PAGES = 24


def add_pages(entry: dict, dialog: list) -> None:
    """Append the pages of this conversation that the entry does not hold yet (order kept)."""
    pages = entry.setdefault("pages", [])
    for p in dialog:
        if p and p not in pages and len(pages) < MAX_PAGES:
            pages.append(p)


def run_id(ctx) -> str:
    """Identity of this run (its run dir name); "" when the context has none."""
    return getattr(getattr(ctx, "run_dir", None), "name", "") or ""


def stats(ctx) -> dict:
    return ctx.mem.data.setdefault("interaction_stats", {"by_type": {}, "retalks": 0, "heal_visits": 0})


def close_interaction(ctx, inter: dict, pos_after: tuple) -> str:
    """Classify the finished interaction and update the entry and the stats. Returns the type."""
    entry = inter["entry"]
    ctx.talk_closed_frame, ctx.post_talk_waits = ctx.frame, 0
    snap = inter.get("snap")
    add_pages(entry, list(ctx.dialog))
    now = ctx.emu.read_range(*EFFECT_WINDOW)
    first = entry.get("count", 1) <= 1
    fx = read_effects(snap if snap is not None else now, now, texts=entry.get("pages", []), menus=inter["menus"],
                      npc=not inter.get("solid", False), repeat_same=not first,
                      pos_before=tuple(inter.get("pos", pos_after)), pos_after=tuple(pos_after))
    kind = record_type(entry, fx)
    if kind == GIVER:
        entry["done"] = True
        entry["done_run"] = run_id(ctx)  # maps.json outlives the run: "given" is only true for the run that saw the reward
    entry["goal"] = goal_stage(ctx.goals())  # which goal was active when it was last read (retalk_veto compares)
    best = entry.get("best_presses")
    entry["best_presses"] = inter["presses"] if best is None else min(best, inter["presses"])
    st = stats(ctx)
    t = st["by_type"].setdefault(kind, {"talks": 0, "presses": 0})
    t["talks"] += 1
    t["presses"] += inter["presses"]
    if not first and kind in (INFO, SIGN):
        st["retalks"] += 1  # an info/sign spot talked to again: the policy should have skipped it
    if kind == HEALER:
        st["heal_visits"] += 1
    ctx.log(f"[interaction typed {kind} ({entry['type_conf']:.0%}): {entry['type_why']}; {inter['presses']} presses, "
            f"{len(entry['pages'])} pages memorised]", "res")
    return kind


__all__ = ["close_interaction", "add_pages", "stats", "TYPES"]
