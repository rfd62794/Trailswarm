"""procedures: named button sequences for menu tasks (check health, open the bag, save, read the TOWN MAP).

Each step is verified against the screen text it should produce; a step that does not register is retried slower,
and the pace that works is remembered per procedure (maps.json ``procedures``).
"""
from __future__ import annotations

import re

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, frame_lines, party_hp
from pokeagent.goals import bag_contents

# POKeMON, ITEM, <name>, SAVE, OPTION, EXIT (POKeMON appears once you have one). READ records the screen.
PROCEDURES = {
    "check_health": [("START", r"POK.MON|ITEM"), ("A", r"\d+/\s*\d+|L\d+"), ("READ", None), ("B", None), ("B", None)],
    "open_bag": [("START", r"ITEM"), ("DOWN", r">ITEM"), ("A", r"CANCEL"), ("READ", None), ("B", None), ("B", None)],
    "save_game": [("START", r"SAVE"), ("DOWN", r">ITEM"), ("DOWN", None), ("DOWN", r">SAVE"), ("A", r"save|SAVE"),
                  ("A", r"YES|Saving|saved"), ("A", r"saved|SAVE"), ("A", None), ("B", None), ("B", None)],
    # A new discovery gets maximal exploration (Robert): the TOWN MAP is opened and read the moment we get it.
    "use_town_map": [("START", r"ITEM"), ("DOWN", r">ITEM"), ("A", r"TOWN MAP|CANCEL"), ("A", r"USE|TOSS"), ("A", None),
                     ("READ", None), ("B", None), ("B", None), ("B", None)],
}


class Procedures(BehaviourBase):
    name = "procedures"

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.proc is not None:
            return True
        return bool(ctx.proc_due) and not ctx.view.box and ctx.emu.read(0xD057) == 0

    def step(self, ctx: ExplorerContext) -> Decision | None:
        proc = ctx.proc
        if proc is None and ctx.proc_due and not ctx.view.box and ctx.emu.read(0xD057) == 0:
            name = ctx.proc_due.pop(0)
            if name in PROCEDURES:
                rec = ctx.mem.data.setdefault("procedures", {}).setdefault(name, {"ok": 0, "fail": 0, "pace": ctx.opts.box_pace or 12})
                ctx.proc = proc = {"name": name, "steps": list(PROCEDURES[name]), "i": 0, "retries": 0, "pace": rec["pace"], "wait": 0}
                ctx.log(f"[procedure {name}: start, pace {proc['pace']} frames]", "res")
        if proc:
            if proc["wait"] > 0:
                proc["wait"] -= ctx.opts.frames_per_step
                return no_press("procedure_wait")  # pacing between steps (the learned pace)
            if proc["i"] >= len(proc["steps"]):
                rec = ctx.mem.data["procedures"][proc["name"]]; rec["ok"] += 1; rec["pace"] = proc["pace"]
                ctx.log(f"[procedure {proc['name']}: done in {len(proc['steps'])} steps at pace {proc['pace']} ({rec['ok']} ok / {rec['fail']} fail)]", "res")
                ctx.proc = None
                return no_press("procedure_done")
            btn, expect = proc["steps"][proc["i"]]
            if btn == "READ":
                lines = frame_lines(ctx.emu.read_range(TILEMAP, TILEMAP_LEN))
                ctx.mem.data.setdefault("menus", {})[proc["name"]] = lines[:10]
                hp_r, mx_r = party_hp(ctx.emu)
                ctx.log(f"[procedure {proc['name']}: screen reads {' | '.join(lines[:4])[:90]} (RAM HP {hp_r}/{mx_r}, bag {bag_contents(ctx.emu)})]", "res")
                proc["i"] += 1
                return no_press("procedure_read")
            if expect and proc.get("checking"):  # did the previous press produce what we expected?
                lines = frame_lines(ctx.emu.read_range(TILEMAP, TILEMAP_LEN))
                if any(re.search(expect, ln) for ln in lines):
                    proc["checking"] = False; proc["i"] += 1; proc["wait"] = proc["pace"]
                    return no_press("procedure_verified")
                proc["retries"] += 1
                if proc["retries"] > 3:
                    rec = ctx.mem.data["procedures"][proc["name"]]; rec["fail"] += 1
                    ctx.log(f"[procedure {proc['name']}: step {proc['i']} ({btn}) never showed /{expect}/ - abandoning, pace raised]", "res")
                    rec["pace"] = min(60, proc["pace"] * 2); ctx.proc = None
                    return Decision("B", "procedure_failed", "procedure failed: backing out")
                proc["pace"] = min(60, proc["pace"] * 2); proc["wait"] = proc["pace"]
                return Decision(btn, "procedure_retry", f"procedure {proc['name']}: retry {btn} slower (pace {proc['pace']})")
            decision = Decision(btn, "procedure_step", f"procedure {proc['name']}: step {proc['i'] + 1}/{len(proc['steps'])} {btn}")
            if expect:
                proc["checking"] = True; proc["wait"] = proc["pace"]
            else:
                proc["i"] += 1; proc["wait"] = proc["pace"]
            return decision
        return None

    def failed(self, ctx: ExplorerContext) -> bool:
        return ctx.proc is not None and ctx.proc["retries"] > 3
