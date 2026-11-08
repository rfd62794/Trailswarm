"""switch_out: switch_out_lead. The Magikarp leads into every fight and is swapped for the strongest healthy member on turn one.

Gen 1 splits a battle's experience among every Pokemon that TOOK PART, so a Magikarp that is sent out and swapped
straight back still earns its share. Runs after the battle behaviour: a wild fight the agent decides to flee from is
already answered there (RUN with the Magikarp still out), so the flee rule wins; in a trainer fight (no fleeing) the swap
always happens. Never switches into a fainted or sub-25%-HP member (magikarp.switch_candidate); with nobody fit to send
in, the fight goes on as usual.
"""
from __future__ import annotations

import re

from dataclasses import replace

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.party_menu import MENU_ITEM, screen_lines, toward
from pokeagent.explorer.perceive import TILEMAP, TILEMAP_LEN, frame_lines
from pokeagent.explorer.behaviours.party_order import species_names
from pokeagent.explorer.kb import ROM_KB
from pokeagent.knowledge import team_plan
from pokeagent.knowledge.party import our_party, trainer_mon
from pokeagent.knowledge.readiness import best_move
from pokeagent.magikarp import MAGIKARP, MAX_RUNS, party_species, switch_candidate, trainee_slot_for
from pokeagent.ramstructs import read_battle_mon, read_enemy_mon, read_party

MAX_PRESSES = 30  # a switch is about 6 presses; past this the menus are not what we think: fight on


def trainee_out(ctx: ExplorerContext) -> int | None:
    """Party slot of the switch-trainee actually out in this battle, else None. The active mon only counts when its
    own party_pos AND species agree with the trainee slot (a Magikarp party: identical to the old species match).
    The trainee slot is the exp-spread rotation's pick: a named weak member or the lowest band breaker, never only
    the Magikarp (team_plan.of(ctx)["breakers"] is published by plan_goal each step)."""
    t = trainee_slot_for(ctx.emu, ctx.train_member, team_plan.of(ctx).get("breakers") or ())
    if t is None:
        return None
    b, sp = read_battle_mon(ctx.emu), party_species(ctx.emu)
    return t if b.party_pos == t and t < len(sp) and b.species == sp[t] else None


def _foe(ctx: ExplorerContext):
    """The enemy Combatant at its CURRENT hp for the matchup maths, else None (no ROM data)."""
    e = read_enemy_mon(ctx.emu)
    name = (ROM_KB or {}).get("name_of_internal", {}).get(str(e.species))
    foe = trainer_mon(name, e.level) if name else None
    return replace(foe, hp=max(1, e.hp)) if foe is not None else None


def matchup_pick(ctx: ExplorerContext) -> tuple[int, str] | None:
    """(slot, why) of team_plan.switch_choice for this TRAINER battle, or None: the active member is
    "thin" (the foe's best hit over SWITCH_HP_TURNS turns meets or beats its HP, or its best move does
    <= WEAK_RATIO of the foe's HP) and a healthy member beats its damage ratio by SWITCH_GAIN.
    Cached on (step, battle): applies() and _matchup_step ask the same question twice a step and the
    our_party + best_move sims are not free."""
    st = team_plan.of(ctx)
    key = (getattr(ctx, "step", -1), getattr(ctx, "battles", -1))
    if st.get("mu_pick_key") != key:
        st["mu_pick_key"], st["mu_pick"] = key, _matchup_pick(ctx)
    return st["mu_pick"]


def _matchup_pick(ctx: ExplorerContext) -> tuple[int, str] | None:
    """The uncached pick for this step (see matchup_pick)."""
    bv = ctx.bv
    if bv is None or getattr(bv, "kind", None) != 2:  # a wild battle (1), or a view stub without a kind
        return None
    bl = ctx.battle_log or {}
    n_sw = bl.get("matchup_switches", 0)
    party, foe = our_party(ctx.emu), _foe(ctx)
    b = read_battle_mon(ctx.emu)
    if not party or foe is None or not (0 <= b.party_pos < len(party)):
        return None
    hp_now = [m.hp for m in read_party(ctx.emu)]
    pick = team_plan.switch_choice(party, b.party_pos, foe, None, hp_now=hp_now, switches=n_sw,
                                   trainee=trainee_slot_for(ctx.emu, ctx.train_member))
    if pick is None:
        return None
    from pokeagent.knowledge.kb import table
    chart = {(a, d): e for a, d, e in table(None, "type_chart")}
    moves, active = table(None, "moves"), party[b.party_pos]
    cur = hp_now[b.party_pos] if b.party_pos < len(hp_now) else active.hp
    inc = best_move(foe, active, chart, moves)[0]
    why = (f"thin: foe hits {inc:.0f}x{team_plan.SWITCH_HP_TURNS} vs {cur} HP" if inc * team_plan.SWITCH_HP_TURNS >= cur
           else f"weak: best hit <= {team_plan.WEAK_RATIO:.0%} of foe")
    return pick, why


def switch_press(frames: list[str], screen: list[str], cur: int, target: int) -> str | None:
    """Next button of PKMN -> member -> SWITCH. `frames` are the framed rows (battle menu / submenu), `screen` all rows.

    None when neither the battle menu nor a party screen is up (a text box is scrolling: let it finish).
    """
    text = " | ".join(screen)
    if re.search(r"Move POK.*where", text, re.I):
        return None
    if "SWITCH" in text and "STATS" in text:
        row = next((i for i, r in enumerate(ln for ln in frames if re.search(r"SWITCH|STATS|CANCEL", ln)) if "SWITCH" in r), 1)
        return toward(cur, row)
    if re.search(r"Choose a POK|Bring out", text, re.I):
        return toward(cur, target)
    joined = " ".join(frames)
    if "FIGHT" in joined and "PKMN" in joined:  # the battle menu: FIGHT PKMN / ITEM RUN, cursor somewhere in it
        if re.search(r">\s*PKMN", joined):
            return "A"
        return "RIGHT" if re.search(r">\s*FIGHT", joined) else "UP"  # ITEM/RUN sit under FIGHT/PKMN
    return None


def run_press(frames: list[str]) -> str | None:
    """Next button toward RUN on the battle menu (FIGHT PKMN / ITEM RUN), None when it is not on screen."""
    joined = " ".join(frames)
    if "FIGHT" not in joined or "RUN" not in joined:
        return None
    if re.search(r">\s*RUN", joined):
        return "A"
    return "RIGHT" if re.search(r">\s*ITEM", joined) else "DOWN"  # FIGHT -> ITEM -> RUN, PKMN -> RUN


class SwitchOut(BehaviourBase):
    name = "switch_out"

    def applies(self, ctx: ExplorerContext) -> bool:
        if not ctx.view.battling or ctx.bv is None or ctx.switch_gave_up == ctx.battles:
            return False
        st = team_plan.of(ctx)
        return (ctx.switch_train is not None or trainee_out(ctx) is not None
                or st.get("matchup") is not None or matchup_pick(ctx) is not None)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        sw = ctx.switch_train
        t = trainee_out(ctx)
        if t is None:
            if sw is not None:
                ctx.magikarp_shared += 1
                ctx.log(f"[{sw['rule']}: done after {sw['presses']} presses (Magikarp shared {ctx.magikarp_shared} battles)]", "res")
                ctx.switch_train = None
            return self._matchup_step(ctx)
        target = switch_candidate(ctx.emu, t)
        tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
        if target is None:
            # Nobody fit to send in. A Magikarp only knows SPLASH: leave a wild fight (the first sighting is logged once),
            # a trainer fight cannot be left, so it carries on as before.
            if ctx.emu.read(0xD057) == 1 and party_species(ctx.emu)[t] == MAGIKARP:  # only a Magikarp is useless: a fighter trainee never flees
                wild_run = run_press(frame_lines(tm))
                if wild_run is None:
                    return None
                n = ctx.switch_runs[1] + 1 if ctx.switch_runs[0] == ctx.battles else 1
                if wild_run == "A":  # an A on RUN is an attempt; the cursor walk before it is free
                    ctx.switch_runs = (ctx.battles, n)
                    if n > MAX_RUNS:
                        ctx.switch_gave_up = ctx.battles
                        ctx.log(f"[switch_train_run: RUN failed {MAX_RUNS} times this battle - fighting on]", "res")
                        return None
                    ctx.log(f"[switch_train_run: RUN attempt {n}/{MAX_RUNS}]", "res")
                return Decision(wild_run, "switch_train_run", "switch_train: nobody healthy to send in, SPLASH is useless: RUN")
            if ctx.switch_gave_up != ctx.battles:
                ctx.switch_gave_up = ctx.battles
                ctx.log("[switch_train: nobody healthy enough to send in; fighting on]", "res")
            return None
        btn = switch_press(frame_lines(tm), screen_lines(tm), ctx.emu.read(MENU_ITEM), target)
        if btn is None:
            return None  # text scrolling / animation: the usual dialog handling runs
        if sw is None:
            names = species_names(ctx.emu)
            who = "MAGIKARP" if t < len(names) and party_species(ctx.emu)[t] == MAGIKARP else names[t]
            rule = f"switch_train: {who} L{read_battle_mon(ctx.emu).level} -> out, {names[target]} in"
            sw = ctx.switch_train = {"rule": rule, "presses": 0}
        sw["presses"] += 1
        if sw["presses"] > MAX_PRESSES:
            ctx.switch_gave_up = ctx.battles; ctx.switch_train = None
            ctx.log("[switch_train: gave up (menus did not behave); fighting with the Magikarp]", "res")
            return Decision("B", "switch_train_failed", "switch_train abandoned: backing out of the menu")
        return Decision(btn, sw["rule"], f"{sw['rule']} (press {sw['presses']})")

    def _matchup_step(self, ctx: ExplorerContext) -> Decision | None:
        """The matchup switch in a trainer battle: PKMN -> the better member -> SWITCH, once per
        decision, the per-battle count kept on the battle record (team_plan.MAX_SWITCHES_PER_BATTLE)."""
        st = team_plan.of(ctx)
        b = read_battle_mon(ctx.emu)
        mu = st.get("matchup")
        if mu and mu.get("battle") != ctx.battles:
            mu = None; st.pop("matchup", None)
        if mu and b.party_pos == mu["target"]:  # the swap landed
            if ctx.battle_log is not None:
                ctx.battle_log["matchup_switches"] = ctx.battle_log.get("matchup_switches", 0) + 1
            ctx.log(f"[{mu['rule']}: done after {mu['presses']} presses]", "res")
            st.pop("matchup", None)
            return None
        tm = ctx.emu.read_range(TILEMAP, TILEMAP_LEN)
        pick = (mu["target"], mu["why"]) if mu else matchup_pick(ctx)
        if pick is None:
            return None
        btn = switch_press(frame_lines(tm), screen_lines(tm), ctx.emu.read(MENU_ITEM), pick[0])
        if btn is None:
            return None  # text scrolling / animation: the usual dialog handling runs
        if mu is None:
            names = species_names(ctx.emu)
            who = names[b.party_pos] if 0 <= b.party_pos < len(names) else "?"
            mu = st["matchup"] = {"battle": ctx.battles, "target": pick[0], "presses": 0, "why": pick[1],
                                  "rule": f"switch_matchup: {who} -> {names[pick[0]]} ({pick[1]})"}
        mu["presses"] += 1
        if mu["presses"] > MAX_PRESSES:
            ctx.switch_gave_up = ctx.battles; st.pop("matchup", None)
            ctx.log("[switch_matchup: gave up (menus did not behave); fighting on]", "res")
            return Decision("B", "switch_matchup_failed", "switch_matchup abandoned: backing out of the menu")
        return Decision(btn, mu["rule"], f"{mu['rule']} (press {mu['presses']})")
