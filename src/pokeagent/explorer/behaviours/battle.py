"""battle: reading the fight (damage learning), POTION timing, fleeing, and the bookkeeping when it ends.

The catch and move-choice rules that follow in the same fight are the ``catch`` and ``battle_moves`` behaviours;
this one hands them a BattleView (``ctx.bv``) of what it just read.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.perceive import party_hp
from pokeagent.goals import bag_contents, check_goals


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
            kind = ctx.emu.read(0xD057)
            hp, mx = party_hp(ctx.emu)
            weak = mx > 0 and hp / mx < 0.4
            run_line = next((ln for ln in lines_now if "RUN" in ln), None)
            # --- learn the opponent's damage: HP drop since our last battle decision, per enemy species ---
            species = ctx.emu.read(0xCFE5)
            my_sp, my_lvl, e_lvl = ctx.emu.read(0xD16B), ctx.emu.read(0xD18C), ctx.emu.read(0xCFF3)
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
            # --- potion timing: use one when the next expected hit could take us below ~1 hit of safety and the heal
            #     is not wasted (POTION restores 20 HP in Gen 1; the observed heal is learned into item_heal) ---
            heal = max(ctx.mem.data.get("item_heal", {}).get("20", [20]) or [20])
            has_potion = bag_contents(ctx.emu).get(0x14, 0) > 0
            want_potion = has_potion and mx and hp <= max(expected * 2, 6) and (mx - hp) >= min(heal, 12) and kind != 0
            cur = next((ln for ln in lines_now if ">" in ln), "")
            if want_potion and (run_line is not None or any("POTION" in ln for ln in lines_now) or "which" in " ".join(lines_now).lower()):
                ctx.potion_hp_before = hp
                if any("POTION" in ln and ">" in ln for ln in lines_now):
                    return Decision("A", "potion_use", f"BATTLE HP {hp}/{mx}, enemy hits up to {expected}: using POTION (+{heal})")
                if any("POTION" in ln for ln in lines_now):
                    return Decision("DOWN", "potion_item_list_down", "item list: moving to POTION")
                if ">ITEM" in cur:
                    return Decision("A", "potion_open_item", f"BATTLE HP {hp}/{mx}: opening ITEM for a POTION")
                if "FIGHT" in cur or "PKMN" in cur:
                    return Decision("DOWN", "potion_menu_down", "battle menu: down to ITEM")
                if "RUN" in cur:
                    return Decision("LEFT", "potion_menu_left", "battle menu: left to ITEM")
                return Decision("A", "potion_confirm", "item use: confirming")
            if ctx.potion_hp_before is not None and hp > ctx.potion_hp_before:
                ctx.mem.data.setdefault("item_heal", {}).setdefault("20", []).append(hp - ctx.potion_hp_before)
                ctx.log(f"[POTION healed {hp - ctx.potion_hp_before} HP: learned]", "res"); ctx.potion_hp_before = None
            # On the road to Pewter after the parcel, wild fights cost 25+ presses each and a to_pewter run only has 1800
            # (2026-11-03: 30-50% of the Forest presses were battle text): run unless a ball could catch it.
            gn = check_goals(ctx.emu, ctx)
            hurry = (gn.get("deliver_parcel") and not gn.get("to_pewter") and ctx.emu.read(0xD35E) in (0x0D, 0x33)
                     and not (bag_contents(ctx.emu).get(0x04, 0) and ctx.emu.read(0xCFE5)))
            if kind == 1 and (weak or hurry) and run_line is not None:  # wild battle and too weak (or in a hurry): flee
                if ">RUN" in run_line:
                    return Decision("A", "flee_run", f"BATTLE wild, HP {hp}/{mx}: RUN")
                cur = next((ln for ln in lines_now if ">" in ln), "")
                if "FIGHT" in cur or "PKMN" in cur:
                    return Decision("DOWN", "flee_down", f"BATTLE wild, HP {hp}/{mx}: moving the cursor down toward RUN")
                if "ITEM" in cur:
                    return Decision("RIGHT", "flee_right", f"BATTLE wild, HP {hp}/{mx}: moving the cursor right to RUN")
            ctx.bv = BattleView(kind, hp, mx, run_line, species, my_sp, my_lvl, e_lvl, bool(want_potion), cur)
            return None
        if ctx.in_battle:
            ctx.in_battle = False; ctx.last_battle_hp = None; ctx.potion_hp_before = None
            ctx.no_pp = set(); ctx.all_pp_out = 0; ctx.last_move_choice = None
            ca = ctx.pop("catch_attempt")
            if ca:  # resolved at the END of the battle, against the species we threw at (not the next enemy)
                dn = ca.get("dex") or 0
                caught = bool(dn) and bool(ctx.emu.read(0xD2F7 + (dn - 1) // 8) >> ((dn - 1) % 8) & 1)
                ctx.mem.data.setdefault("catches", []).append({**{k: v for k, v in ca.items() if k != "dex"}, "caught": caught}); del ctx.mem.data["catches"][:-100]
                ctx.log(f"[catch attempt {'SUCCEEDED' if caught else 'failed'} vs #{ca['species']} L{ca['level']} at {ca['hp_pct']:.0%}]", "res")
            # Won = still standing where the battle happened with a Pokemon in the party; a loss warps you home.
            won = ctx.emu.read(0xD163) > 0 and (m, x, y) == ctx.battle_pos  # a blackout warps you away
            if won and ctx.trainer_npc is not None:
                ctx.trainer_npc["beaten"] = True
                ctx.log(f"[trainer beaten: NPC pic {ctx.trainer_npc['pic']}]", "res")
            ctx.trainer_npc = None
            ctx.battles_won = ctx.battles_won + (1 if won else 0)
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
