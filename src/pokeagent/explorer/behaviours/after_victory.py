"""after_victory: ONE decision per TRAINER win - push on, drink a Potion, walk to a Pokecenter, or carry on.

Registered right after the battle behaviours; it never presses anything in battle and never changes move
choice. It only DECIDES (procedures.after_victory_rules.decide), logs one line, and sets an intent the
existing behaviours already honour: ``potion`` primes the ledger's field-potion cache that
``outside_use.field_wants`` / CaveTopUp read; ``heal`` requests a real walk to the nurse
(``heal_walk.start``, carried out by StatusCare, which runs before PlanGoal) - ``ctx.center_intent`` cannot
carry it, PlanGoal clears that on the road. The decision is stored on ``of(ctx)["victory"]`` for the
ProcedureRunner and appended (without any ROM data) to the run dir's after_victory.jsonl. A wild win never
reaches this behaviour: battle bookkeeping records trainer wins in ``of(ctx)["twins"]``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace

from pokeagent.explorer import heal_walk
from pokeagent.explorer.behaviours.base import BehaviourBase, Decision, no_press
from pokeagent.explorer.context import ExplorerContext
from pokeagent.explorer.economy import ledger, outside_use
from pokeagent.explorer.procedures.state import of
from pokeagent.goals import bag_contents
from pokeagent.knowledge import trainers
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import our_party, species_row
from pokeagent.procedures.after_victory_rules import decide
from pokeagent.procedures.predicates import beaten_trainers
from pokeagent.ramstructs import read_party

log = logging.getLogger(__name__)

LOG_NAME = "after_victory.jsonl"
FAR = 10 ** 6  # a trainer not on the active procedure's path sorts last (by distance)
_walk_warned: set = set()  # walk_to_center failures already logged (once per distinct message)


def _party_now(emu) -> list:
    """Our party as Combatants with each member's hp replaced by its CURRENT hp (same slot filter our_party uses)."""
    names = table(None, "name_of_internal")
    mons = [m for m in read_party(emu) if m.level and species_row(names.get(str(m.species), ""), None) is not None]
    return [replace(c, hp=mons[i].hp) for i, c in enumerate(our_party(emu)) if i < len(mons)]


class AfterVictory(BehaviourBase):
    name = "after_victory"

    def applies(self, ctx: ExplorerContext) -> bool:
        """A trainer win is still undecided (battle bookkeeping bumps ``twins``; a wild win never does)."""
        return (of(ctx)["twins"] > 0 and not ctx.view.battling and not ctx.in_battle
                and not ctx.view.box and ctx.proc is None)

    def step(self, ctx: ExplorerContext) -> Decision | None:
        st = of(ctx)
        st["twins"] = 0             # every recorded trainer win is decided by this one call
        st["seen"] = ctx.battles_won
        m, x, y = ctx.view.m, ctx.view.x, ctx.view.y
        beaten = beaten_trainers(ctx)
        rows = [r for r in trainers.trainers_on(m) if r.get("mons") and (m, r.get("x"), r.get("y")) not in beaten]
        order = {}
        run = st["run"]
        if run is not None:  # remaining trainers in the active procedure's step order when one exists
            for i, s in enumerate(run["proc"].steps):
                a = s.action or {}
                if a.get("name") == "fight_trainer" and isinstance(a.get("at"), (list, tuple)):
                    order.setdefault(tuple(a["at"]), i)
        rows.sort(key=lambda r: (order.get((m, r.get("x"), r.get("y")), FAR),
                                 abs(r.get("x", x) - x) + abs(r.get("y", y) - y)))
        try:
            walk = outside_use.walk_to_center(ctx)
        except Exception as exc:  # noqa: BLE001 - a routing failure must not break the decision
            walk = None
            if repr(exc) not in _walk_warned:  # once per distinct message, via the module logger
                _walk_warned.add(repr(exc))
                log.warning("after_victory: walk_to_center failed, deciding without it: %r", exc)
        dec = st["victory"] = decide(_party_now(ctx.emu), [r["mons"] for r in rows],
                                     bag_contents(ctx.emu), walk)
        if dec.action == "potion":
            led = ledger.of(ctx)  # the field-potion verdict CaveTopUp/outside_use.field_wants already honours
            led.field_check_at = ctx.step + outside_use.RECHECK_EVERY
            led.field_decision = True
        elif dec.action == "heal":
            heal_walk.start(ctx, "after_victory")  # a real walk request; StatusCare carries it out press by press
        line = self._line(dec, rows)
        ctx.log(line, "res")
        self._record(ctx, dec)
        return no_press("after_victory", line)

    @staticmethod
    def _line(dec, rows) -> str:
        nxt = ""
        if dec.next_trainer:
            r = rows[0] if rows else {}
            who = f"{r.get('class', '?')} p{r.get('party', '?')} ({r.get('x')},{r.get('y')})" if r else ""
            nxt = f"next {who} {dec.next_trainer}, ".replace("  ", " ")
        margin = f"{dec.margin:+.2f}" if dec.margin is not None else "n/a"
        return (f"[after_victory] {dec.action}: {nxt}margin {margin}, party {dec.hp_frac:.0%} "
                f"(lead {dec.lead_hp_frac:.0%}), {dec.alive} alive [{dec.why}]")

    @staticmethod
    def _record(ctx: ExplorerContext, dec) -> None:
        try:  # one object per decision, no ROM data; a write failure is swallowed with one log line
            path = ctx.run_dir / LOG_NAME
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step": ctx.step, "map": ctx.view.m, "action": dec.action,
                                     "margin": dec.margin, "hp_frac": round(dec.hp_frac, 3),
                                     "lead_hp_frac": round(dec.lead_hp_frac, 3), "alive": dec.alive,
                                     "why": dec.why}) + "\n")
        except OSError as exc:
            ctx.log(f"[after_victory: record skipped: {exc!r}]", "res")
