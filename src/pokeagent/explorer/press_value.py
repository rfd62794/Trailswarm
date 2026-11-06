"""press_value: which A/B presses actually DO something, learned per context, and a gate that stops the useless ones.

A context is the screen kind (overworld / text waiting / text printing / menu / yes-no / battle menu / battle text),
the map, the behaviour asking, the joypad-ignore flag, and the first text line + cursor line. Every agent A/B press
is graded: did it have an EFFECT (text or cursor changed, position or map changed, a box opened or closed, bag /
party / story flags changed) and did a goal or beat PROGRESS within the next few presses. Counts live in maps.json
under "press_value": {sig: {button: {n, effect, progress}}} (500 most-used signatures; the swarm merges per entry,
larger n wins).

The gate (called by the Selector for every decision): readiness, guards, battle_moves and advance_dialog do not
press A/B in a context that has had >= GATE_MIN_N presses with an effect rate under GATE_MAX_RATE (and little
progress). They wait instead, but never longer than WAIT_BOUND frames, so nothing deadlocks. Battle text contexts
need more proof (n >= 20, effect < 10%). Text still printing is only a signature part, never a hold of its own.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from pokeagent.explorer.behaviours.base import Decision, no_press
from pokeagent.explorer.perceive import frame_lines, is_menu

MAX_SIGS = 500  # signatures kept in maps.json (most used)
GATE_MIN_N = 8  # presses of evidence before a context may be gated
GATE_MAX_RATE = 0.15  # effect (and progress) rate below which a press is not worth making
WAIT_BOUND = 90  # frames a gate may hold a press back before it lets one through
BATTLE_TEXT_MIN_N = 20  # battle text contexts need this much evidence ...
BATTLE_TEXT_MAX_RATE = 0.10  # ... and an effect rate under this before they are gated
PROGRESS_WINDOW = 8  # a goal / beat advancing within this many A/B presses credits them
PRINT_QUIET = 12  # frames the box text must hold still before it counts as waiting for input
ARROW = 0xEE  # the blinking "more text" prompt arrow tile
GATED = ("readiness", "guards", "battle_moves", "advance_dialog")
FP_RANGES = ((0xD163, 0x110), (0xD31D, 42), (0xD747, 0x140))  # party, bag, story flags


def screen_kind(view, printing: bool) -> str:
    if not view.box:
        return "overworld"
    if view.battling:
        if any("FIGHT" in ln for ln in view.lines) or is_menu(view.tm):
            return "battle_menu"
        return "battle_text_printing" if printing else "battle_text"
    if is_menu(view.tm):
        yn = any(ln.replace(">", "").strip() in ("YES", "NO") for ln in view.lines)
        return "yes_no" if yn else "menu"
    return "text_printing" if printing else "text_waiting"


@dataclass
class PressValue:
    data: dict
    table: dict = field(init=False)
    pending: list = field(default_factory=list)  # (fine, coarse, button) of the last PROGRESS_WINDOW presses
    wait: tuple | None = None  # (key, first frame) of the hold in force
    text_hash: int | None = None
    changed_frame: int | None = None  # ctx.frame when the box text last changed

    def __post_init__(self) -> None:
        self.table = self.data.setdefault("press_value", {})

    # --- learning ---
    def _bump(self, sig: str, button: str, effect: bool) -> None:
        e = self.table.setdefault(sig, {}).setdefault(button, {"n": 0, "effect": 0, "progress": 0})
        e["n"] += 1
        e["effect"] += int(effect)

    def record(self, fine: str, coarse: str, button: str, effect: bool) -> None:
        self._bump(fine, button, effect)
        self._bump(coarse, button, effect)
        self.pending.append((fine, coarse, button))
        del self.pending[:-PROGRESS_WINDOW]
        self.wait = None  # a press was made: the next one starts a fresh hold
        if len(self.table) > MAX_SIGS + 100:
            trim(self.table)

    def mark_progress(self) -> None:
        for fine, coarse, button in self.pending:
            for sig in {fine, coarse}:
                if button in self.table.get(sig, {}):  # a trimmed signature has nothing to credit
                    self.table[sig][button]["progress"] += 1
        self.pending.clear()

    # --- reading the screen ---
    def watch(self, ctx) -> None:
        """Once per step: did the box text change since the last look (prompt arrow blink excluded)?"""
        h = hash(bytes(0x7F if b == ARROW else b for b in ctx.view.tm)) if ctx.view.box else None
        if h != self.text_hash:
            self.text_hash, self.changed_frame = h, ctx.frame

    def printing(self, ctx) -> bool:
        """Text still printing: a box is open, no prompt arrow, and the text changed within PRINT_QUIET frames."""
        v = ctx.view
        if not v.box or ARROW in v.tm or self.changed_frame is None:
            return False
        return ctx.frame - self.changed_frame < PRINT_QUIET

    # --- the gate's question ---
    def verdict(self, fine: str, coarse: str, button: str) -> str | None:
        """'effect 3/40' when this context has proven useless for this button, else None."""
        battle_text = fine.startswith("battle_text")  # paging battle text is cheap and was costly to hold: more proof needed
        min_n, max_rate = (BATTLE_TEXT_MIN_N, BATTLE_TEXT_MAX_RATE) if battle_text else (GATE_MIN_N, GATE_MAX_RATE)
        for sig in (fine, coarse):
            e = self.table.get(sig, {}).get(button)
            if e and e["n"] >= min_n:
                if e["effect"] / e["n"] < max_rate and e["progress"] / e["n"] < max_rate:
                    return f"{button} had effect {e['effect']}/{e['n']} here"
                return None  # the finest context with enough evidence decides
        return None

    def hold(self, key: str, frame: int) -> bool:
        """True = keep holding; False = the bound passed, let one press through (and start over)."""
        if self.wait and self.wait[0] == key:
            if frame - self.wait[1] >= WAIT_BOUND:
                self.wait = None
                return False
            return True
        self.wait = (key, frame)
        return True


def trim(table: dict) -> None:
    keep = sorted(table, key=lambda s: -sum(e["n"] for e in table[s].values()))[:MAX_SIGS]
    for sig in set(table) - set(keep):
        del table[sig]


def get_pv(ctx) -> PressValue:
    if ctx.pv is None:
        ctx.pv = PressValue(ctx.mem.data)
    return ctx.pv


def context_sigs(ctx, behaviour: str) -> tuple[str, str]:
    """(fine, coarse) signatures of the situation a behaviour is about to press in."""
    v = ctx.view
    kind = screen_kind(v, get_pv(ctx).printing(ctx))
    joy = int(bool(ctx.emu.read(0xCD6B)))
    first = next((ln for ln in v.lines if ln.strip()), "")[:14]
    cursor = next((ln.replace(">", "").strip() for ln in v.lines if ">" in ln), "")[:12]
    coarse = f"{kind}|m{v.m}|{behaviour}|j{joy}"
    return f"{coarse}|{first}|{cursor}", coarse


def _log_gate(ctx, fine: str, button: str, why: str) -> None:
    try:
        with (ctx.run_dir / "press_gate.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"step": ctx.step, "frame": ctx.frame, "sig": fine, "button": button, "why": why}) + "\n")
    except OSError:
        pass


def gate(ctx, decision: Decision) -> Decision:
    """Pass an A/B decision through, or swap it for a bounded wait when the learned context says it is wasted."""
    if decision.button not in ("A", "B"):
        return decision
    pv = get_pv(ctx)
    fine, coarse = context_sigs(ctx, decision.behaviour)
    why = None
    if decision.behaviour in GATED:
        why = pv.verdict(fine, coarse, decision.button)
    if why is not None and pv.hold(f"{fine}|{decision.button}", ctx.frame):
        if decision.behaviour == "readiness":
            ctx.busy_presses = max(0, ctx.busy_presses - 1)  # the press was counted when decided, but never made
        text = f"press_gate: wait ({why})"
        ctx.log(f"[{text}]", "res")
        _log_gate(ctx, fine, decision.button, why)
        held = no_press("press_gate", text)
        held.behaviour = decision.behaviour
        return held
    ctx.pv_pending = (fine, coarse, decision.button)
    return decision


def fingerprint(emu) -> bytes:
    return b"".join(bytes(emu.read_range(a, n)) for a, n in FP_RANGES)


def had_effect(ctx, fr, fp_post: bytes) -> bool:
    if fr.after != fr.before or fr.box_before != fr.box_after:
        return True
    if fr.fp_pre is not None and fp_post != fr.fp_pre:
        return True
    return bool(fr.box_before and frame_lines(fr.tm) != frame_lines(fr.tm2))  # text paged or cursor moved


def observe(ctx, fr) -> None:
    """After an agent A/B press: record whether it did anything in the context the gate saw."""
    pend, ctx.pv_pending = ctx.pv_pending, None
    if not pend or fr.source != "agent" or pend[2] != fr.name:
        return
    ctx.pv_last_effect = had_effect(ctx, fr, fingerprint(ctx.emu))
    get_pv(ctx).record(pend[0], pend[1], pend[2], ctx.pv_last_effect)


def merge_press_value(dst: dict, src: dict) -> None:
    """Swarm merge: every agent started from a copy of the shared table, so per entry the larger n wins (never summed)."""
    table = dst.setdefault("press_value", {})
    for sig, buttons in src.get("press_value", {}).items():
        cur = table.setdefault(sig, {})
        for button, e in buttons.items():
            if e["n"] > cur.get(button, {"n": -1})["n"]:
                cur[button] = dict(e)
    trim(table)
