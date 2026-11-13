"""The party stands lowest level first; every gate reads the strongest fighter, never slot 0 (Robert 2026-11-12)."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import party_order as po
from pokeagent.explorer.behaviours.cave_topup import fighter_slot
from pokeagent.explorer.item_policies.view import Mon, fighter_slot_of
from pokeagent.explorer.perceive import lead_level, party_hp, true_lead_level
from pokeagent.goals import GOALS
from pokeagent.knowledge import team_plan
from pokeagent.magikarp import MAGIKARP
from test_magikarp import party_mem

CHARMELEON = 0xB2   # any non-Magikarp internal id: only levels and the Magikarp id matter here


def _emu(mons):
    return FakeEmulator(party_mem(mons))


def _ctx(mons, step=100):
    return SimpleNamespace(emu=_emu(mons), step=step)


def _settle(levels, fainted=None):
    """Apply next_swap until the party stands; returns (final levels, swaps made)."""
    levels, fainted = list(levels), list(fainted or [False] * len(levels))
    swaps = 0
    while (sw := team_plan.next_swap(levels, fainted)) is not None:
        s, w = sw
        levels[s], levels[w] = levels[w], levels[s]
        fainted[s], fainted[w] = fainted[w], fainted[s]
        swaps += 1
        assert swaps < 20
    return levels, swaps


# --- 1. the one ordering rule -------------------------------------------------------------------------------------

def test_ascending_order_lowest_first_fainted_last_ties_stable():
    assert team_plan.ascending_order([16, 5, 9], [False] * 3) == [1, 2, 0]
    assert team_plan.ascending_order([10, 3, 7], [False, True, False]) == [2, 0, 1]   # the L3 is fainted: last
    assert team_plan.ascending_order([8, 8, 8], [False] * 3) == [0, 1, 2]              # ties keep the current order


def test_settle_reaches_ascending_and_a_sorted_party_never_moves():
    assert _settle([16, 5, 9, 12])[0] == [5, 9, 12, 16]
    assert _settle([5, 9, 12, 16])[1] == 0
    assert _settle([8, 8, 5, 8])[0] == [5, 8, 8, 8]
    assert _settle([9, 4, 6], [False, False, True])[0] == [4, 9, 6]                    # fainted L6 goes last


def test_charmeleon_and_magikarp_reorder_puts_magikarp_first():
    ctx = _ctx([(CHARMELEON, 16, 50, 50), (MAGIKARP, 5, 17, 17)])
    src, want, why = po.want_home(ctx)
    assert (src, want) == (1, 0) and "lowest level first" in why


def test_no_churn_between_two_orders():
    """The Charmeleon/Magikarp flip-flop (~117 presses): once Magikarp leads nothing asks to move again."""
    mons = [(MAGIKARP, 5, 17, 17), (CHARMELEON, 16, 50, 50)]
    for step in (100, 150, 600):
        assert po.want_home(_ctx(mons, step)) is None
    # equal levels: whichever order stands, stands
    assert po.want_home(_ctx([(CHARMELEON, 9, 30, 30), (0x54, 9, 30, 30)])) is None


def test_hold_blocks_a_repeat_until_the_team_changes_and_never_expires():
    ctx = _ctx([(CHARMELEON, 16, 50, 50), (MAGIKARP, 5, 17, 17)])
    team_plan.of(ctx)["order_hold"] = (ctx.step - 12, po.team_sig(ctx))
    assert po.want_home(ctx) is None                                 # held: a level-neutral reorder is not repeated
    ctx.emu = _emu([(CHARMELEON, 16, 50, 50), (MAGIKARP, 6, 18, 18)])   # the Magikarp levelled: team changed
    assert po.want_home(ctx) is not None
    ctx.emu = _emu([(CHARMELEON, 16, 50, 50), (MAGIKARP, 5, 17, 17)])
    for later in (300, 3000, 30000):                                  # a battle's switch-out moved the order: no churn, ever
        ctx.step += later
        assert po.want_home(ctx) is None
    ctx.emu = _emu([(CHARMELEON, 17, 55, 55), (MAGIKARP, 5, 17, 17)])  # the fighter levelled: the team changed
    assert po.want_home(ctx) is not None


def test_only_one_ordering_rule_remains():
    for gone in ("trainee_home", "_opponent", "_lead_weak", "_opp_key"):
        assert not hasattr(po, gone)


# --- 2. gates read the fighter, not slot 0 -------------------------------------------------------------------------

WEAK_LEAD = [(MAGIKARP, 5, 17, 17), (CHARMELEON, 16, 50, 50)]
NO_KARP = [(0x54, 6, 20, 20), (CHARMELEON, 18, 50, 50)]


def test_lead_level_and_party_hp_read_the_strongest_healthy_member():
    for mons in (WEAK_LEAD, NO_KARP):
        emu = _emu(mons)
        assert lead_level(emu) == true_lead_level(emu) == mons[1][1]
        assert party_hp(emu) == (50, 50)


def test_a_fainted_strongest_member_is_not_the_fighter():
    emu = _emu([(0x54, 6, 20, 20), (CHARMELEON, 18, 0, 50)])
    assert lead_level(emu) == 6 and party_hp(emu) == (20, 20)


def test_cave_topup_fighter_slot_is_the_strongest_not_the_lead():
    assert fighter_slot(_emu(WEAK_LEAD)) == 1 and fighter_slot(_emu(NO_KARP)) == 1


def test_item_policy_fighter_slot_generalises_beyond_magikarp():
    party = [Mon(0, "RATTATA", 6, (), 20, 20, ()), Mon(1, "CHARMELEON", 18, (), 50, 50, ())]
    assert fighter_slot_of(party) == 1


def test_level_band_puts_the_strongest_at_need():
    from pokeagent.knowledge.party import Combatant
    team = [Combatant("A", 6, ("NORMAL",), 20, (5,) * 4, (), (8,) * 5, (0,) * 5),
            Combatant("B", 18, ("FIRE",), 50, (5,) * 4, (), (8,) * 5, (0,) * 5)]
    band = team_plan.level_band(team, 18)
    assert band[1] == (18, 18) and band[0] == (14, 18) and team_plan.band_breakers(team, band) == (0,)


def test_assess_raises_the_strongest_not_slot_0(monkeypatch):
    from pokeagent.knowledge import readiness
    seen = []
    monkeypatch.setattr(readiness, "trainer_mon", lambda n, lv, kb=None: SimpleNamespace(hp=10))
    monkeypatch.setattr(readiness, "table", lambda kb, k: {"x": 1})
    monkeypatch.setattr(readiness, "_chart", lambda kb: {})
    monkeypatch.setattr(readiness, "matchup_text", lambda *a: "")
    monkeypatch.setattr(readiness, "at_level", lambda c, L, kb=None: SimpleNamespace(name=c.name, level=L, hp=c.hp))
    monkeypatch.setattr(readiness, "fight", lambda ours, theirs, chart, moves: seen.append([c.level for c in ours]) or (1.0 if max(c.level for c in ours) >= 12 else -1.0))
    party = [SimpleNamespace(name="W", level=5, hp=10), SimpleNamespace(name="S", level=9, hp=10)]
    r = readiness.assess(party, [(10, "X")], "B")
    assert r is not None and r.required == 12
    assert [5, 12] in seen                                           # the L9 member was raised, slot 0 stayed L5


# --- 3. regression: the Magikarp-lead Route 3 grind loop ----------------------------------------------------------

def test_magikarp_lead_does_not_send_the_agent_back_to_route3(monkeypatch):
    """2026-11-12: [MAGIKARP L5, CHARMELEON L16], Mt Moon need L12. The gate read min(16, 5 + TEAM_GAP) = 11 < 12 and the
    planner walked back to Route 3 for 1,500+ steps. The gate now reads the fighter (16): the planner heads for the cave."""
    from pokeagent.explorer import planner_east
    emu = _emu(WEAK_LEAD)
    goals = {g: True for g in GOALS[:GOALS.index("to_mt_moon")]}
    need = 12
    goals.update({"_level": lead_level(emu), "_train_level": need, "_hp": party_hp(emu)})
    assert goals["_level"] == 16
    calls = []
    g = SimpleNamespace(path=lambda pos, goal: calls.append(goal) or ["UP"], blocked_now=frozenset())
    monkeypatch.setattr(planner_east, "checkpoint_step", lambda *a, **k: None)
    monkeypatch.setattr(planner_east, "ship_gate_step", lambda *a, **k: None)
    out = planner_east.east_road_step(g, {}, goals, (planner_east.ROUTE4, 5, 5))
    assert out is None or "to train to" not in out[1]
    # and the old behaviour, for contrast: a capped level under the need does grind Route 3
    old = planner_east.east_road_step(g, {}, {**goals, "_level": 11}, (planner_east.ROUTE4, 5, 5))
    assert old is not None and "Route 3 to train to L12" in old[1]


# --- 3b. battle: the weak lead is swapped for the strongest healthy member --------------------------------------------

def test_switch_candidate_sends_in_the_strongest_healthy_member_for_a_weak_lead():
    from pokeagent.magikarp import switch_candidate
    emu = _emu([(0x54, 6, 20, 20), (0x55, 12, 0, 40), (CHARMELEON, 18, 50, 50), (0x56, 15, 4, 40)])
    assert switch_candidate(emu, 0) == 2             # not the fainted L12, not the L15 under 25% HP
