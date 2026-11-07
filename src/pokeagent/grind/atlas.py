"""rank_spots: where to grind for (lead species, lead level, goal). ROM-math prior, corrected by observed battles, minus risk
and the amortised Pokecenter round trip. Time unit is the explorer step (one press); FRAMES_PER_STEP converts par frames."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from pokeagent.grind.observed import Obs, band, pooled
from pokeagent.grind.xpmath import xp_gain, xp_needed

FRAMES_PER_STEP = 16      # ASSUMPTION: one explorer step ~ one walked tile (16 frames); calibrate from decisions.jsonl later
STEPS_PER_MIN = 3600 / FRAMES_PER_STEP
SHRINK_K = 10             # observed battles that outweigh the prior 50:50
SESSION_BATTLES = 25      # one grind session between heals (explorer.grind.GRIND_BATTLES)
BLACKOUT_STEPS = 2000     # steps a blackout costs (warp home, walk back, lose the money)
PRIOR_WIN, PRIOR_BLACKOUT, PRIOR_HP, PRIOR_BATTLE_STEPS = 0.92, 0.02, 0.25, 40.0
SLOT_CHANCE = [x / 256 for x in (51, 51, 39, 25, 25, 25, 13, 13, 11, 3)]
FAR = 9e4                 # frames to a Pokecenter we know nothing about


@dataclass
class Spot:
    map_id: int
    name: str
    xp_per_battle: float      # expected, after win rate (observed real XP blended in when logged)
    encounter_p: float        # per grass step
    n_obs: int
    win: float
    blackout: float           # blackout probability per battle: the risk term
    hp_lost: float
    battle_steps: float
    travel_steps: float       # amortised Pokecenter round trip per battle
    xp_per_step: float        # net of risk and travel
    xp_per_min: float
    steps_to_goal: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def prior_xp(row: dict, base_exp: dict) -> float:
    """Expected XP per wild encounter on a map's grass table [[level, species]*10]."""
    return sum(SLOT_CHANCE[i] * xp_gain(base_exp.get(sp, 0), lv) for i, (lv, sp) in enumerate((row.get("grass") or [])[:10]))


def blend(prior: float, obs: float | None, n: int) -> float:
    return prior if obs is None else (prior * SHRINK_K + obs * n) / (SHRINK_K + n)


def rank_spots(starter: str, level: int, need_level: int | None, tables: dict, stats: dict, center_cost: dict,
               growth: str = "MEDIUM_SLOW", candidates=None, top: int = 3, names=None) -> list[Spot]:
    """Best grind spots, best first. ``tables`` = {"wild": {map: row}, "base_exp": {species: n}}; ``stats`` from observed.fold;
    ``center_cost`` = {map: frames to the nearest Pokecenter} (unknown = very far). ``need_level`` None = no goal gap."""
    pool = [o for (s, b, _m, _g), o in stats.items() if s is None and b == band(level)]
    allp = Obs()
    for o in pool:
        allp = allp.merge(o)
    avg_steps = allp.presses / allp.n if allp.n else PRIOR_BATTLE_STEPS
    need_xp = xp_needed(growth, level, need_level) if need_level else 0
    out = []
    for m, row in tables["wild"].items():
        m = int(m)
        if (candidates is not None and m not in candidates) or not row.get("grass") or not row.get("grass_rate"):
            continue
        o = pooled(stats, starter, level, m)
        if o.n < 3:
            o = pooled(stats, None, level, m)  # too few of this starter's battles: borrow the pooled ones
        n = o.n
        win = blend(PRIOR_WIN, o.wins / n if n else None, n)
        blk = blend(PRIOR_BLACKOUT, o.blackouts / n if n else None, n)
        hp = blend(PRIOR_HP, o.hp_lost / n if n else None, n)
        bsteps = blend(avg_steps, o.presses / n if n else None, n)
        p = row["grass_rate"] / 256
        xp_b = blend(prior_xp(row, tables["base_exp"]) * win, o.xp_sum / o.xp_n if o.xp_n else None, o.xp_n)
        travel = 2 * center_cost.get(m, FAR) / FRAMES_PER_STEP / SESSION_BATTLES
        per_step = xp_b / (1 / p + bsteps + travel + blk * BLACKOUT_STEPS)
        out.append(Spot(m, (names or {}).get(m, f"0x{m:02X}"), xp_b, p, n, win, blk, hp, bsteps, travel, per_step,
                        per_step * STEPS_PER_MIN, need_xp / per_step if need_xp and per_step > 0 else None,
                        "" if n else "prior only"))
    return sorted(out, key=lambda s: -s.xp_per_step)[:top]
