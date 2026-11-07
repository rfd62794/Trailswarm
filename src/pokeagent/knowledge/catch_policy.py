"""catch_policy: what to DO about a wanted wild mon this turn - weaken it, status it, switch to the
catcher, throw the best-value ball, or skip.

HARD RULE (Robert, 2026-11-07): "you CANNOT Capture an Owned Pokemon, ONLY Wild Pokemon can be caught,
Stealing is wrong." ``may_throw`` is the ONE predicate everything obeys: kind 1 (wild) and no trainer
evidence (no trainer NPC, no battle-log kind 2); unknown kind -> False. ``decide`` returns ``skip``
whenever it is False - never a throw, a catching move or a catcher switch in a trainer battle (there the
normal win path decides everything, untouched).

``decide`` is deterministic and never raises on missing data (an unknown species returns ``skip``).
``wild``/``active``/``party`` are Combatants; ``wild.hp`` should equal ``wild_hp`` (its current HP -
``decide`` normalizes it); ``bag``/``price`` are keyed by ball name; ``chart`` is {(move type, def type):
mult} and ``moves`` the kb moves table.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from pokeagent.knowledge.catch_math import STATUS_BONUS, best_ball, p_catch
from pokeagent.knowledge.catcher import catcher_slot, max_damage, min_damage, safe_moves
from pokeagent.knowledge.damage import PHYSICAL, expected_damage, type_mult
from pokeagent.knowledge.moves import effect_of
from pokeagent.knowledge.party import Combatant

ACCEPTABLE_P = 0.15            # throw an unweakened target only if one ball has at least this chance; untuned
STATUS_MIN_GAIN = 0.05         # a status move is worth a turn only if it raises P(catch) by at least this (after its own hit chance); untuned
WEAKEN_TARGET = 0.35           # stop reducing HP at or below this fraction (the existing catch.py threshold); untuned
MAX_TURNS = 8                  # give up the attempt after this many policy turns on one wild mon
CRIT_SAFETY = 2.0              # "could it KO" margin: max-roll damage x this (a crit roughly doubles); untuned

_STATUS_PREFERENCE = {"sleep": 3, "freeze": 3, "paralyse": 2, "burn": 1, "poison": 1}  # bonus table order; burn/poison last (they chip HP)


@dataclass(frozen=True)
class CatchStep:
    kind: str          # "throw" | "status_move" | "damage_move" | "switch" | "skip"
    move: str = ""     # for the two move kinds
    ball: str = ""     # for "throw"
    slot: int | None = None   # for "switch": the party slot of the catcher
    p: float = 0.0     # P(catch) with the chosen ball now (throw) or the expected P after the step
    why: str = ""      # the logged reason


def may_throw(kind: int | None, trainer_npc: object | None = None, battle_log_kind: int | None = None) -> bool:
    """True iff the battle is a wild one (kind 1, no trainer NPC, no battle-log kind 2); unknown kind -> False."""
    return kind == 1 and trainer_npc is None and battle_log_kind != 2


def may_throw_ctx(ctx) -> bool:
    """may_throw over the explorer context's fields (bv.kind, trainer_npc, battle_log.kind)."""
    bv = getattr(ctx, "bv", None)
    return may_throw(getattr(bv, "kind", None), getattr(ctx, "trainer_npc", None),
                     (getattr(ctx, "battle_log", None) or {}).get("kind"))


def _move_row(name: str, moves: dict) -> dict | None:
    return next((m for m in (moves or {}).values() if m.get("name") == name), None)


def _expected(att: Combatant, mv: dict, dfn: Combatant, chart: dict) -> float:
    phys = mv.get("type", "") in PHYSICAL
    return expected_damage(att.level, int(mv.get("power", 0) or 0), att.stats[0] if phys else att.stats[3],
                           dfn.stats[1] if phys else dfn.stats[3], stab=mv.get("type", "") in att.types,
                           eff=type_mult(chart, mv.get("type", ""), list(dfn.types)))


def _status_step(active: Combatant, wild_hp: int, wild_hp_max: int, catch_rate: int,
                 ball_name: str, p_now: float, moves: dict) -> CatchStep | None:
    """The best status move whose accuracy-weighted P(catch) gain clears STATUS_MIN_GAIN, else None.
    A damaging move with a status side effect is a damaging move, not a candidate (kind == "status" only)."""
    best = None
    for name in active.moves:
        mv = _move_row(name, moves)
        e = effect_of(mv)
        if e is None or e.kind != "status" or e.status not in STATUS_BONUS:
            continue
        acc = float(mv.get("accuracy", 1.0) or 1.0)
        p_st = p_catch(catch_rate, wild_hp, wild_hp_max, ball_name, e.status)
        gain = acc * (p_st - p_now)
        if gain < STATUS_MIN_GAIN:
            continue
        key = (gain, _STATUS_PREFERENCE.get(e.status, 0), name)
        if best is None or key > best[0]:
            best = (key, name, acc, p_st)
    if best is None:
        return None
    _, name, acc, p_st = best
    p_exp = acc * p_st + (1 - acc) * p_now
    return CatchStep("status_move", move=name, p=round(p_exp, 4),
                     why=f"status first: {name} takes P(catch) to {p_st:.2f} on a hit")


def decide(active: Combatant, party: list[Combatant], wild: Combatant, wild_hp: int, wild_hp_max: int,
           wild_status: str | None, catch_rate: int, bag: dict[str, int], price: dict[str, int],
           chart: dict, moves: dict, turn: int = 0, *,
           kind: int | None = 1, trainer_npc: object | None = None,
           battle_log_kind: int | None = None) -> CatchStep:
    """The next step toward catching ``wild``, first match wins: skip past MAX_TURNS / no ball / trainer
    battle; the overpower gate (switch to a catcher, or throw at full HP, or skip); a status move; the
    least-damaging safe hit while above WEAKEN_TARGET; then the best-value ball."""
    if not may_throw(kind, trainer_npc, battle_log_kind):
        return CatchStep("skip", why="trainer battle: cannot catch")
    if wild is None or active is None or wild_hp_max <= 0 or catch_rate <= 0:
        return CatchStep("skip", why="unknown species / no battle data")
    wild = wild if wild.hp == wild_hp else replace(wild, hp=wild_hp)
    if turn >= MAX_TURNS:
        return CatchStep("skip", why=f"catch attempt gave up after {MAX_TURNS} turns")
    ball = best_ball(catch_rate, wild_hp, wild_hp_max, wild_status, bag, price)
    if ball is None:
        return CatchStep("skip", why="no ball in the bag")
    ball_name, p_now = ball
    if not safe_moves(active, wild, chart, moves):
        # the overpower gate: every damaging move KOs even at the minimum roll (or none exists)
        lead = next((i for i, c in enumerate(party or ()) if c == active), 0)
        slot = catcher_slot(party or [], [wild], chart, moves, lead=lead)
        if slot is not None:
            return CatchStep("switch", slot=slot, p=p_now,
                             why=f"overpowered: switch to the catcher in slot {slot + 1}")
        if wild_hp >= wild_hp_max and p_now >= ACCEPTABLE_P:
            return CatchStep("throw", ball=ball_name, p=p_now,
                             why=f"overpowered, no catcher: throwing {ball_name} at full HP (p={p_now:.2f})")
        return CatchStep("skip", why="overpowered, no catcher, P(catch) too low")
    if not wild_status:
        step = _status_step(active, wild_hp, wild_hp_max, catch_rate, ball_name, p_now, moves)
        if step is not None:
            return step
    if wild_hp / wild_hp_max > WEAKEN_TARGET:
        okay = [n for n in safe_moves(active, wild, chart, moves)
                if max_damage(active, _move_row(n, moves), wild, chart) * CRIT_SAFETY < wild_hp]
        if okay:
            pick = min(okay, key=lambda n: (_expected(active, _move_row(n, moves), wild, chart), n))
            return CatchStep("damage_move", move=pick, p=p_now,
                             why=f"weakening: {pick} is the least-damaging hit that cannot KO")
        return CatchStep("throw", ball=ball_name, p=p_now,
                         why=f"every remaining hit could KO: throwing {ball_name} (p={p_now:.2f})")
    return CatchStep("throw", ball=ball_name, p=p_now,
                     why=f"at/below {WEAKEN_TARGET:.0%} HP: throwing {ball_name} (p={p_now:.2f})")
