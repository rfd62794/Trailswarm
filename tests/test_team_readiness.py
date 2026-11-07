"""Team readiness: the whole party vs the boss (hurt-lead sim), the gyarados ladder goal, the training-gate
level seam, and who the switch-training targets."""
from __future__ import annotations

from pokeagent import campaign
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.perceive import lead_level
from pokeagent.explorer.stats import stat_value
from pokeagent.goals import GOALS, SIDE_GOALS, check_goals
from pokeagent.knowledge.party import Combatant
from pokeagent.knowledge.readiness import TEAM_GAP, team_readiness
from pokeagent.magikarp import GYARADOS, MAGIKARP, trainee_slot_for
from test_magikarp import party_mem


def _mv(name, typ, power, acc=1.0, effect=0):
    return {"name": name, "type": typ, "power": power, "accuracy": acc, "effect": effect, "pp": 20}


def _species(name, t1, t2, hp, atk, dfn, spd, spc, moves1):
    return {"name": name, "type1": t1, "type2": t2, "hp": hp, "atk": atk, "def": dfn, "spd": spd, "spc": spc, "moves1": moves1}


# The test_knowledge.SYN cartridge plus the trainee pair and a bulky WATER boss for the hurt-lead case.
SYN = {
    "moves": {"1": _mv("TACKLE", "NORMAL", 35, 0.95), "2": _mv("WATER GUN", "WATER", 40), "3": _mv("EMBER", "FIRE", 40, effect=4)},
    "type_chart": [["WATER", "ROCK", 2.0], ["WATER", "GROUND", 2.0], ["FIRE", "ROCK", 0.5], ["WATER", "WATER", 0.5]],
    "species_by_dex": {"1": _species("AQUA", "WATER", "WATER", 44, 48, 65, 43, 50, ["TACKLE"]),
                       "2": _species("BLAZE", "FIRE", "FIRE", 44, 48, 65, 43, 50, ["TACKLE"]),
                       "3": _species("PEBBLE", "ROCK", "GROUND", 40, 80, 100, 20, 30, ["TACKLE"]),
                       "4": _species("MAGIKARP", "WATER", "WATER", 15, 5, 40, 50, 10, ["TACKLE"]),
                       "5": _species("GYARADOS", "WATER", "FLYING", 95, 125, 79, 81, 100, ["TACKLE"]),
                       "6": _species("TURTLE", "WATER", "WATER", 100, 60, 90, 60, 60, ["TACKLE"])},
    "learnsets": {"AQUA": {"learnset": [[8, "WATER GUN"]]}, "BLAZE": {"learnset": [[8, "EMBER"]]}, "PEBBLE": {"learnset": []},
                  "MAGIKARP": {"learnset": []}, "GYARADOS": {"learnset": [[20, "WATER GUN"]]}, "TURTLE": {"learnset": []}},
}

BOSS = [(12, "PEBBLE"), (14, "PEBBLE")]   # a synthetic two-mon boss
TANK = [(20, "TURTLE")]                   # bulky enough that the half-HP lead loses where the full one wins


def _mon(name, level, moves=None):
    """A Combatant built like test_knowledge._starter, for any species in this file's SYN."""
    row = next(r for r in SYN["species_by_dex"].values() if r["name"] == name)
    hp = stat_value(row["hp"], 8, 0, level, hp=True)
    st = tuple(stat_value(row[k], 8, 0, level) for k in ("atk", "def", "spd", "spc"))
    types = tuple(dict.fromkeys((row["type1"], row["type2"])))
    return Combatant(name, level, types, hp, st, tuple(moves if moves is not None else row["moves1"]), (8,) * 5, (0,) * 5)


# --- the party verdict -------------------------------------------------------------------------------------------

def test_weak_second_member_names_the_trainee_shortfall():
    t = team_readiness([_mon("AQUA", 30), _mon("MAGIKARP", 13)], BOSS, "TWO-MON", SYN)
    assert t is not None and t.ready is False
    assert t.weakest is not None and t.weakest.name == "MAGIKARP" and t.weakest.useful is False
    assert t.weakest.target >= 20 and t.weakest.target >= 30 - TEAM_GAP
    assert t.text.startswith("team not ready vs TWO-MON: MAGIKARP L13 -> L")


def test_strong_second_member_makes_the_team_ready():
    t = team_readiness([_mon("AQUA", 30), _mon("BLAZE", 28)], BOSS, "TWO-MON", SYN)
    assert t is not None and t.ready is True and t.weakest is None
    assert all(m.useful for m in t.members)
    assert t.text == "team ready vs TWO-MON: lead L30, 2/2 useful"


def test_one_mon_and_empty_inputs():
    t = team_readiness([_mon("AQUA", 30)], BOSS, "TWO-MON", SYN)
    assert t is not None and t.ready is False and t.weakest is None
    assert "no second member" in t.text
    assert team_readiness([], BOSS, "X", SYN) is None
    assert team_readiness([_mon("AQUA", 30)], [], "X", SYN) is None


def test_hurt_lead_sim_fails_where_the_full_lead_wins():
    t = team_readiness([_mon("AQUA", 30), _mon("MAGIKARP", 13)], TANK, "TANK", SYN)
    assert t is not None and t.lead is not None and t.lead.ready is True   # assess passes at full HP ...
    assert t.ready is False                                                # ... but the half-HP lead loses and the trainee cannot fight


def test_evolved_magikarp_is_judged_as_gyarados():
    t = team_readiness([_mon("AQUA", 26), _mon("MAGIKARP", 22)], BOSS, "TWO-MON", SYN)
    assert t is not None
    karp = next(m for m in t.members if m.name == "MAGIKARP")
    assert karp.useful is True   # L22 >= EVOLVE_LEVEL: the GYARADOS projection carries the hurt-lead sim


# --- the gyarados ladder goal ------------------------------------------------------------------------------------

def test_gyarados_detector_never_blocks():
    assert GOALS.index("gyarados") == GOALS.index("nugget_bridge") + 1
    assert GOALS.index("to_bill") == GOALS.index("gyarados") + 1
    assert "gyarados" not in SIDE_GOALS
    assert campaign.selectable("gyarados")   # the segment picker may target it: nugget_bridge -> gyarados
    st: dict = {}
    emu = FakeEmulator(party_mem([(0xB1, 14, 30, 30), (GYARADOS, 20, 60, 60)]))
    assert check_goals(emu, st)["gyarados"]                       # owned -> met
    emu.memory.update(party_mem([(0xB1, 14, 30, 30)]))
    assert check_goals(emu, st)["gyarados"]                       # sticky: stays met once seen this run
    assert check_goals(FakeEmulator(party_mem([(0xB1, 14, 30, 30)])), {})["gyarados"]       # never owned a Magikarp -> settled
    karp = FakeEmulator(party_mem([(0xB1, 14, 30, 30), (MAGIKARP, 5, 17, 17)]))
    assert not check_goals(karp, {})["gyarados"]                  # a Magikarp in the party: the goal is open
    assert check_goals(karp, {"gyarados_skipped": True})["gyarados"]  # ... unless the stage's step cap ran out


# --- the training-gate seam and the switch-training target --------------------------------------------------------

def test_lead_level_drops_to_the_trainee_band_while_a_magikarp_is_in_the_party():
    emu = FakeEmulator(party_mem([(MAGIKARP, 13, 17, 17), (179, 30, 82, 82)]))
    assert lead_level(emu) == min(30, 13 + TEAM_GAP) == 19
    emu.memory.update(party_mem([(GYARADOS, 30, 82, 82), (179, 30, 82, 82)]))
    assert lead_level(emu) == 30                                    # evolved: slot 0's level, as before
    assert lead_level(FakeEmulator(party_mem([(179, 30, 82, 82), (0x54, 9, 20, 20)]))) == 30  # no Magikarp: unchanged


def test_trainee_slot_for_follows_the_magikarp_then_the_named_member():
    karp = FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (0xB1, 18, 51, 51)]))
    assert trainee_slot_for(karp, 1) == 0 and trainee_slot_for(karp, None) == 0   # the Magikarp always wins
    weak = FakeEmulator(party_mem([(0xB1, 30, 79, 79), (0x54, 9, 20, 20)]))
    assert trainee_slot_for(weak, 1) == 1          # slot 1 is TEAM_GAP+ below the lead
    close = FakeEmulator(party_mem([(0xB1, 30, 79, 79), (0x54, 25, 60, 60)]))
    assert trainee_slot_for(close, 1) is None      # within the gap: already useful
    assert trainee_slot_for(weak, 0) is None       # the lead itself is never the trainee
    assert trainee_slot_for(weak, 2) is None       # out of range
    assert trainee_slot_for(weak, None) is None    # nobody named
