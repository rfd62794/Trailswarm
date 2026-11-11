"""Per-press learning that is not tied to one interaction (moved from the demo's do_press)."""
from __future__ import annotations

import os
from pathlib import Path

from pokeagent.checkpoint_goals import stamp_fingerprint
from pokeagent.explorer.behaviours.frontier import TABU_LEN
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import DIRS, frame_lines, is_menu
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.stat_records import note_stat_exp
from pokeagent.goals import GOALS, bag_contents, check_goals, store_path

ITEM_NAMES = {0x01: "MASTER BALL", 0x02: "ULTRA BALL", 0x03: "GREAT BALL", 0x04: "POKE BALL", 0x05: "TOWN MAP", 0x06: "BICYCLE",
              0x0B: "ANTIDOTE", 0x0C: "BURN HEAL", 0x0D: "ICE HEAL", 0x0E: "AWAKENING", 0x0F: "PARLYZ HEAL", 0x10: "FULL RESTORE",
              0x11: "MAX POTION", 0x12: "HYPER POTION", 0x13: "SUPER POTION", 0x14: "POTION", 0x1D: "ESCAPE ROPE", 0x1E: "REPEL",
              0x46: "OAK'S PARCEL"}  # pokered item constants; only POTION (0x14) verified so far


def track_progress(ctx: ExplorerContext, fr: PressFrame) -> None:
    """Per-press learning: tile visits, story flags, team checkpoint, XP economics, items, NPC talk, beats."""
    name, source, before, after, tm, box_before, box_after, text, extra, goals_before, result, bag_pre = fr.name, fr.source, fr.before, fr.after, fr.tm, fr.box_before, fr.box_after, fr.text, fr.extra, fr.goals_before, fr.result, fr.bag_pre
    ctx.mem.visit(after[0], after[1], after[2], ctx.step)
    if after != before:  # a move: momentum memory for choose() - in-memory only, never written to maps.json
        entered = after[0] != before[0]
        if entered:
            ctx.last_dir = None  # a new map: the direction we came in on says nothing about the new one
            ctx.recent_tiles.pop(after[0], None)  # tiles stood on in an earlier visit are stale (reset on entry)
        elif name in DIRS:
            ctx.last_dir = name
        stood = ctx.recent_tiles.setdefault(after[0], [])
        stood.append((after[1], after[2]))
        del stood[:-TABU_LEN]
    ctx.mem.observe_npcs(after[0], ctx.emu, ctx.step)
    # Event/completion tracking: the story flags (wEventFlags 0xD747-0xD886, from pokered.sym) are the game's own
    # record of what has been done once. Any bit that flips is remembered with where, when and what was on screen.
    ev = ctx.emu.read_range(0xD747, 0x140)
    if ctx.events_prev is not None and ev != ctx.events_prev:
        flips = [(i, (ctx.events_prev[i], ev[i])) for i in range(len(ev)) if ev[i] != ctx.events_prev[i]]
        rec = {"step": ctx.step, "map": before[0], "at": [before[1], before[2]], "text": (ctx.last_text or text)[:80],
               "flags": [[f"0x{0xD747 + i:04X}", o, n] for i, (o, n) in flips[:8]], "run": ctx.run_dir.name}
        ctx.mem.data.setdefault("events", []).append(rec); del ctx.mem.data["events"][:-300]
        extra["event_flags"] = rec["flags"]
        ctx.log(f"*** EVENT: {len(flips)} story flag byte(s) changed at map 0x{before[0]:02X} ({before[1]},{before[2]}): {rec['flags'][:3]} ***", "res")
    ctx.events_prev = ev
    # Team checkpoint: whenever the lead pokemon's level beats the best ever, save a 'team_best' state the
    # explorer agents start from (Robert: trainer agents feed the stronger team to the map-clearing agents).
    lvl = ctx.emu.read(0xD18C)
    if lvl > ctx.best_level_seen:
        ctx.best_level_seen = lvl
        best = ctx.mem.data.get("team_best_level", 0)
        side = store_path("runs/checkpoints/team_best.level", scope="game")
        try:  # another agent may have saved a stronger team than our copy of the memory knows about
            best = max(best, int(side.read_text())) if side.exists() else best
        except Exception:
            pass
        if lvl > best and ctx.emu.read(0xD057) == 0 and not box_after:
            try:
                cp = store_path("runs/checkpoints", scope="game"); cp.mkdir(parents=True, exist_ok=True)
                side.write_text(str(lvl))
                tmp = cp / f"team_best.{os.getpid()}.tmp"; ctx.emu.save_state(tmp); os.replace(tmp, cp / "team_best.state")
                stamp_fingerprint(ctx.emu, cp / "team_best.state", ctx.run_dir.name, inherit=getattr(ctx.opts, "state_path", "") or None)  # lineage carries from the run's start
                ctx.mem.data["team_best_level"] = lvl; ctx.log(f"*** TEAM CHECKPOINT: level {lvl} saved as team_best.state ***", "res")
            except Exception as e:
                ctx.log(f"[team checkpoint failed: {e!r}]", "res")
    # Training economics: experience gained per map (wPartyMon1Exp 0xD179, 3 bytes) so the trainer can pick the
    # grass with the best XP per step for its level - the 'optimized training strategy' data.
    exp_now = (ctx.emu.read(0xD179) << 16) | (ctx.emu.read(0xD17A) << 8) | ctx.emu.read(0xD17B)
    if ctx.exp_prev is not None and exp_now > ctx.exp_prev:
        tr = ctx.mem.data.setdefault("training", {}).setdefault(str(before[0]), {"exp": 0, "steps": 0, "by_level": {}})
        tr["exp"] += exp_now - ctx.exp_prev
        lv = str(ctx.emu.read(0xD18C)); tr["by_level"][lv] = tr["by_level"].get(lv, 0) + (exp_now - ctx.exp_prev)
    if ctx.exp_prev is not None:
        ctx.mem.data.setdefault("training", {}).setdefault(str(before[0]), {"exp": 0, "steps": 0, "by_level": {}})["steps"] += 1
    ctx.exp_prev = exp_now
    try:  # record-only stat-exp yield: never let it end a run
        sx_now = sum(int.from_bytes(ctx.emu.read_range(0xD17C + 2 * i, 2), "big") for i in range(5))  # wPartyMon1 stat exp
        note_stat_exp(ctx.mem.data.setdefault("training", {}).setdefault(str(before[0]), {"exp": 0, "steps": 0, "by_level": {}}), sx_now, ctx.stat_exp_prev)
        ctx.stat_exp_prev = sx_now
    except Exception:
        ctx.stat_exp_prev = None
    bag_post = bag_contents(ctx.emu)
    if bag_post != bag_pre:  # an item was received, used, bought or sold: remember where and from what
        for item in set(bag_pre) | set(bag_post):
            delta = bag_post.get(item, 0) - bag_pre.get(item, 0)
            if delta:
                iname = ITEM_NAMES.get(item, f"item 0x{item:02X}")
                rec = {"item": iname, "id": item, "delta": delta, "map": before[0], "at": [before[1], before[2]],
                       "facing": ctx.facing, "text": (ctx.last_text or text)[:80], "step": ctx.step, "run": ctx.run_dir.name}
                ctx.mem.data.setdefault("items", []).append(rec); del ctx.mem.data["items"][:-200]
                extra["item"] = rec
                if delta > 0 and item == 0x05 and "use_town_map" not in ctx.proc_done:
                    ctx.proc_due.append("use_town_map"); ctx.proc_done.add("use_town_map")
                if delta > 0:
                    ctx.explore_burst = 60  # something new: look around properly before moving on
                ctx.log(f"*** ITEM {'RECEIVED' if delta > 0 else 'USED/LOST'}: {iname} x{abs(delta)} at map 0x{before[0]:02X} ({before[1]},{before[2]}) ***", "res")
    if name == "A" and box_after and not box_before:  # talked to whatever is in front: tie the text to the NPC there
        dx, dy = DIRS[ctx.facing]
        npc = ctx.mem.npc_at(before[0], before[1] + dx, before[2] + dy)
        if npc is not None:
            npc["talked"] += 1
            if len(text) > len(npc.get("text", "")):
                npc["text"] = text[:160]
            result += f" [NPC pic {npc['pic']}{' (moves)' if npc.get('moves') else ''}]"
    ctx.box_streak = ctx.box_streak + 1 if box_after else 0
    # Beat capture: the presses from a box opening (keyed by its first text) to its closing, graded by progress.
    if box_after and not box_before:
        ctx.beat = {"sig": None, "buttons": [], "goals": goals_before, "pos": before, "sources": set()}
    elif ctx.beat and box_before:
        lines_b = frame_lines(tm)
        if ctx.beat["sig"] is None and len(lines_b) >= 2:  # first line is complete once a second line exists
            ctx.beat["sig"] = lines_b[0][:60]
        if is_menu(tm):  # a beat must never carry a decision (YES/NO, menu): rules decide those, not replays
            ctx.beat["choice"] = True
        ctx.beat["buttons"].append(name); ctx.beat["sources"].add(source)
        if not box_after:
            bt = ctx.pop("beat"); goals_now = check_goals(ctx.emu, ctx)
            progressed = (any(goals_now[g] and not bt["goals"].get(g) for g in GOALS) or bool(extra.get("ram_diff"))) \
                and not bt.get("choice")
            src = "human" if "human" in bt["sources"] else "claude" if "claude" in bt["sources"] else "agent"
            if bt["sig"] is None:
                progressed = False  # a one-line box (the START menu) never got a signature: nothing to key a beat on
            else:
                ctx.mem.learn_beat(bt["sig"], bt["buttons"], progressed, src)
            if progressed:
                ctx.log(f"[beat learned for \"{bt['sig'][:40]}\": {len(bt['buttons'])} presses ({src})]", "res")
    fr.result = result
