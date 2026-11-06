"""battle: reading the fight (damage learning), POTION timing, fleeing, and the bookkeeping when it ends.

The catch and move-choice rules that follow in the same fight are the ``catch`` and ``battle_moves`` behaviours;
this one hands them a BattleView (``ctx.bv``) of what it just read.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pokeagent.explorer.grind import record_battle_result
from pokeagent.explorer.battle import enemy_types, move_by_name, norm_name, record_threat, record_type_effect
from pokeagent.explorer.battle_text import battle_events
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.behaviours.item_use import (
    POTION, close_unwanted_list, item_is_blocked, item_step, new_battle, note_screen)
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.perceive import party_hp
from pokeagent.explorer.stat_records import record_catch
from pokeagent.goals import bag_contents, check_goals
from pokeagent.magikarp import fighter
from pokeagent.ramstructs import read_party

PENDING_EFFECT_MAX_STEPS = 90  # a landed attack's result text should arrive well within this


@dataclass
class BattleView:
    """What the battle behaviour read this step, for the behaviours after it."""

    kind: int = 0
    hp: int = 0
    mx: int = 0
    run_line: str | None = None
    species: int = 0
    my_sp: int = 0
    my_lvl: int = 0
    e_lvl: int = 0
    want_potion: bool = False
    cur: str = ""
    threat: float = 0.0  # worst ROM-estimated threat this enemy species has shown


def _record_observed(ctx: ExplorerContext, move: str, observed: str) -> None:
    """Count one result message for our move in the type-effect ledger (super/weak/none)."""
    mv = move_by_name(move)
    if mv is None:
        return
    record_type_effect(ctx.mem.data, mv["type"], enemy_types(ctx.emu), observed, step=ctx.step)
    ctx.fx_last_fx = {"move": move, "effect": observed, "step": ctx.step}


def _finalize_pending_effect(ctx: ExplorerContext) -> None:
    """Our last attack's result window closed with no message: a damaging hit reads neutral."""
    pe = ctx.pending_effect
    if pe is None:
        return
    record_type_effect(ctx.mem.data, pe["move_type"], pe["def_types"], "neutral", step=pe["step"])
    ctx.pending_effect = None


def _unseen(ctx: ExplorerContext, dlg: list) -> list:
    """Dialog entries not parsed yet. A new list object (press.py swaps it when a box reopens) is all new, even
    if its first line repeats the old last one; the same list is matched against the snapshot we scanned, allowing
    for the 12-entry cap having rotated old entries off the front."""
    prev = ctx.fx_seen
    if dlg is ctx.fx_src:
        for shift in range(len(prev)):  # largest overlap first: prev[shift:] is a prefix of dlg
            keep = prev[shift:]
            if dlg[:len(keep)] == keep:
                return dlg[len(keep):]
    ctx.fx_src = dlg
    return list(dlg)


def scan_battle_text(ctx: ExplorerContext) -> None:
    """Parse newly arrived battle text: our moves' results -> type_effect, enemy moves -> threat.

    ctx.dialog is a capped stream of text-box contents (replaced by a new list when a box reopens); fx_src and
    fx_seen are the scan cursor so each entry is parsed once.
    """
    dlg = ctx.dialog
    if not dlg:
        return
    new = _unseen(ctx, dlg)
    ctx.fx_seen = list(dlg)
    blob = " ".join(e.replace(" | ", " ") for e in new)
    for ev in battle_events(blob):
        if ev[0] == "used":
            _finalize_pending_effect(ctx)  # a new attack means the last one's result text is done
            ctx.fx_last = {"side": ev[1], "move": ev[2]}
            if ev[1] == "enemy":
                record_threat(ctx.mem.data, ctx.emu, ctx.emu.read(0xCFE5), ev[2], step=ctx.step)
        elif ev[0] == "effect" and ctx.fx_last and ctx.fx_last["side"] == "ours":
            _record_observed(ctx, ctx.fx_last["move"], ev[1])
            pe = ctx.pending_effect
            if pe and norm_name(pe["move"]) == norm_name(ctx.fx_last["move"]):
                ctx.pending_effect = None  # the real message beat the neutral default


class Battle(BehaviourBase):
    name = "battle"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.battling or ctx.in_battle  # in a fight, or one that just ended (bookkeeping)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        tm_now, lines_now = ctx.view.tm, ctx.view.lines
        if ctx.view.battling:
            if not ctx.in_battle:
                ctx.battles = ctx.battles + 1; ctx.battle_pos = (m, x, y)
                ctx.fx_last = ctx.fx_last_fx = ctx.pending_effect = None  # fresh fight: no carried text state
                new_battle(ctx)
                bflag = ctx.emu.read(0xD057)
                if bflag == 1:  # wild: remember this tile spawns pokemon, and what tile ids grass has
                    under = [tm_now[8 * 20 + 8], tm_now[8 * 20 + 9], tm_now[9 * 20 + 8], tm_now[9 * 20 + 9]]
                    ctx.mem.learn_encounter(m, x, y, ctx.emu.read(0xD367), under)
                    ctx.log(f"[wild encounter at ({x},{y}): grass tile learned]", "res")
                elif bflag == 2:  # trainer battle (verified in the demo): the NPC we faced or that approached is one
                    ctx.trainer_npc = ctx.mem.mark_trainer(m, x, y, ctx.facing)
                    if ctx.trainer_npc is not None:
                        ctx.log(f"[trainer battle: NPC pic {ctx.trainer_npc['pic']} marked trainer]", "res")
            ctx.in_battle = True
            ctx.box_streak = 0
            scan_battle_text(ctx)
            if ctx.pending_effect and ctx.step - ctx.pending_effect["step"] > PENDING_EFFECT_MAX_STEPS:
                _finalize_pending_effect(ctx)  # the result text never came: count the hit neutral
            kind = ctx.emu.read(0xD057)
            hp, mx = party_hp(ctx.emu)
            weak = mx > 0 and hp / mx < 0.4
            run_line = next((ln for ln in lines_now if "RUN" in ln), None)
            # --- learn the opponent's damage: HP drop since our last battle decision, per enemy species ---
            species = ctx.emu.read(0xCFE5)
            my_sp, my_lvl = fighter(ctx.emu)[:2]; e_lvl = ctx.emu.read(0xCFF3)
            if ctx.last_battle_hp is not None and hp < ctx.last_battle_hp:
                taken = ctx.last_battle_hp - hp
                dmg = ctx.mem.data.setdefault("enemy_damage", {}).setdefault(str(species), [])
                dmg.append(taken); del dmg[:-20]
                # Full-context record (Robert): which enemy move, at which levels, did how much to which of ours.
                m_used = re.search(r"used ([A-Z][A-Z ]+?)!", " ".join(ctx.dialog[-3:]))
                emove = m_used.group(1).strip() if m_used else "?"
                key = f"{species}L{e_lvl}:{emove}->{my_sp}L{my_lvl}"
                rec = ctx.mem.data.setdefault("damage_taken", {}).setdefault(key, [])
                rec.append(taken); del rec[:-20]
            ctx.last_battle_hp = hp
            expected = max(ctx.mem.data.get("enemy_damage", {}).get(str(species), [0]) or [0])
            threat = ctx.mem.data.get("threat_by_species", {}).get(str(species), {}).get("score", 0.0)
            # --- potion timing: use one when the next expected hit could take us below ~1 hit of safety and the heal
            #     is not wasted (POTION restores 20 HP in Gen 1; the observed heal is learned into item_heal) ---
            heal = max(ctx.mem.data.get("item_heal", {}).get("20", [20]) or [20])
            has_potion = bag_contents(ctx.emu).get(0x14, 0) > 0
            note_screen(ctx, lines_now, POTION)
            want_potion = (has_potion and mx and hp <= max(expected * 2, 6) and (mx - hp) >= min(heal, 12) and kind != 0
                           and not item_is_blocked(ctx, POTION))
            cur = next((ln for ln in lines_now if ">" in ln), "")
            if want_potion:
                ctx.potion_hp_before = hp
                dec = item_step(ctx, lines_now, cur, POTION, "POTION", f"BATTLE HP {hp}/{mx}, enemy hits up to {expected}")
                if dec is not None:
                    return dec
            else:
                dec = close_unwanted_list(ctx, lines_now)
                if dec is not None:
                    return dec
            if ctx.potion_hp_before is not None and hp > ctx.potion_hp_before:
                ctx.mem.data.setdefault("item_heal", {}).setdefault("20", []).append(hp - ctx.potion_hp_before)
                ctx.log(f"[POTION healed {hp - ctx.potion_hp_before} HP: learned]", "res"); ctx.potion_hp_before = None
            # On the road to Pewter after the parcel, wild fights cost 25+ presses each and a to_pewter run only has 1800
            # (2026-11-03: 30-50% of the Forest presses were battle text): run unless a ball could catch it.
            gn = check_goals(ctx.emu, ctx)
            hurry = (gn.get("deliver_parcel") and not gn.get("to_pewter") and ctx.emu.read(0xD35E) in (0x0D, 0x33)
                     and not (bag_contents(ctx.emu).get(0x04, 0) and ctx.emu.read(0xCFE5)))
            if kind == 1 and (weak or hurry) and run_line is not None:  # wild battle and too weak (or in a hurry): flee
                tnote = f", threat {threat:g}" if weak and threat else ""
                if ">RUN" in run_line:
                    return Decision("A", "flee_run", f"BATTLE wild, HP {hp}/{mx}: RUN{tnote}")
                cur = next((ln for ln in lines_now if ">" in ln), "")
                if "FIGHT" in cur or "PKMN" in cur:
                    return Decision("DOWN", "flee_down", f"BATTLE wild, HP {hp}/{mx}: moving the cursor down toward RUN{tnote}")
                if "ITEM" in cur:
                    return Decision("RIGHT", "flee_right", f"BATTLE wild, HP {hp}/{mx}: moving the cursor right to RUN{tnote}")
            ctx.bv = BattleView(kind, hp, mx, run_line, species, my_sp, my_lvl, e_lvl, bool(want_potion), cur, threat)
            return None
        if ctx.in_battle:
            ctx.in_battle = False; ctx.last_battle_hp = None; ctx.potion_hp_before = None
            ctx.no_pp = set(); ctx.all_pp_out = 0; ctx.last_move_choice = None
            _finalize_pending_effect(ctx)  # the fight ended before any result text: the hit reads neutral
            ca = ctx.pop("catch_attempt")
            if ca:  # resolved at the END of the battle, against the species we threw at (not the next enemy)
                dn = ca.get("dex") or 0
                caught = bool(dn) and bool(ctx.emu.read(0xD2F7 + (dn - 1) // 8) >> ((dn - 1) % 8) & 1)
                ctx.mem.data.setdefault("catches", []).append({**{k: v for k, v in ca.items() if k != "dex"}, "caught": caught}); del ctx.mem.data["catches"][:-100]
                ctx.log(f"[catch attempt {'SUCCEEDED' if caught else 'failed'} vs #{ca['species']} L{ca['level']} at {ca['hp_pct']:.0%}]", "res")
                try:  # record-only: a decode failure must never end a run
                    rec = record_catch(ctx.mem.data, read_party(ctx.emu), ca["species"], ctx.step) if caught else None
                except Exception as exc:
                    rec = None; ctx.log(f"[dv record skipped: {exc}]", "res")
                if rec and rec["duplicate"]:  # keep-best is report-only: no box juggling yet
                    ctx.log(f"[duplicate #{ca['species']}: best DVs in party slot {rec['prefer_slot'] + 1}]", "res")
            # Won = still standing where the battle happened with a Pokemon in the party; a loss warps you home.
            won = ctx.emu.read(0xD163) > 0 and (m, x, y) == ctx.battle_pos  # a blackout warps you away
            if won and ctx.trainer_npc is not None:
                ctx.trainer_npc["beaten"] = True
                ctx.log(f"[trainer beaten: NPC pic {ctx.trainer_npc['pic']}]", "res")
            ctx.trainer_npc = None
            ctx.battles_won = ctx.battles_won + (1 if won else 0)
            record_battle_result(ctx, won=won, moved_away=ctx.emu.read(0xD163) > 0 and (m, x, y) != ctx.battle_pos)
            ctx.log(f"[battle over - {'WON' if won else 'lost?'}; {ctx.battles} battles this run]", "res")
            bl = ctx.pop("battle_log")
            if bl:  # one record per battle: who, choices per turn with HP, result - the data for battle strategy
                hp_end, mx_end = party_hp(ctx.emu)
                bl.update({"end": ctx.step, "won": won, "run": ctx.run_dir.name, "map": m, "presses": ctx.step - bl["start"],
                           "hp_end": [hp_end, mx_end], "fled": not won and hp_end > 0})
                with Path("runs/battles.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(bl) + "\n")
                # Every battle is a lesson: per enemy species keep fights/wins/fled, HP lost, turns, and the move that
                # actually did the most damage. The planner reads these to pick fights and set the flee threshold.
                sp = str(bl.get("enemy_species") or ctx.emu.read(0xCFE5))
                ls = ctx.mem.data.setdefault("battle_lessons", {}).setdefault(sp, {"fights": 0, "wins": 0, "fled": 0, "turns": [], "hp_lost": []})
                ls["fights"] += 1; ls["wins"] += int(won); ls["fled"] += int(bl["fled"])
                ls["turns"].append(len(bl["turns"])); del ls["turns"][:-20]
                first = bl["turns"][0]["hp_you"] if bl["turns"] else hp_end
                ls["hp_lost"].append(max(0, first - hp_end)); del ls["hp_lost"][:-20]
                dmg = {k.split(":")[1]: round(sum(v) / len(v), 1) for k, v in ctx.mem.data.get("move_damage", {}).items() if k.startswith(sp + ":") and v}
                if dmg:
                    ls["best_move"] = max(dmg, key=dmg.get); ls["move_avg_damage"] = dmg
                ename = (ROM_KB or {}).get("name_of_internal", {}).get(sp, f"#{sp}")
                ctx.log(f"[lesson vs {ename}: {ls['wins']}/{ls['fights']} won, fled {ls['fled']}, avg turns {sum(ls['turns']) / len(ls['turns']):.1f}, "
                    f"avg HP lost {sum(ls['hp_lost']) / len(ls['hp_lost']):.1f}, best move {ls.get('best_move', '?')}]", "res")
        return None

    def done(self, ctx: ExplorerContext) -> bool:
        return not ctx.view.battling and not ctx.in_battle
