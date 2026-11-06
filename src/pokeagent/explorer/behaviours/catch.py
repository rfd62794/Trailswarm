"""catch: weaken a wild species we do not own, then throw a POKe BALL (attempts are recorded to learn the odds)."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.behaviours.battle_run import cave_catch_allowed
from pokeagent.explorer.behaviours.item_use import item_list_open, item_step, party_prompt_open
from pokeagent.goals import bag_contents

POKE_BALL = 0x04


class Catch(BehaviourBase):
    name = "catch"

    def applies(self, ctx: ExplorerContext) -> bool:
        return ctx.view.battling and ctx.bv is not None  # also resets catch_mode on every fight step

    def step(self, ctx: ExplorerContext) -> Decision | None:
        lines_now = ctx.view.lines
        bv = ctx.bv
        kind, species, e_lvl, run_line = bv.kind, bv.species, bv.e_lvl, bv.run_line
        # --- catching: a wild species we do not own yet, with a POKe BALL in the bag -> weaken to <=35% HP, then
        #     ITEM -> POKe BALL. Attempts and results (per species, level, HP%) are recorded to learn catch odds.
        balls = bag_contents(ctx.emu).get(0x04, 0)
        dex_no = int((ROM_KB or {}).get("dex_of_internal", {}).get(str(species), 0) or 0)
        owned = bool(dex_no) and bool(ctx.emu.read(0xD2F7 + (dex_no - 1) // 8) >> ((dex_no - 1) % 8) & 1)
        e_hp, e_max = ((ctx.emu.read(0xCFE6) << 8) | ctx.emu.read(0xCFE7)), ((ctx.emu.read(0xCFF4) << 8) | ctx.emu.read(0xCFF5))
        if kind == 1 and balls and dex_no and not owned and e_max and cave_catch_allowed(ctx, species):
            ratio = e_hp / e_max
            if ratio <= 0.35 and (run_line is not None or item_list_open(lines_now) or party_prompt_open(lines_now)):
                ctx.catch_attempt = {"species": species, "level": e_lvl, "hp_pct": round(ratio, 2), "step": ctx.step, "dex": dex_no}
                cur_c = next((ln for ln in lines_now if ">" in ln), "")
                dec = item_step(ctx, lines_now, cur_c, POKE_BALL, "POKe BALL", f"CATCH at {ratio:.0%} HP")
                if dec is not None:
                    if dec.rule == "item_use":  # the A that throws it
                        n = ctx.cave_catch_balls.get(species, 0) + 1
                        ctx.cave_catch_balls[species] = n
                        sp_name = (ROM_KB or {}).get("name_of_internal", {}).get(str(species), species)
                        ctx.log(f"[catch: throwing ball {n} at {sp_name} L{e_lvl} ({ratio:.0%} HP) on map 0x{ctx.view.m:02X}]", "res")
                    return dec
            ctx.catch_mode = True  # weaken, do not KO: the move chooser picks the WEAKEST damaging move
        else:
            ctx.catch_mode = False
        return None
