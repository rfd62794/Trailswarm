"""Lead-and-wild switch (2026-11-14): a member that cannot hurt the foe never leads, wild fights get the
thin switch (about to faint or cannot damage - never the weak-ratio test), a switch-in must survive the
hit it takes on the way in, and a designated trainee below TRAINEE_SAFE_HP is always pulled.

Synthetic parties, no ROM - the SYN table style is copied from test_switch_matchup (HARDEN power 0 and
POISON STING power 15 rows added, plus KAKUNA and RATTATA species).
"""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer.behaviours import battle_switch as bs
from pokeagent.explorer.behaviours import switch_out as so_mod
from pokeagent.explorer.stats import stat_value
from pokeagent.explorer.training_ctl import roster
from pokeagent.knowledge import lead, team_plan
from pokeagent.knowledge.party import Combatant

SYN = {
    "moves": {"1": {"name": "EMBER", "type": "FIRE", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "2": {"name": "VINE WHIP", "type": "GRASS", "power": 45, "accuracy": 1.0, "effect": 0, "pp": 25},
              "3": {"name": "WATER GUN", "type": "WATER", "power": 40, "accuracy": 1.0, "effect": 0, "pp": 25},
              "4": {"name": "TACKLE", "type": "NORMAL", "power": 35, "accuracy": 1.0, "effect": 0, "pp": 35},
              "5": {"name": "HARDEN", "type": "NORMAL", "power": 0, "accuracy": 1.0, "effect": 0, "pp": 30},
              "6": {"name": "POISON STING", "type": "POISON", "power": 15, "accuracy": 1.0, "effect": 0, "pp": 35}},
    "type_chart": [["WATER", "FIRE", 2.0], ["GRASS", "WATER", 2.0], ["FIRE", "WATER", 0.5],
                   ["WATER", "GRASS", 0.5]],
    "species_by_dex": {
        "1": {"name": "CHARMELEON", "type1": "FIRE", "type2": "FIRE", "hp": 58, "atk": 64, "def": 58,
              "spd": 80, "spc": 65, "moves1": ["EMBER"]},
        "2": {"name": "ODDISH", "type1": "GRASS", "type2": "POISON", "hp": 45, "atk": 50, "def": 55,
              "spd": 30, "spc": 75, "moves1": ["VINE WHIP"]},
        "3": {"name": "STARMIE", "type1": "WATER", "type2": "PSYCHIC", "hp": 60, "atk": 75, "def": 85,
              "spd": 115, "spc": 100, "moves1": ["WATER GUN"]},
        "4": {"name": "WEEDLE", "type1": "BUG", "type2": "POISON", "hp": 40, "atk": 35, "def": 30,
              "spd": 50, "spc": 20, "moves1": ["POISON STING"]},
        "5": {"name": "KAKUNA", "type1": "BUG", "type2": "POISON", "hp": 45, "atk": 25, "def": 50,
              "spd": 35, "spc": 25, "moves1": ["HARDEN"]},
        "6": {"name": "RATTATA", "type1": "NORMAL", "type2": "NORMAL", "hp": 30, "atk": 56, "def": 35,
              "spd": 72, "spc": 25, "moves1": ["TACKLE"]},
    },
    "learnsets": {},
}


def _mon(name, level):
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    return Combatant(name, level, tuple(dict.fromkeys((row["type1"], row["type2"]))), hp, st,
                     tuple(row["moves1"]), (8,) * 5, (0,) * 5)


# --- can_damage / lead_order -------------------------------------------------------------------------

def test_can_damage_false_for_a_harden_only_kakuna():
    assert lead.can_damage(_mon("KAKUNA", 5), SYN) is False        # HARDEN has power 0
    assert lead.can_damage(_mon("WEEDLE", 4), SYN) is True         # POISON STING
    assert lead.can_damage(_mon("RATTATA", 3), SYN) is True        # TACKLE


def test_lead_order_puts_the_cocoon_last_and_the_weakest_damaging_member_first():
    levels, fainted = [16, 5, 4], [False] * 3                      # CHARMELEON L16, KAKUNA L5, WEEDLE L4
    assert lead.lead_order(levels, fainted, [True, False, True]) == [2, 0, 1]
    assert lead.lead_order(levels, fainted, None) == team_plan.ascending_order(levels, fainted) == [2, 1, 0]


# --- switch_choice in a wild fight ----------------------------------------------------------------------

def test_wild_switch_fires_for_a_harden_only_active():
    """The fainting wild KAKUNA of 2026-11-14: it cannot damage the foe, so in a wild fight it swaps."""
    team = [_mon("KAKUNA", 5), _mon("CHARMELEON", 16)]
    assert team_plan.switch_choice(team, 0, _mon("RATTATA", 6), SYN, wild=True) == 1


def test_wild_switch_does_not_fire_on_the_weak_ratio_alone():
    """A weak-but-damaging member keeps grinding in a wild fight: the weak-ratio test is trainer-only."""
    team = [_mon("WEEDLE", 8), _mon("CHARMELEON", 16)]
    foe = _mon("KAKUNA", 5)                                        # HARDEN only: it can never KO anybody
    assert team_plan.switch_choice(team, 0, foe, SYN, wild=True) is None
    assert team_plan.switch_choice(team, 0, foe, SYN) == 1         # a trainer fight still reads thin


def test_wild_switch_fires_when_the_foe_kos_inside_switch_hp_turns():
    team = [_mon("CHARMELEON", 15), _mon("ODDISH", 16)]
    hp_now = [10, team[1].hp]                                      # Starmie's hits x2 meet the 10 HP left
    assert team_plan.switch_choice(team, 0, _mon("STARMIE", 21), SYN, hp_now=hp_now, wild=True) == 1


def test_a_switch_in_that_would_faint_on_the_way_in_is_never_picked():
    """Gen 1: the incoming mon takes the foe's attack on the switch turn. The 3-HP WEEDLE (11 max - over
    the 25% floor, so ONLY the survives check rejects it) would be KO'd on the way in; the healthy
    ODDISH goes instead, and with no fit member at all the answer is None."""
    team = [_mon("CHARMELEON", 15), _mon("WEEDLE", 1), _mon("ODDISH", 16)]
    foe = _mon("STARMIE", 21)
    hp_now = [team[0].hp, 3, team[2].hp]
    assert team_plan.switch_choice(team, 0, foe, SYN, hp_now=hp_now) == 2
    assert team_plan.switch_choice(team[:2], 0, foe, SYN, hp_now=hp_now[:2]) is None


# --- trainee safety --------------------------------------------------------------------------------------

def test_the_trainee_below_safe_hp_is_pulled_even_when_not_thin():
    """A designated trainee never stays in to faint: under TRAINEE_SAFE_HP a healthy member comes in even
    though the trainee is winning the exchange - and the member need not beat the damage ask, just be fit."""
    weedle, charmeleon = _mon("WEEDLE", 15), _mon("CHARMELEON", 16)
    team = [weedle, charmeleon]
    foe = _mon("WEEDLE", 3)                                        # frail: the trainee is NOT thin vs it
    low = int(weedle.hp * (team_plan.TRAINEE_SAFE_HP - 0.05))       # ~30%: below the floor
    assert team_plan.switch_choice(team, 0, foe, SYN, hp_now=[low, charmeleon.hp], trainee=0) == 1
    high = int(weedle.hp * 0.6)                                    # 60%: above the floor, not thin: stays
    assert team_plan.switch_choice(team, 0, foe, SYN, hp_now=[high, charmeleon.hp], trainee=0) is None


def test_the_switch_cap_still_applies_in_a_wild_fight():
    team = [_mon("KAKUNA", 5), _mon("CHARMELEON", 16)]
    assert team_plan.switch_choice(team, 0, _mon("RATTATA", 6), SYN, wild=True,
                                   switches=team_plan.MAX_SWITCHES_PER_BATTLE) is None


# --- _matchup_pick on the synthetic ctx (the shape from test_switch_matchup) -------------------------------

def _ctx(team, kind=1, active_hp=None):
    emu = SimpleNamespace()  # every emu-touching helper is patched below
    return SimpleNamespace(bv=SimpleNamespace(kind=kind), battle_log={"matchup_switches": 0},
                           battles=3, train_member=None, emu=emu, switch_gave_up=None,
                           _team=team, _active_hp=active_hp)


def _patch(monkeypatch, ctx, foe):
    team = ctx._team
    monkeypatch.setattr(team_plan, "table", lambda kb, k: SYN.get(k, {}))
    monkeypatch.setattr(so_mod, "our_party", lambda emu: team)
    monkeypatch.setattr(so_mod, "_foe", lambda c: foe)
    monkeypatch.setattr(so_mod, "active_slot", lambda emu: 0)
    hp = [c.hp for c in team]
    if ctx._active_hp is not None:
        hp[0] = ctx._active_hp
    monkeypatch.setattr(so_mod, "read_party", lambda emu: [SimpleNamespace(hp=h) for h in hp])
    monkeypatch.setattr(roster, "trainee_slot", lambda ctx, **kw: None)


def test_matchup_pick_returns_a_pick_in_a_wild_fight(monkeypatch):
    ctx = _ctx([_mon("KAKUNA", 5), _mon("CHARMELEON", 16)], kind=1)
    _patch(monkeypatch, ctx, _mon("RATTATA", 6))
    pick = so_mod.matchup_pick(ctx)
    assert pick is not None and pick[0] == 1                       # the cocoon goes out, the fighter in


def test_matchup_pick_none_outside_a_battle(monkeypatch):
    ctx = _ctx([_mon("KAKUNA", 5), _mon("CHARMELEON", 16)], kind=0)
    _patch(monkeypatch, ctx, _mon("RATTATA", 6))
    assert so_mod.matchup_pick(ctx) is None


def test_matchup_pick_wild_does_not_fire_on_the_weak_ratio_alone(monkeypatch):
    ctx = _ctx([_mon("WEEDLE", 8), _mon("CHARMELEON", 16)], kind=1)
    _patch(monkeypatch, ctx, _mon("KAKUNA", 5))
    assert so_mod.matchup_pick(ctx) is None                        # weak but damaging: the wild grind goes on


# --- battle_switch.yield_to_switch: the behaviour-layer gate that was missing ----------------------------------
#
# CHANGES-NEEDED (PR 281 review): in a real wild Paras L8 fight a non-trainee Rattata went 7 HP -> 2 HP
# -> fainted with no switch, while switch_choice(wild=True) returned Charmeleon for both HP values.
# What blocked it: Battle() runs BEFORE SwitchOut() and its potion / RUN Decisions win every step -
# the old carve-out only yielded for a member with NO damaging move, so a thin member that CAN hurt
# the foe (TACKLE on the Rattata) was potioned and RUN-attempted to death. The yield now also covers
# any member a wild matchup pick would save.


def _patch_yield(monkeypatch, ctx, foe, move_ids=(4,)):
    """_patch plus the battle_switch halves the plain _patch leaves real: the moves table the
    no-damage check reads (SYN) and the battle mon's known move ids (TACKLE by default)."""
    _patch(monkeypatch, ctx, foe)
    monkeypatch.setattr(bs, "table", lambda kb, k: SYN.get(k, {}))
    monkeypatch.setattr(bs, "read_battle_mon", lambda emu: SimpleNamespace(moves=move_ids))


def test_wild_thin_member_yields_the_step_to_switchout(monkeypatch):
    """The Rattata case: it CAN damage (TACKLE), but the foe's hits KO it inside SWITCH_HP_TURNS and a
    healthy Charmeleon answers - the step belongs to SwitchOut, not to a potion or a RUN."""
    ctx = _ctx([_mon("RATTATA", 8), _mon("CHARMELEON", 16)], kind=1, active_hp=4)
    _patch_yield(monkeypatch, ctx, _mon("ODDISH", 21))
    assert bs.yield_to_switch(ctx, 1, want_potion=True) is True
    assert bs.yield_to_switch(ctx, 1, want_potion=False) is True    # the RUN attempt yields the same way


def test_wild_member_that_cannot_damage_yields_via_the_healthy_candidate_rule(monkeypatch):
    """The original carve-out still holds: a Harden-only KAKUNA with any healthy member behind it."""
    ctx = _ctx([_mon("KAKUNA", 5), _mon("CHARMELEON", 16)], kind=1)
    _patch_yield(monkeypatch, ctx, _mon("RATTATA", 6), move_ids=(5,))
    monkeypatch.setattr(bs, "switch_candidate", lambda emu, t: 1)
    assert bs.yield_to_switch(ctx, 1, want_potion=False) is True


def test_no_yield_in_a_wild_fight_when_nobody_needs_saving(monkeypatch):
    ctx = _ctx([_mon("RATTATA", 8), _mon("CHARMELEON", 16)], kind=1)
    _patch_yield(monkeypatch, ctx, _mon("KAKUNA", 5))               # HARDEN only: nobody is thin
    assert bs.yield_to_switch(ctx, 1, want_potion=True) is False    # potion/flee rules exactly as before


def test_a_trainer_fight_keeps_the_no_damage_only_yield(monkeypatch):
    """The matchup branch is wild-only: in a trainer fight a damaging member still takes its potion
    (no fleeing anyway) - only a member with no damaging move yields there."""
    ctx = _ctx([_mon("RATTATA", 8), _mon("CHARMELEON", 16)], kind=2, active_hp=4)
    _patch_yield(monkeypatch, ctx, _mon("STARMIE", 21))
    assert bs.yield_to_switch(ctx, 2, want_potion=True) is False


def test_no_yield_once_the_switch_menus_gave_up(monkeypatch):
    """After a gave_up the normal rules take over again - otherwise the member could neither switch
    nor be healed/run for the rest of the battle."""
    ctx = _ctx([_mon("RATTATA", 8), _mon("CHARMELEON", 16)], kind=1, active_hp=4)
    _patch_yield(monkeypatch, ctx, _mon("ODDISH", 21))
    ctx.switch_gave_up = ctx.battles
    assert bs.yield_to_switch(ctx, 1, want_potion=True) is False


# --- Battle().step end to end (the FakeEmulator harness from test_train_fight) ---------------------------------

RAT, CHAR, FOE = 0xA5, 0xB0, 0x6D                                  # internal species ids (nonzero; real id is unused)


def _wild_ctx(tmp_path, monkeypatch, reserve_hp=40):
    """A wild fight (kind 1) with a weak RATTATA out (4/23) and a reserve behind it - the same shape as
    test_train_fight.wild, which ends in a flee_run press when nothing vetoes it."""
    from test_explorer_behaviours import BATTLE, make_ctx, put_box
    from test_magikarp import party_mem
    mem = party_mem([(RAT, 8, 4, 23), (CHAR, 16, reserve_hp, 40)])
    mem.update({0xD014: RAT, 0xD015: 0, 0xD016: 4, 0xD01C: 4, 0xD022: 8, 0xD023: 0, 0xD024: 23,
                0xCFE5: FOE, 0xCFF3: 8, 0xCC2F: 0, BATTLE: 1})   # Rattata out at 4/23, wild L8 foe, slot 0 verified
    ctx = make_ctx(tmp_path, memory=mem)
    put_box(ctx, menu=True, text_rows=(" RUN",))
    monkeypatch.setattr(team_plan, "table", lambda kb, k: SYN.get(k, {}))
    monkeypatch.setattr(so_mod, "_foe", lambda c: _mon("ODDISH", 21))   # KOs the 4 HP lead; Ember answers it 2x
    monkeypatch.setattr(roster, "trainee_slot", lambda *a, **k: None)
    monkeypatch.setattr(bs, "table", lambda kb, k: SYN.get(k, {}))
    ctx.refresh()
    return ctx


def test_battle_step_yields_a_wild_fight_to_switchout(monkeypatch, tmp_path):
    """Before the fix this exact fixture ended in 'flee_run' - Battle's flee answer won the step and
    SwitchOut was never asked (the Rattata vs Paras review case)."""
    from pokeagent.explorer.behaviours import Battle
    ctx = _wild_ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(so_mod, "our_party", lambda emu: [_mon("RATTATA", 8), _mon("CHARMELEON", 16)])
    assert Battle().step(ctx) is None and ctx.bv is not None and ctx.bv.kind == 1
    pick = so_mod.matchup_pick(ctx)
    assert pick is not None and pick[0] == 1                       # the healthy Charmeleon SwitchOut sends in


def test_battle_step_still_flees_when_no_member_is_a_fit_switch(monkeypatch, tmp_path):
    """A fit switch-in is the condition for yielding: a lone weak member still gets the flee answer."""
    from pokeagent.explorer.behaviours import Battle
    ctx = _wild_ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(so_mod, "our_party", lambda emu: [_mon("RATTATA", 8)])   # nobody to switch to
    dec = Battle().step(ctx)
    assert dec is not None and dec.rule == "flee_run"
