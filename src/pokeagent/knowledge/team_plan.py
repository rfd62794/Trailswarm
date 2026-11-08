"""Team management judgments for a growing party: the gate judges the whole team (not slot 0), the lead
is chosen by matchup, mid-battle switches follow type and HP, exp is spread by a level band, and the
grind pressure that plan_goal reads rises with team size and the gap to the next boss.

Pure: the party is a list of Combatant-like members (name, level, types, moves; ``hp`` is the member's
HP figure - max HP for the planning helpers, and the in-battle helpers take a separate ``hp_now`` list
of CURRENT HP because a Combatant's ``hp`` is the max). Bosses are ``[(level, species)]`` exactly like
readiness.team_readiness, and the kb tables come in as arguments. No emulator, no RAM.

The one Gen 1 wrinkle shared with readiness: a MAGIKARP is judged as the GYARADOS it becomes for a
raise search at or past EVOLVE_LEVEL (deferred import, same as readiness/team_value).
"""
from __future__ import annotations

from dataclasses import dataclass

from pokeagent.knowledge.kb import table
from pokeagent.knowledge.party import Combatant, at_level, trainer_mon
from pokeagent.knowledge.readiness import MARGIN, MAX_LEVEL, TEAM_GAP, best_move, fight

# --- exp-spread band and rotation ----------------------------------------------------
BAND_BELOW = 4                    # non-lead members are asked to stay within this many levels of the lead's target; untuned

# --- matchup switching ---------------------------------------------------------------
SWITCH_HP_TURNS = 2               # "thin": the foe's best expected hit over this many turns meets or beats our current HP
WEAK_RATIO = 0.5                  # "thin": our best move does at most this fraction of the foe's HP per turn
SWITCH_MIN_HP = 0.25              # a switch-in must hold at least this HP fraction (= magikarp.SWITCH_MIN_HP)
SWITCH_GAIN = 1.5                 # a switch must buy at least this much more damage per turn than staying; untuned
MAX_SWITCHES_PER_BATTLE = 2       # matchup switches per trainer battle (the count lives in the battle record)

# --- grind pressure (the one knob plan_goal reads) ------------------------------------
GRIND_PRESSURE_START = 0.5        # pressure that latches the grind episode on; untuned
GRIND_PRESSURE_STOP = 0.2         # pressure that releases it (hysteresis); untuned
BREAKER_W = 0.5                   # weight of band breakers over team size
GAP_W = 0.3                       # weight of the level gap to the stage need
BLACKOUT_W = 0.2                  # weight of recent blackouts
GAP_CAP = 8                       # a level gap this large already reads as the maximum
BLACKOUT_CAP = 3                  # blackouts in a row past this read the same
NEAR_STEPS = 200                  # a boss this many route steps away or nearer adds urgency
NEAR_BONUS = 0.25                 # extra pressure as the boss approaches (scaled by distance)


@dataclass(frozen=True)
class Need:
    """boss_need's verdict: what the whole team must do before ``boss``.

    ``level_by_slot`` = the lowest level at which raising THAT member alone makes the fight pass
    (``None`` = no level works). ``raise_slot``/``raise_level`` = the cheapest passing single raise
    (``None`` when none exists: "train the band"). ``need`` = the level the gate wants
    (``raise_level``, else the boss's top level for the band). ``weak_slots`` = members below their
    level-band ``lo`` at ``need``. ``team_score`` = readiness.fight of the team as it stands."""
    ready: bool
    team_score: float
    lead_slot: int
    level_by_slot: dict
    raise_slot: int | None
    raise_level: int | None
    need: int
    weak_slots: tuple
    text: str


def _chart(kb) -> dict:
    return {(a, d): e for a, d, e in table(kb, "type_chart")}


def _grown(c: Combatant, level: int, kb) -> Combatant:
    """``c`` trained to ``level``: a MAGIKARP is judged as the GYARADOS it becomes at EVOLVE_LEVEL."""
    from pokeagent.magikarp import EVOLVE_LEVEL  # deferred: keep this pure module free of the emulator import
    if c.name == "MAGIKARP":
        g = trainer_mon("GYARADOS", max(level, EVOLVE_LEVEL), kb)
        if g is not None:
            return g
    return at_level(c, level, kb)


def _now(c: Combatant, kb) -> Combatant:
    """``c`` as it fights today: only an evolved MAGIKARP counts as its GYARADOS."""
    from pokeagent.magikarp import EVOLVE_LEVEL
    return _grown(c, c.level, kb) if c.name == "MAGIKARP" and c.level >= EVOLVE_LEVEL else c


def _theirs(boss, kb) -> list[Combatant]:
    return [m for lv, n in boss or () if (m := trainer_mon(n, lv, kb))]


def choose_lead(team, opponent_party, kb, hp_now=None) -> int:
    """Slot of the member with the best first-turn matchup vs the opponent's lead: highest best-move
    damage ratio (expected damage per turn over the foe's HP), then HP fraction, then level; the lowest
    slot breaks what is left. For wild grinding the lead is the trainee instead (trainee_slot)."""
    if not team or not opponent_party:
        return 0
    chart, moves, foe = _chart(kb), table(kb, "moves"), opponent_party[0]

    def key(i: int):
        frac = hp_now[i] / team[i].hp if hp_now is not None and i < len(hp_now) and team[i].hp else 1.0
        return (best_move(team[i], foe, chart, moves)[0] / max(foe.hp, 1), frac, team[i].level, -i)
    return max(range(len(team)), key=key)


def survives_hit(member: Combatant, foe: Combatant, chart: dict, moves: dict) -> bool:
    """The member can take the foe's best expected hit once (a rotation lead must survive the wild mon)."""
    return best_move(foe, member, chart, moves)[0] < member.hp


def boss_need(team, boss, kb, label: str = "BOSS") -> Need | None:
    """The whole party vs ``boss`` ([(level, species)]): the best-switch fight of the team as it stands,
    then the per-member raise each slot alone would need for it to pass, so the verdict names a raise
    target whichever slot the strong mon sits in. ``None`` without data (same conditions as assess)."""
    theirs = _theirs(boss, kb)
    moves = table(kb, "moves")
    if not team or not boss or len(theirs) != len(boss) or not moves:
        return None
    chart = _chart(kb)
    now = [_now(c, kb) for c in team]
    score = fight(now, theirs, chart, moves)
    lead_slot = choose_lead(now, theirs, kb)
    if score >= MARGIN:
        return Need(True, round(score, 2), lead_slot, {}, None, None, now[lead_slot].level, (),
                    f"team ready vs {label}")
    asks = {}
    for i, c in enumerate(team):
        asks[i] = next((L for L in range(c.level + 1, MAX_LEVEL + 1)
                        if fight([_grown(team[j], L, kb) if j == i else now[j] for j in range(len(team))],
                                 theirs, chart, moves) >= MARGIN), None)
    raise_slot = min((i for i, L in asks.items() if L is not None),
                     key=lambda i: (asks[i] - team[i].level, asks[i], i), default=None)
    need = asks[raise_slot] if raise_slot is not None else max(lv for lv, _ in boss)
    weak = band_breakers(team, level_band(team, need))
    if raise_slot is not None:
        text = f"team not ready vs {label}: raise {team[raise_slot].name} (slot {raise_slot + 1}) to L{need}"
    else:
        text = f"team not ready vs {label}: no single raise works - train the band"
    return Need(False, round(score, 2), lead_slot, asks, raise_slot,
                asks.get(raise_slot), need, weak, text)


def level_band(team, need: int) -> dict:
    """{slot: (lo, hi)} target levels per member: the lead (slot 0) at ``need``, every other member
    within BAND_BELOW of it - the exp-spread band the rotation keeps."""
    return {i: (max(1, need if i == 0 else need - BAND_BELOW), need) for i in range(len(team or ()))}


def band_breakers(team, band) -> tuple:
    """Slots whose level is under their band's ``lo``: the members a grind should feed first."""
    return tuple(i for i, (lo, _hi) in (band or {}).items() if i < len(team or ()) and team[i].level < lo)


def trainee_slot(party, named: int | None = None, breakers=(), wild=None, kb=None) -> int | None:
    """The non-Magikarp training lead (the exp-spread rotation). ``named`` = the slot team_readiness's
    weakest member names: it wins when it is a non-lead member at least TEAM_GAP under the lead's level
    (the old rule). Otherwise the lowest-level band breaker that can survive the wild mon - ``wild`` =
    [(level, species)] or Combatants, whose best hits the member must take once (no wild data: the
    lowest breaker leads anyway). MAGIKARP never answers here: its own slot wins upstream."""
    if not party:
        return None
    if named is not None and 0 < named < len(party) and party[named].level <= party[0].level - TEAM_GAP:
        return named
    foes = []
    for w in wild or ():
        f = w if isinstance(w, Combatant) else trainer_mon(w[1], w[0], kb)
        if f is not None:
            foes.append(f)
    chart, moves = _chart(kb), table(kb, "moves")
    for s in sorted((s for s in breakers if 0 <= s < len(party)), key=lambda s: (party[s].level, s)):
        if not foes or all(survives_hit(party[s], f, chart, moves) for f in foes):
            return s
    return None


def switch_choice(team, active_slot: int, opponent, kb, *, hp_now=None, switches: int = 0,
                  trainee: int | None = None) -> int | None:
    """Party slot to switch to in a TRAINER battle, or None.

    The active member is "thin" when the foe's best expected hit over SWITCH_HP_TURNS turns meets or
    beats its CURRENT hp, or its own best move does at most WEAK_RATIO of the foe's HP per turn. A
    switch then needs another healthy member (current HP >= SWITCH_MIN_HP of its max) whose expected
    damage per turn beats the active's by SWITCH_GAIN - the best such slot is returned. Never switches
    the ``trainee`` IN, never past MAX_SWITCHES_PER_BATTLE switches (the caller counts them)."""
    if not team or opponent is None or not (0 <= active_slot < len(team)) or switches >= MAX_SWITCHES_PER_BATTLE:
        return None
    chart, moves = _chart(kb), table(kb, "moves")
    active, foe = team[active_slot], opponent
    hp = list(hp_now) if hp_now is not None else [c.hp for c in team]
    cur = hp[active_slot] if active_slot < len(hp) else active.hp
    our_dmg = best_move(active, foe, chart, moves)[0]
    thin = best_move(foe, active, chart, moves)[0] * SWITCH_HP_TURNS >= cur or our_dmg <= WEAK_RATIO * foe.hp
    if not thin:
        return None
    pick, best = None, our_dmg * SWITCH_GAIN
    for i, c in enumerate(team):
        if i == active_slot or i == trainee:
            continue
        ci = hp[i] if i < len(hp) else c.hp
        if c.hp <= 0 or ci / c.hp < SWITCH_MIN_HP:
            continue
        d = best_move(c, foe, chart, moves)[0]
        if d >= best and (pick is None or d > best_move(team[pick], foe, chart, moves)[0]):
            pick = i
    return pick


def grind_pressure(team, need: int, next_boss_gap_steps: int = 0, blackouts_recent: int = 0, *,
                   breakers=(), ready: bool = False, lead_level: int | None = None) -> float:
    """[0,1] pressure to grind rather than push the stage - the one knob plan_goal reads.

    0 when the team already passes boss_need (``ready``) or there is no gap to close. Otherwise::

        pressure = BREAKER_W * (band breakers / team size)
                 + GAP_W * min(need - lead_level, GAP_CAP) / GAP_CAP
                 + BLACKOUT_W * min(blackouts_recent, BLACKOUT_CAP) / BLACKOUT_CAP
                 + NEAR_BONUS * (1 - min(next_boss_gap_steps, NEAR_STEPS) / NEAR_STEPS)

    The band-breaker share is what makes pressure rise with team size: the more members below their
    band, the more exp a grind spreads. ``next_boss_gap_steps`` is the learned-world distance to the
    boss's map: the nearer the boss while the team is short, the harder we grind before walking in.
    """
    if not team or ready:
        return 0.0
    lead = lead_level if lead_level is not None else max(c.level for c in team)
    gap = max(0, (need or 0) - lead)
    base = (BREAKER_W * (len(set(breakers)) / len(team))
            + GAP_W * (min(gap, GAP_CAP) / GAP_CAP)
            + BLACKOUT_W * (min(blackouts_recent, BLACKOUT_CAP) / BLACKOUT_CAP))
    if base <= 0:
        return 0.0  # no gap, no breakers, no blackouts: nothing to grind for, however near the boss
    near = NEAR_BONUS * max(0.0, 1.0 - min(next_boss_gap_steps, NEAR_STEPS) / NEAR_STEPS)
    return round(min(1.0, base + near), 3)


def release_candidate(party, *, protected=frozenset(), values=None) -> int | None:
    """Slot of the member a full party gives up for a wanted catch: the lowest ``values`` score
    (``team_value`` member scores supplied by the caller; the member's level when none are), never a
    ``protected`` slot - the trainee and HM learners the run still needs are marked protected upstream."""
    picks = [(values[i] if values and i < len(values) else party[i].level, i)
             for i in range(len(party or ())) if i not in protected]
    return min(picks, default=None)[1] if picks else None


def of(ctx) -> dict:
    """team_plan's per-run state dict on ``ctx.__dict__`` (never a context field: context.py and
    memory.py are at the size ceiling): published band breakers, the grind latch, the matchup switch
    in flight, a pending full-party deposit."""
    return ctx.__dict__.setdefault("team_plan_state", {})
