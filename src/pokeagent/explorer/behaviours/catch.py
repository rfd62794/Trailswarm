"""catch: weaken a wild species we do not own, then throw a POKe BALL (attempts are recorded to learn the odds)."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.kb import ROM_KB
from pokeagent.goals import bag_contents


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
        if kind == 1 and balls and dex_no and not owned and e_max:
            ratio = e_hp / e_max
            if ratio <= 0.35 and (run_line is not None or any("BALL" in ln for ln in lines_now)):
                ctx.catch_attempt = {"species": species, "level": e_lvl, "hp_pct": round(ratio, 2), "step": ctx.step, "dex": dex_no}
                cur_c = next((ln for ln in lines_now if ">" in ln), "")
                if any("BALL" in ln and ">" in ln for ln in lines_now):
                    return Decision("A", "catch_throw", f"CATCH {ROM_KB['name_of_internal'].get(str(species), species)} at {ratio:.0%} HP: throwing a POKe BALL")
                if any("BALL" in ln for ln in lines_now):
                    return Decision("DOWN", "catch_item_list_down", "item list: moving to POKe BALL")
                if ">ITEM" in cur_c:
                    return Decision("A", "catch_open_item", "opening ITEM for a POKe BALL")
                if "FIGHT" in cur_c or "PKMN" in cur_c:
                    return Decision("DOWN", "catch_menu_down", "battle menu: down to ITEM (catching)")
                if "RUN" in cur_c:
                    return Decision("LEFT", "catch_menu_left", "battle menu: left to ITEM (catching)")
            ctx.catch_mode = True  # weaken, do not KO: the move chooser picks the WEAKEST damaging move
        else:
            ctx.catch_mode = False
        return None
