"""heal: the Mom-heal loop guard. If we talked to her and HP did not rise, stop going back for a while."""
from __future__ import annotations

from pokeagent.explorer.behaviours.base import BehaviourBase, Decision
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.perceive import party_hp


class Heal(BehaviourBase):
    name = "heal"

    def applies(self, ctx: ExplorerContext) -> bool:
        return bool(ctx.mom_talk_step)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        hp_now, mx_now = party_hp(ctx.emu)
        if ctx.mom_talk_step and ctx.step - ctx.mom_talk_step > 6:
            if hp_now <= ctx.mom_talk_hp and mx_now and hp_now / mx_now < 0.4:
                ctx.mom_failed_until = ctx.step + 150
                ctx.log(f"[Mom did not heal us (HP {hp_now}/{mx_now}); not retrying for 150 steps]", "res")
            else:
                ctx.log(f"[healed at Mom: HP {hp_now}/{mx_now}]", "res")
                ctx.proc_due.extend(n for n in ("check_health", "open_bag", "save_game") if n not in ctx.proc_done)
                ctx.proc_done.update({"check_health", "open_bag", "save_game"})
            ctx.mom_talk_step = None
        return None

    def failed(self, ctx: ExplorerContext) -> bool:
        return ctx.mom_failed_until > ctx.step  # Mom did not heal us: not retrying for a while
