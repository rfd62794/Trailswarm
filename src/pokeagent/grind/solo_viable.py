"""Solo-viability: can the trainee win a map's wild fights alone, and what does the nurse cost?

The switch trick (send the trainee in, swap it out on turn one) pays half XP at best. When the
trainee can win a map's encounters ALONE it keeps all of it - but only on maps near a Pokecenter
(the nurse walk eats grind time) and only inside ``MAX_TRAVEL_STEPS``. ``choose()`` gets the whole
judgment as a ``rank`` closure from ``make_rank``/``rank_for``; the in-battle start gate is
``SOLO_START_HP`` (switch_out latches it per battle into the episode dict).

Missing data is NEVER viable: an empty encounter mix, an empty move table or an unknown species
answers None/False - a guess that says "viable" would grind the trainee into blackouts.
"""
from __future__ import annotations

from pokeagent.grind import atlas
from pokeagent.grind.points import FAR_TRAVEL, MIN_MEASURED, travel_steps
from pokeagent.knowledge import readiness
from pokeagent.knowledge.encounters import slot_chances
from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import Combatant, trainer_mon

SOLO_MIN_WIN = 0.95      # share of encounters the trainee must win alone (over atlas PRIOR_WIN: 1
                        # loss in 12 already blacks out inside one GRIND_BATTLES session)
SOLO_MARGIN = 0.30       # mean HP fraction wanted after the wins (= readiness.MARGIN: the boss margin)
SOLO_START_HP = 0.6      # HP fraction a solo trainee must ENTER a battle with: a fight can cost 1 - SOLO_MARGIN
MAX_TRAVEL_STEPS = 320   # 10 map crossings at HOP_STEPS, ~an eighth of GRIND_STEPS: no solo preference past it
MIN_HP_FRACTION = 0.5    # = explorer.train_route.MIN_HP_FRACTION (this module never imports explorer)


def encounter_mix(kb, map_id) -> list[tuple[str, int, float]]:
    """[(species, level, weight)] of a map's grass slots: each slot's own level weighted by
    ``slot_chances()[i]``; rows sharing species AND level are summed. Weights sum to 1 on a full table."""
    row = table(kb, "wild_by_map").get(str(map_id)) or table(kb, "wild_by_map").get(map_id) or {}
    mix: dict = {}
    for i, (lv, sp) in enumerate((row.get("grass") or [])[:len(slot_chances())]):
        mix[(sp, lv)] = mix.get((sp, lv), 0.0) + slot_chances()[i]
    return [(sp, lv, w) for (sp, lv), w in mix.items()]


def solo_verdict(trainee: Combatant, kb, map_id) -> tuple[float, float] | None:
    """(win_rate, mean_hp_left) of the trainee fighting every encounter alone: the chance-weighted
    share of wins, and the weight-averaged HP fraction left over the wins (0 when it wins none).
    None = missing data - and missing data is never viable."""
    mix, moves = encounter_mix(kb, map_id), table(kb, "moves")
    if trainee is None or not mix or not moves:
        return None
    chart = {(a, d): e for a, d, e in table(kb, "type_chart")}
    wins, hp = 0.0, 0.0
    for sp, lv, w in mix:
        foe = trainer_mon(sp, lv, kb)
        if foe is None:
            return None            # an unknown species: never a guess
        r = readiness.fight([trainee], [foe], chart, moves)
        if r >= 0:
            wins, hp = wins + w, hp + w * r
    return wins, hp / wins if wins else 0.0


def passes(verdict) -> bool:
    """Does a (win_rate, mean_hp_left) verdict meet the solo bars? None (missing data) never does."""
    return verdict is not None and verdict[0] >= SOLO_MIN_WIN and verdict[1] >= SOLO_MARGIN


def is_solo_viable(trainee: Combatant | None, kb, map_id) -> bool:
    return passes(solo_verdict(trainee, kb, map_id))


def nurse_steps(maps: dict, point, centers) -> float:
    """Steps from the point's map to the nearest known Pokecenter map; the point's measured
    ``center_cost_frames`` converted when no map route is learned; FAR_TRAVEL when neither is known."""
    d = min((travel_steps(maps, point.map_id, c) for c in centers or ()), default=FAR_TRAVEL)
    if d < FAR_TRAVEL:
        return d
    cost = getattr(point, "center_cost_frames", 0.0) or 0.0
    return cost / atlas.frames_per_step() if cost > 0 else float(FAR_TRAVEL)


def nurse_penalty(xp_per_min: float, mean_hp_left: float, steps: float) -> float:
    """xp/min lost to nurse round trips: the fraction of grind time spent walking to the nurse and
    back (a heal is wanted each time the trainee drops under MIN_HP_FRACTION), in xp/min units."""
    heals = (atlas.STEPS_PER_MIN / atlas.PRIOR_BATTLE_STEPS) * (1 - mean_hp_left) / (1 - MIN_HP_FRACTION)
    return xp_per_min * min(1.0, heals * 2 * steps / atlas.STEPS_PER_MIN)


def make_rank(viable: dict, nurse: dict, maps: dict, current_map):
    """choose()'s ``rank`` closure: a solo-viable point inside MAX_TRAVEL_STEPS gets
    (False, -(score - nurse penalty), map_id) and sorts ahead of every other point; anything else
    returns None - not preference-eligible, so _best orders it by today's score behind them."""
    def rank(p, score):
        v = viable.get(p.map_id)
        if not passes(v) or travel_steps(maps, current_map, p.map_id) > MAX_TRAVEL_STEPS:
            return None
        xp = p.xp_per_min_measured if (p.n_measured >= MIN_MEASURED and p.xp_per_min_measured is not None) \
            else p.xp_per_min_prior
        return (False, -(score - nurse_penalty(xp, v[1], nurse.get(p.map_id, FAR_TRAVEL))), p.map_id)
    return rank


def rank_for(points, ours: list, levels: list, slot, only_maps, maps: dict, current_map, centers,
             n_party: int, kb=None):
    """(rank closure, {map_id: (win_rate, hp_left)}) for a trainee that is not the fighter (its level
    under the top party level), else (None, {}). ``ours`` = the our_party Combatants: when it does
    not cover the RAM party 1:1 (a member had no ROM row) the indices are shifted and the whole
    check is skipped - never a guessed verdict."""
    if slot is None or not levels or not 0 <= slot < len(levels) or levels[slot] >= max(levels):
        return None, {}
    if len(ours) != n_party or not 0 <= slot < len(ours):
        return None, {}
    viable, nurse = {}, {}
    for p in points:
        if only_maps is not None and p.map_id not in only_maps:
            continue
        v = solo_verdict(ours[slot], kb, p.map_id)
        if v is not None:
            viable[p.map_id], nurse[p.map_id] = v, nurse_steps(maps, p, centers)
    return make_rank(viable, nurse, maps, current_map), viable
