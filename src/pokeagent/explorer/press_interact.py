"""Interaction bookkeeping for one press (moved from the demo's do_press)."""
from __future__ import annotations

from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.interaction_record import close_interaction
from pokeagent.explorer.items import is_item_ball, parse_item_text
from pokeagent.explorer.perceive import DIRS, box_text, effects, EFFECT_WINDOW, frame_lines, is_menu, npc_positions, sprite_snapshot
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.world import DUNGEON_MAPS

NPC_BLOCK_FRAMES = 240  # how long a person in the way keeps their tile out of routing


def record_interaction(ctx: ExplorerContext, fr: PressFrame) -> None:
    """Interaction bookkeeping for one press: close, advance or open an interaction; learn walls and warps."""
    name, before, after, tm, tm2, box_before, box_after, text, extra, snap_pre = fr.name, fr.before, fr.after, fr.tm, fr.tm2, fr.box_before, fr.box_after, fr.text, fr.extra, fr.snap_pre
    inter = ctx.inter
    if box_before:
        if inter:
            inter["presses"] += 1
            # The first capture happens while the text is still printing ("So! Y"): keep the fullest dialog seen.
            full = " / ".join(ctx.dialog)[:400]
            if len(full) > len(inter["entry"].get("text", "")):
                inter["entry"]["text"] = full
            if is_menu(tm) and name == "A":  # a choice was made on a menu: remember which line the cursor was on
                chosen = next((ln for ln in frame_lines(tm) if ">" in ln), "").replace(">", "").strip()
                yn = ctx.pop("yesno")
                if yn and chosen.endswith(yn["answer"]):
                    chosen = f"YES/NO '{yn['question']}' -> {yn['answer']}"
                if chosen:
                    inter["choices"].append(chosen)
            if box_after and is_menu(tm2):
                menu = box_text(tm2)
                if menu not in inter["menus"]:
                    inter["menus"].append(menu)
        if not box_after and inter:
            ctx.mem.finish_interaction(inter["entry"], inter["presses"], inter["menus"], inter["choices"])
            if inter.get("ball") is not None:  # the dialog is complete: record the fullest text + parsed item
                bx, by = inter["ball"]
                full = inter["entry"].get("text") or " / ".join(ctx.dialog)
                ctx.mem.note_item_ball(before[0], bx, by, text=full, seen=False)
                ctx.ball_result = (before[0], bx, by, parse_item_text(full))  # THIS press's own outcome
            extra["ram_diff"], fx = effects(inter["snap"], ctx.emu.read_range(*EFFECT_WINDOW))
            inter["entry"].setdefault("effects", [])
            if fx not in inter["entry"]["effects"]:
                inter["entry"]["effects"].append(fx)
            close_interaction(ctx, inter, after)
            result = (f"interaction closed after {inter['presses']} presses; menus seen: {len(inter['menus'])}, "
                      f"choices: {inter['choices'] or 'none'}; effects: {fx}")
            ctx.inter = None
        else:
            result = f"text box: advanced ({'menu' if is_menu(tm2) else 'dialog'})"
    elif name == "A":
        # Record the A press either way, so a silent wall is tested once and never again.
        fdx, fdy = DIRS[ctx.facing]
        npc_in_front = ctx.mem.npc_at(before[0], before[1] + fdx, before[2] + fdy)
        ball = (before[1] + fdx, before[2] + fdy) if is_item_ball(npc_in_front) else None
        if ball is not None:
            ctx.mem.note_item_ball(before[0], ball[0], ball[1], text=text)
        if npc_in_front is not None:  # people move: their results belong to the NPC record, not to the tile
            npc_in_front["talked"] = npc_in_front.get("talked", 0) + 1
            if len(text) > len(npc_in_front.get("text", "")):
                npc_in_front["text"] = text[:160]
            entry = npc_in_front.setdefault("results", {"count": 0, "text": "", "presses": [], "menus": [], "choices": []})
            entry["count"] += 1
        else:
            entry = ctx.mem.interact(before[0], before[1], before[2], ctx.facing, text if box_after else "")
        ctx.mem.recent_talk.add(f"{before[1]},{before[2]},{ctx.facing}")
        if box_after:
            ctx.inter = {"entry": entry, "presses": 1, "menus": [box_text(tm2)] if is_menu(tm2) else [],
                           "choices": [], "snap": snap_pre, "ball": ball, "pos": before, "solid": npc_in_front is None}
            extra["sprites"] = sprite_snapshot(ctx.emu)
        result = (f"INTERACTION at ({before[1]},{before[2]}) facing {ctx.facing}: \"{text[:60]}\""
                  if box_after else f"nothing to interact with facing {ctx.facing} (remembered)")
    else:
        fail_key = (before, name)
        confirmed = ctx.last_fail == fail_key
        dx, dy = DIRS.get(name, (0, 0))
        npc_ahead = name in DIRS and after == before and (before[1] + dx, before[2] + dy) in npc_positions(ctx.emu)
        result = ctx.mem.learn(before, name, after, confirmed=confirmed, npc_ahead=npc_ahead)
        exploring = fr.why.startswith("frontier")  # exploration never needs a person's tile: route around the person (Route 25 trainers, 2026-11-06)
        if npc_ahead and (before[0] in DUNGEON_MAPS or exploring):  # elsewhere the person may be the target (nurse, Mom, clerk); the tile decays and is never learned as a wall
            tb = ctx.mem.temp_blocked
            for k in [k for k, until in tb.items() if until <= ctx.frame]:
                del tb[k]  # prune here too: headless/demo runs have no anomaly monitor to expire them
            tb[(before[0], before[1] + dx, before[2] + dy)] = ctx.frame + NPC_BLOCK_FRAMES
            if exploring:
                ctx.frontier_route, ctx.frontier_target, ctx.frontier_at = [], None, None  # replan around the person
        if "ahead_tiles" in extra and after[0] == before[0]:
            if result.startswith("blocked (confirmed)") and not npc_ahead and not box_after:
                ctx.mem.learn_tiles(ctx.emu.read(0xD367), extra["ahead_tiles"], walkable=False, stand=extra.get("stand_tile"))  # a real wall, not a person
            elif result.startswith("moved"):
                ctx.mem.learn_tiles(ctx.emu.read(0xD367), extra["ahead_tiles"], walkable=True, stand=extra.get("stand_tile"))
        ctx.last_fail = fail_key if (name in DIRS and after == before) else None
        if after[0] != before[0]:
            ctx.settle = 30  # fade already waited out; a short pause so the watcher sees the arrival
        if box_after and not ctx.inter and ctx.proc is None:  # (a procedure's own menu is not an interaction) walked into an NPC, or a scripted event fired (Oak!)
            entry = ctx.mem.interact(before[0], before[1], before[2], ctx.facing, text)
            ctx.inter = {"entry": entry, "presses": 1, "menus": [box_text(tm2)] if is_menu(tm2) else [],
                           "choices": [], "snap": snap_pre, "pos": before}
            extra["sprites"] = sprite_snapshot(ctx.emu)
            extra["trigger"] = True  # a box with no A press is a contact/scripted event, not an interaction
            result += f'; event on contact: "{text[:50]}"'
    fr.result = result
