"""Presser: one button press and everything the demo learned from it (moved from the demo's do_press closure)."""
from __future__ import annotations

import json

from pokeagent.emulator import Button
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.demos import close_episode, record_intervention, shutdown
from pokeagent.explorer.perceive import (
    DIRS, EFFECT_WINDOW, TILEMAP, TILEMAP_LEN, ahead_tiles, box_open, box_text, frame_lines, is_menu,
)
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.press_goals import record_goals
from pokeagent.explorer.press_interact import record_interaction
from pokeagent.explorer.press_track import track_progress
from pokeagent.goals import GOALS, bag_contents, check_goals


def settle_position(ctx: ExplorerContext, before, max_frames=600):
    """Tick in 8-frame slices until the position has been stable for 3 reads; a map change (warp fade)
    gets 60 more frames and a re-read, so the recorded arrival is the real one, not a mid-fade value."""
    prev, stable, waited = ctx.pos(), 0, 0
    while waited < max_frames:
        ctx.emu.tick(8); waited += 8
        cur = ctx.pos()
        stable = stable + 1 if cur == prev else 0
        prev = cur
        if stable >= 3:
            break
    if prev[0] != before[0]:
        ctx.emu.tick(60); prev = ctx.pos()
    elif prev != before and f"{before[1]},{before[2]},{ctx.last_press}" in ctx.mem.m(before[0])["warps"]:
        # Stepped onto a learned door tile: the warp fade can start after the position looked stable. Wait it out so
        # a real warp is never sampled as 'walked one tile' (that reading is what disproves a warp).
        ctx.emu.tick(60); prev = ctx.pos()
    return prev


def begin_press(ctx: ExplorerContext, fr: PressFrame) -> None:
    """Before the button: step count, interventions, battle log fields, pre-press snapshots."""
    name, source = fr.name, fr.source
    ctx.last_press = name
    before = ctx.pos(); ctx.step += 1
    tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
    box_before = box_open(tm)
    goals_before = check_goals(ctx.emu, ctx)
    if source in ("human", "claude"):
        record_intervention(ctx, name, source, before, tm, goals_before)
    elif ctx.episode:
        close_episode(ctx, before, goals_before)  # the agent is back in control: the demonstration is over
    extra: dict = {}
    flag = ctx.emu.read(0xD057)
    if flag or ctx.in_battle:
        extra["battle_flag"] = flag  # wIsInBattle 0xD057 (verified = 2 for trainer battles)
        u16 = lambda a: (ctx.emu.read(a) << 8) | ctx.emu.read(a + 1)
        bl = ctx.battle_log = ctx.battle_log or {"start": ctx.step, "kind": flag, "turns": [],
                                          "you": [ctx.emu.read(0xD014), ctx.emu.read(0xD022)], "enemy": [ctx.emu.read(0xCFE5), ctx.emu.read(0xCFF3)]}
        if ctx.emu.read(0xCFE5):
            bl["enemy_species"] = ctx.emu.read(0xCFE5); bl["enemy"] = [ctx.emu.read(0xCFE5), ctx.emu.read(0xCFF3)]  # filled once the battle data loads
        lines_b = frame_lines(tm)
        cursor_b = next((ln.replace(">", "").strip() for ln in lines_b if ">" in ln), "")
        if name == "A" and cursor_b:  # a battle choice: what was chosen and the HP situation at that moment
            bl["turns"].append({"step": ctx.step, "chose": cursor_b, "menu": [ln for ln in lines_b if ln.isupper() or ">" in ln][:6],
                                "hp_you": u16(0xD015), "hp_enemy": u16(0xCFE6)})
        extra["battle_turn"] = len(bl["turns"])
    if name in DIRS and not box_before:
        extra["ahead_tiles"] = ahead_tiles(tm, name)  # lets the KB learn which tile ids are walls
    if name not in DIRS or box_before:
        ctx.last_fail = None  # a wall is only 'confirmed' by two consecutive identical move presses
    snap_pre = ctx.emu.read_range(*EFFECT_WINDOW) if not box_before else None
    bag_pre = bag_contents(ctx.emu)
    fr.before = before
    fr.tm = tm
    fr.box_before = box_before
    fr.goals_before = goals_before
    fr.extra = extra
    fr.snap_pre = snap_pre
    fr.bag_pre = bag_pre


def press_and_read(ctx: ExplorerContext, fr: PressFrame) -> None:
    """Press the button, wait for the position to settle, read the screen, track the dialog."""
    name, before, box_before = fr.name, fr.before, fr.box_before
    ctx.emu.press(Button[name])
    after = settle_position(ctx, before)
    tm2 = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
    box_after = box_open(tm2)
    text = box_text(tm2) if box_after else ""
    if text and not is_menu(tm2):
        ctx.last_text = text  # the question a YES/NO box will be about
        # Dialog arrives in fragments ("So! You want | the fire POKeMON," then "CHARMANDER?"): keep the whole
        # conversation since the box opened, so a YES/NO decision can read the name even if it scrolled off.
        if not box_before:
            ctx.dialog = []
        if not ctx.dialog or ctx.dialog[-1] != text:
            ctx.dialog.append(text)
            del ctx.dialog[:-12]
    if name in DIRS and not box_before:
        ctx.facing = name
    fr.after = after
    fr.tm2 = tm2
    fr.box_after = box_after
    fr.text = text


def write_transition(ctx: ExplorerContext, fr: PressFrame) -> None:
    """One line per press in transitions.jsonl (a later process reads it while the demo runs)."""
    name, source, before, after, box_before, text, extra = fr.name, fr.source, fr.before, fr.after, fr.box_before, fr.text, fr.extra
    ctx.trans.write(json.dumps({"step": ctx.step, "from": list(before), "button": name, "to": list(after),
                            "moved": before != after, "textbox": "dialog" if box_before else "none",
                            "text": text, "facing": ctx.facing, "source": source, **extra}) + "\n")
    ctx.trans.flush()  # the later process reads this file while the demo is still running


def log_press(ctx: ExplorerContext, fr: PressFrame) -> None:
    """Console log of the press, periodic map save, and the step cap."""
    name, source, why, after, result, goals = fr.name, fr.source, fr.why, fr.after, fr.result, fr.goals
    mm = ctx.mem.m(after[0])
    gtxt = " ".join(f"{g}{'+' if goals[g] else '-'}" for g in GOALS)
    ctx.log(f"--- step {ctx.step}/{ctx.opts.steps}  map=0x{after[0]:02X} pos=({after[1]},{after[2]}) facing {ctx.facing}  "
        f"party={ctx.emu.read(0xD163)} bag={ctx.emu.read(0xD31D)}  goals: {gtxt}\n"
        f"    learned here: {len(mm['visited'])} tiles, {len(mm['blocked'])} walls, {len(mm['warps'])} warps, "
        f"{len(mm.get('interactions', {}))} interactions", "hdr")
    ctx.log(f"{'human:   ' if source == 'human' else 'thinking:'} {why}", "human" if source == "human" else "why")
    ctx.log(f"button:   {name:<8} result: {result}", "btn")
    ctx.log("", None)
    if ctx.step % 10 == 0:
        ctx.mem.save()
    if ctx.step >= ctx.opts.steps and not ctx.done:
        ctx.done = True; shutdown(ctx); ctx.log(f"done. map memory saved to {ctx.opts.maps_path}; transitions in {ctx.run_dir}", "hdr")


class Presser:
    """``press(name, source, why)``: source is "agent", "human" or "claude" (remote)."""

    def __init__(self, ctx: ExplorerContext) -> None:
        self.ctx = ctx

    def press(self, name: str, source: str, why: str) -> None:
        ctx = self.ctx
        fr = PressFrame(name, source, why)
        begin_press(ctx, fr)
        press_and_read(ctx, fr)
        record_interaction(ctx, fr)
        track_progress(ctx, fr)
        if ctx.anomalies is not None:
            try:  # watching must never end a run
                ctx.anomalies.observe(ctx, fr)
            except Exception as e:
                ctx.log(f"[anomaly monitor failed: {e!r}]", "res")
        write_transition(ctx, fr)
        if record_goals(ctx, fr):
            return
        log_press(ctx, fr)
