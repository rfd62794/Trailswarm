"""Battle macros: battle_fight(move), use_item(item, on), switch(slot). All read the screen before every press.

They reuse the explorer's own pure menu helpers (item_use, switch_out, party_menu) so a macro walks the same menus the
behaviours do, but under Claude's lease and with a press cap and an explicit stop on any screen they do not expect.
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours.item_use import (
    MAX_ITEM_ATTEMPTS, item_step, no_effect_shown, party_prompt_open)
from pokeagent.explorer.behaviours.switch_out import switch_press
from pokeagent.explorer.party_menu import toward
from pokeagent.intervene.macro_core import MacroArgError, Step, press
from pokeagent.intervene.names import item_id, norm
from pokeagent.intervene.screen import (
    ScreenRead, active_slot, bag_qty, battle_moves, main_cursor, main_menu, party_names, party_slot, toward_main)
from pokeagent.ramstructs import read_party_count


def _to_main(scr: ScreenRead, want: str) -> Step:
    """One press toward `want` on the battle main menu; wait when the cursor is not drawn this frame."""
    cur = main_cursor(scr.frames)
    return Step(wait=4) if cur is None else press(toward_main(cur, want), f"menu {cur} -> {want}")


def build_fight(args: dict):
    """FIGHT -> the named move -> confirm; done when the turn's text has played out and the main menu is back."""
    target = norm(args["move"])

    def step(scr: ScreenRead, st: dict, rig) -> Step:
        moves = battle_moves(rig.emu)
        if not scr.in_battle:
            return Step(done="battle_ended") if st.get("chosen") else Step(stop="not_in_battle")
        idx = next((i for i, m in enumerate(moves) if norm(m) == target), None)
        if idx is None:
            return Step(stop=f"move_unknown: have {', '.join(moves) or 'none'}")
        text = scr.text.lower()
        if "no pp" in text or "no moves left" in text:
            return Step(stop="no_pp")
        if main_menu(scr.frames):
            if st.get("chosen"):
                return Step(done="attacked")
            return _to_main(scr, "FIGHT")
        if scr.menu and any(norm(moves[0]) in norm(ln) for ln in scr.frames):  # the move list
            p = toward(scr.cur, idx)
            st["chosen"] = st.get("chosen") or p == "A"
            return press(p, f"move list -> {moves[idx]}")
        if scr.menu:
            return press("B", "leaving a submenu")
        return press("A", "advancing battle text") if scr.box else Step(wait=10)
    return step, 40


def build_use_item(args: dict):
    """ITEM -> the named bag row -> the target Pokemon; verified by the bag count dropping. 'No effect' backs out and stops."""
    name, on = str(args["item"]), args.get("on")
    iid = item_id(name)
    if iid is None:
        raise MacroArgError(f"unknown item {name!r}")

    def step(scr: ScreenRead, st: dict, rig) -> Step:
        emu = rig.emu
        qty = bag_qty(emu, iid)
        st.setdefault("qty0", qty)
        if st["qty0"] == 0:
            return Step(stop="item_not_in_bag")
        if qty < st["qty0"]:
            st["used"] = True
        if not scr.in_battle:
            return Step(done="used") if st.get("used") else Step(stop="not_in_battle")
        if st.get("used"):
            return Step(done="used") if main_menu(scr.frames) else (press("A", "reading the result") if scr.box else Step(wait=10))
        if no_effect_shown(scr.frames):
            st["no_effect"] = True
        if st.get("no_effect"):
            return Step(stop="no_effect") if main_menu(scr.frames) else press("B", "backing out of a useless item")
        if st.get("attempts", 0) >= MAX_ITEM_ATTEMPTS:
            return Step(stop="attempt_cap")
        target = on
        if target is None:  # never act on a guess: the active slot must be verified against wBattleMon
            active = active_slot(emu)
            if active is None:
                return Step(stop="active_unverified")
            target = active + 1
        if party_prompt_open(scr.frames):
            slot = party_slot(emu, target)
            if slot is None:
                return Step(stop=f"target_not_in_party: {target} (have {', '.join(party_names(emu))})")
            p = toward(scr.cur, slot)
            st["attempts"] = st.get("attempts", 0) + (p == "A")
            return press(p, f"{name} on slot {slot + 1}")
        shim = SimpleNamespace(emu=emu, item_attempts=st.get("attempts", 0))
        cur = next((ln for ln in scr.frames if ">" in ln), "")
        d = item_step(shim, scr.frames, cur, iid, name, "claude use_item")
        st["attempts"] = shim.item_attempts
        if d is not None:
            return press(d.button, d.why)
        return press("A", "advancing battle text") if scr.box else Step(wait=10)
    return step, 40


def build_switch(args: dict):
    """PKMN -> the party slot (1-based) -> SWITCH; done when that Pokemon is out and the main menu is back."""
    slot = int(args["slot"])
    if not 1 <= slot <= 6:
        raise MacroArgError("slot must be 1..6")
    target = slot - 1

    def step(scr: ScreenRead, st: dict, rig) -> Step:
        emu = rig.emu
        if slot > read_party_count(emu):
            return Step(stop="slot_not_in_party")
        if not scr.in_battle:
            return Step(done="switched") if st.get("sent") else Step(stop="not_in_battle")
        active = active_slot(emu)
        text = scr.text.lower()
        if "no will" in text:
            return Step(stop="target_fainted")
        if "already out" in text:
            return Step(stop="already_active")
        if st.get("sent") and main_menu(scr.frames):
            if active is None:
                return Step(stop="active_unverified")
            return Step(done="switched") if active == target else Step(stop="switch_failed")
        if not st.get("sent") and main_menu(scr.frames):
            if active is None:
                return Step(stop="active_unverified")
            if active == target:
                return Step(stop="already_active")
        p = switch_press(scr.frames, scr.screen, scr.cur, target)
        if p is None:
            return press("A", "advancing battle text") if scr.box else Step(wait=10)
        if p == "A" and "SWITCH" in scr.text and "STATS" in scr.text:
            st["sent"] = True
        return press(p, "toward the switch")
    return step, 40
