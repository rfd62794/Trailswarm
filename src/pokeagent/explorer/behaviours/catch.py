"""catch: a wild species we do not own -> the catch policy's step (weaken / status / switch / throw).

The policy (knowledge.catch_policy) decides through ``ctx.catch_hint``: a status_move or damage_move is
picked by battle_moves, a switch is pressed through switch_out's helper, a throw uses ITEM -> the hinted
ball. The original rule (a POKE BALL at <=35% HP) stays as the fallback for when there is no ROM data to
decide with (catch_hint is None), and attempts are recorded to learn the odds.
"""
from __future__ import annotations

from dataclasses import replace

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.behaviours.battle_run import cave_catch_allowed
from pokeagent.explorer.behaviours.item_use import item_list_open, item_step
from pokeagent.explorer.behaviours.switch_out import switch_press
from pokeagent.explorer.catch_list import catch_wanted, dex_owned_count, upcoming_needs
from pokeagent.explorer.party_menu import MENU_ITEM, screen_lines
from pokeagent.explorer.perceive import frame_lines
from pokeagent.goals import bag_contents
from pokeagent.knowledge.catch_math import BALLS, FALLBACK_PRICE, status_kind
from pokeagent.knowledge.catch_policy import decide, may_throw_ctx
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import our_party, species_row, trainer_mon
from pokeagent.ramstructs import read_battle_mon, read_enemy_mon

POKE_BALL = 0x04
BALL_NAME = {"POKE": "POKe BALL", "GREAT": "GREAT BALL", "ULTRA": "ULTRA BALL", "MASTER": "MASTER BALL"}


def _policy_hint(ctx: ExplorerContext, sp_name: str, e_lvl: int, e_hp: int, e_max: int,
                 bag: dict[int, int], turn: int):
    """The catch policy's CatchStep for this step, or None when there is no ROM data to decide with."""
    party = our_party(ctx.emu)
    wild = trainer_mon(sp_name, e_lvl)
    if not party or wild is None:
        return None
    pos = read_battle_mon(ctx.emu).party_pos
    active = party[pos] if 0 <= pos < len(party) else party[0]
    items = (ROM_KB or {}).get("items", {})
    price = {name: int((items.get(str(i)) or {}).get("price") or FALLBACK_PRICE.get(name, 200))
             for name, i in BALLS.items()}
    rate = int((species_row(sp_name) or {}).get("catch_rate") or 0)
    return decide(active, party, replace(wild, hp=max(1, e_hp)), e_hp, e_max,
                  status_kind(read_enemy_mon(ctx.emu).status), rate,
                  {name: bag.get(i, 0) for name, i in BALLS.items()}, price,
                  {(a, d): e for a, d, e in table(None, "type_chart")}, table(None, "moves"), turn=turn,
                  kind=ctx.bv.kind, trainer_npc=ctx.trainer_npc,
                  battle_log_kind=(ctx.battle_log or {}).get("kind"))


class Catch(BehaviourBase):
    name = "catch"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.battling and ctx.bv is not None  # also resets catch_mode on every fight step

    def step(self, ctx: ExplorerContext) -> Decision | None:
        lines_now = ctx.view.lines
        bv = ctx.bv
        kind, species, e_lvl, run_line = bv.kind, bv.species, bv.e_lvl, bv.run_line
        # --- catching: a wild species we do not own yet, with a ball in the bag -> the catch policy decides;
        #     the throw itself is ITEM -> the hinted ball. Attempts and results are recorded to learn catch odds.
        bag = bag_contents(ctx.emu)
        balls = sum(bag.get(i, 0) for i in BALLS.values())
        dex_no = int((ROM_KB or {}).get("dex_of_internal", {}).get(str(species), 0) or 0)
        owned = bool(dex_no) and bool(ctx.emu.read(0xD2F7 + (dex_no - 1) // 8) >> ((dex_no - 1) % 8) & 1)
        e_hp, e_max = ((ctx.emu.read(0xCFE6) << 8) | ctx.emu.read(0xCFE7)), ((ctx.emu.read(0xCFF4) << 8) | ctx.emu.read(0xCFF5))
        want = sp_name = None
        if kind == 1 and balls and dex_no and e_max and cave_catch_allowed(ctx, species):
            sp_name = (ROM_KB or {}).get("name_of_internal", {}).get(str(species), str(species))
            key = (ctx.battles, species)
            if ctx.catch_want[0] != key:  # decided once per fight: the party read is not free
                why = catch_wanted(sp_name, our_party(ctx.emu), dex_owned_count(ctx.emu), upcoming_needs(ctx.goals()),
                                   owned=owned, wants=ctx.team_wants)
                ctx.catch_want = (key, why)
                ctx.log(f"[catch: {'wanted' if why else 'skipping'} {sp_name}: {why or 'not on the need-list'}]", "res")
            want = ctx.catch_want[1]
        if not (want and balls and dex_no and e_max and may_throw_ctx(ctx)
                and (not owned or want.startswith(("can learn", "planned")))):
            ctx.catch_mode = False
            ctx.catch_hint = None
            return None
        ratio = e_hp / e_max
        # A policy turn = one change of the situation signature (a hit landed, a status stuck, a switch or
        # a throw went through, our move was chosen); menu-walking steps between actions are not turns.
        enemy = read_enemy_mon(ctx.emu)
        key = ctx.catch_want[0]
        sig = (e_hp, enemy.status, bv.my_sp, balls, id(ctx.pending_move), id(ctx.catch_attempt))
        prev = ctx.catch_turns
        turn = prev[2] if prev[0] == key else 0
        if prev[0] != key or prev[1] != sig:
            turn += 1
        ctx.catch_turns = (key, sig, turn)
        hint = _policy_hint(ctx, sp_name, e_lvl, e_hp, e_max, bag, turn)
        ctx.catch_hint = hint
        ctx.catch_mode = hint is None or hint.kind != "skip"  # a skip means fight it out normally
        if hint is not None and hint.kind == "throw":
            if run_line is None and not item_list_open(lines_now):
                return None
            ball_id = BALLS.get(hint.ball, POKE_BALL)           # unknown names fall back to the Poke Ball
            ball_name = BALL_NAME.get(hint.ball, "POKe BALL")
            ctx.catch_attempt = {"species": species, "level": e_lvl, "hp_pct": round(ratio, 2),
                                 "step": ctx.step, "dex": dex_no, "ball": hint.ball}
            cur_c = next((ln for ln in lines_now if ">" in ln), "")
            dec = item_step(ctx, lines_now, cur_c, ball_id, ball_name,
                            f"CATCH {hint.ball or 'POKE'} at {ratio:.0%} HP (p={hint.p:.2f})")
            if dec is not None:
                if dec.rule == "item_use":  # the A that throws it
                    n = ctx.cave_catch_balls.get(species, 0) + 1
                    ctx.cave_catch_balls[species] = n
                    ctx.log(f"[catch: throwing {ball_name} {n} at {sp_name} L{e_lvl} ({ratio:.0%} HP) on map 0x{ctx.view.m:02X}]", "res")
                return dec
            return None
        if hint is not None and hint.kind == "switch":
            btn = switch_press(frame_lines(ctx.view.tm), screen_lines(ctx.view.tm),
                               ctx.emu.read(MENU_ITEM), hint.slot)
            if btn is not None:
                return Decision(btn, "catch_switch", f"catch: {hint.why}")
            return None
        if hint is None and ratio <= 0.35 and (run_line is not None or item_list_open(lines_now)):
            # No ROM data for the policy (catch_hint is None): the original rule - a POKE BALL at <=35% HP.
            # A ball throw never opens a party prompt.
            ctx.catch_attempt = {"species": species, "level": e_lvl, "hp_pct": round(ratio, 2), "step": ctx.step, "dex": dex_no}
            cur_c = next((ln for ln in lines_now if ">" in ln), "")
            dec = item_step(ctx, lines_now, cur_c, POKE_BALL, "POKe BALL", f"CATCH at {ratio:.0%} HP")
            if dec is not None:
                if dec.rule == "item_use":  # the A that throws it
                    n = ctx.cave_catch_balls.get(species, 0) + 1
                    ctx.cave_catch_balls[species] = n
                    ctx.log(f"[catch: throwing ball {n} at {sp_name} L{e_lvl} ({ratio:.0%} HP) on map 0x{ctx.view.m:02X}]", "res")
                return dec
        return None
