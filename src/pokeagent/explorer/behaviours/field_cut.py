"""FieldCut: START -> POKeMON -> the member that knows CUT -> CUT, one press at a time (helpers and the why: explorer/field_cut.py)."""
from __future__ import annotations

import re

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.field_cut import (AFTER_CUT_STEPS, CALM_FRAMES, COOLDOWN, PACE_FRAMES, PRESS_CAP, TILESET_ADDR, can_cut, cutter_slot, state,
                                          tree_ahead, tries_left)
from pokeagent.explorer.party_menu import MENU_ITEM, is_start_menu, screen_lines, start_menu_target, toward
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, frame_lines

_SUBMENU = re.compile(r"^>?\s*(CUT|FLY|SURF|STRENGTH|FLASH|DIG|TELEPORT|SOFTBOILED|STATS|SWITCH|CANCEL)$")


class FieldCut(BehaviourBase):
    name = "field_cut"

    def applies(self, ctx: ExplorerContext) -> bool:
        if ctx.view.battling or ctx.in_battle:
            return False
        st = state(ctx)
        if st["seq"] is not None:
            return True  # a started sequence owns the screen until it ends
        want = st["want"]
        if not want or ctx.step < st["cooldown_until"] or not tries_left(st, want["tree"]):
            return False
        return (ctx.pos() == want["pos"] and ctx.facing == want["dir"] and not ctx.view.box and ctx.stable_frames >= CALM_FRAMES
                and tree_ahead(ctx.view.tm, ctx.facing, ctx.emu.read(TILESET_ADDR)) and can_cut(ctx.emu))

    def _end(self, ctx: ExplorerContext, st: dict, ok: bool, why: str) -> None:
        seq, want = st["seq"], st["want"]
        st["seq"], st["want"] = None, None
        if ok:
            st["cuts"] += 1
        else:
            st["cooldown_until"] = ctx.step + COOLDOWN
            if want:
                st["tries"][want["tree"]] = st["tries"].get(want["tree"], 0) + 1
        ctx.log(f"[field_cut: {'tree cut' if ok else 'gave up'} after {seq['presses'] if seq else 0} presses: {why}]", "res")

    def step(self, ctx: ExplorerContext) -> Decision | None:
        st = state(ctx)
        if st["seq"] is None:
            slot = cutter_slot(ctx.emu)
            if slot is None or not st["want"]:
                return None
            st["seq"] = {"presses": 0, "wait": 0, "chosen": False, "after": 0, "slot": slot}
            ctx.log(f"[field_cut: using CUT on the tree at {st['want']['tree']} from {st['want']['pos']} facing {st['want']['dir']} (party slot {slot})]", "res")
        seq, want = st["seq"], st["want"]
        if seq["wait"] > 0:
            seq["wait"] -= ctx.opts.frames_per_step
            return no_press("field_cut_wait")
        tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
        lines, framed = screen_lines(tm), frame_lines(tm)
        text = " | ".join(lines)
        menus = is_start_menu(" | ".join(framed)) or "Choose a POK" in text or "STATS" in text
        if seq["chosen"]:
            if not menus and not framed and not tree_ahead(tm, want["dir"], ctx.emu.read(TILESET_ADDR)):
                self._end(ctx, st, True, "the tree is gone from the tile in front")
                return no_press("field_cut_done")
            seq["after"] += 1
            if seq["after"] > AFTER_CUT_STEPS:
                self._end(ctx, st, False, "the tree is still there after CUT was chosen")
                return Decision("B", "field_cut_failed", "CUT chosen but the tree stayed: backing out")
        if seq["presses"] >= PRESS_CAP:
            self._end(ctx, st, False, f"not done in {PRESS_CAP} presses")
            return Decision("B", "field_cut_failed", "CUT sequence abandoned")
        if "anything to" in text.lower():  # "There isn't anything to CUT!"
            self._end(ctx, st, False, "the game says there is nothing to cut")
            return Decision("B", "field_cut_failed", "nothing to cut here: closing the text")
        btn, why = self._press(ctx, seq, lines, framed, text)
        seq["presses"] += 1
        seq["wait"] = PACE_FRAMES
        return Decision(btn, "field_cut", f"field_cut: {why}, press {seq['presses']}")

    @staticmethod
    def _press(ctx: ExplorerContext, seq: dict, lines: list[str], framed: list[str], text: str) -> tuple[str, str]:
        cur = ctx.emu.read(MENU_ITEM)
        rows = [ln.strip() for ln in lines if _SUBMENU.match(ln.strip())]
        if "STATS" in text and "SWITCH" in text and rows:  # the member's own menu: CUT sits first, above STATS
            names = [r.lstrip(">").strip() for r in rows]
            if "CUT" not in names:
                return "B", "the member menu has no CUT row: backing out"
            btn = toward(cur, names.index("CUT"))
            if btn == "A":
                seq["chosen"] = True
            return btn, f"member menu: cursor {cur} -> CUT row {names.index('CUT')}"
        if re.search(r"Choose a POK", text, re.I):
            return toward(cur, seq["slot"]), f"party list: cursor {cur} -> slot {seq['slot']}"
        if is_start_menu(" | ".join(framed)):
            row = start_menu_target(framed)
            return (toward(cur, row), f"START menu: cursor {cur} -> POKeMON row {row}") if row is not None else ("B", "START menu without POKeMON")
        if seq["chosen"]:
            return "A", "advancing the CUT text"
        return ("B", "an unknown box: closing it") if framed else ("START", "opening the START menu")
