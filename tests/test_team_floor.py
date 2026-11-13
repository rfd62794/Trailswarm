"""team_floor: the per-checkpoint team level floor is the second half of the ONE gym verdict (sim AND floor).
Synthetic kb (no ROM), the test_team_plan cartridge."""
from __future__ import annotations

from pokeagent.explorer import training
from pokeagent.knowledge import team_floor, team_plan
from test_team_plan import SYN, _mon

BOSS = [(18, "STARYU"), (21, "STARMIE")]


class _Ctx:
    floor_note = ""

    def __init__(self):
        self.logs = []

    def log(self, msg, *_):
        self.logs.append(msg)


def _need(party):
    return team_plan.boss_need(party, BOSS, SYN, "MISTY")


def _floor(party, level=19):
    team_floor.FLOOR_BY_GOAL["beat_misty"] = level
    return team_floor.check("beat_misty", party, BOSS, SYN)


STRONG = [_mon("STARMIE", 30), _mon("CHARMELEON", 30), _mon("RATTATA", 5)]   # sim passes; two members >= L19
SIM_OK_FLOOR_BAD = [_mon("STARMIE", 40), _mon("RATTATA", 8), _mon("PIDGEY", 9)]  # one L40 carry wins alone, nobody else near
SIM_BAD_FLOOR_OK = [_mon("RATTATA", 19), _mon("PIDGEY", 19), _mon("WEEDLE", 19)]  # three at the floor; none can beat Starmie


def test_sim_passes_floor_fails_is_held():
    nv, fl = _need(SIM_OK_FLOOR_BAD), _floor(SIM_OK_FLOOR_BAD)
    assert nv.ready and fl is not None and not fl.met
    assert team_floor.ready(nv, fl) is False
    assert fl.text == "team floor for beat_misty: need 2 members >= L19, have 1"


def test_floor_passes_sim_fails_is_held():
    nv, fl = _need(SIM_BAD_FLOOR_OK), _floor(SIM_BAD_FLOOR_OK)
    assert not nv.ready and fl is not None and fl.met
    assert team_floor.ready(nv, fl) is False


def test_both_pass_is_ready():
    nv, fl = _need(STRONG), _floor(STRONG)
    assert nv.ready and fl.met and team_floor.ready(nv, fl) is True


def test_no_floor_data_leaves_the_sim_alone():
    assert team_floor.ready(_need(STRONG), None) is True
    assert team_floor.check("to_mt_moon", STRONG, BOSS, SYN) is None


def test_weak_slot0_does_not_gate_when_others_meet_floor():
    party = [_mon("RATTATA", 4), _mon("STARMIE", 30), _mon("CHARMELEON", 30)]   # slot 0 is the weakest, as the party is ordered
    nv, fl = _need(party), _floor(party)
    assert nv.ready and fl.met and nv.lead_slot != 0
    assert team_floor.ready(nv, fl) is True


def test_no_single_member_level_gates_a_gym():
    """The verdict is the whole-party fight: swapping which slot holds the strong mon does not change it."""
    a, b = [_mon("RATTATA", 4), _mon("STARMIE", 30)], [_mon("STARMIE", 30), _mon("RATTATA", 4)]
    assert _need(a).ready == _need(b).ready is True
    assert _need([_mon("RATTATA", 4)]).ready is False


def test_floor_target_never_an_unsendable_member():
    useless = _mon("WEEDLE", 17, moves=())
    party = [_mon("STARMIE", 30), useless, _mon("RATTATA", 12), _mon("MAGIKARP", 18)]
    fl = _floor(party)
    assert not fl.met and fl.target_slot == 2   # RATTATA: the sendable member closest below; not the L17 mover-less WEEDLE or the Magikarp
    assert team_floor.sendable_slots(party, BOSS, SYN) == [0, 2]


def test_floor_capped_at_sendable_members():
    party = [_mon("STARMIE", 30), _mon("WEEDLE", 5, moves=())]
    fl = _floor(party)
    assert fl.met and fl.need == 1   # nothing else can be trained: do not hold on a floor no one can fix


def test_gate_state_logs_reason_once_and_trains_floor_target(monkeypatch):
    monkeypatch.setattr(training, "floor_for", lambda g, p: _floor(SIM_OK_FLOOR_BAD))
    ctx, nv = _Ctx(), _need(SIM_OK_FLOOR_BAD)
    slot, ready = training.gate_state(ctx, {}, SIM_OK_FLOOR_BAD, nv, None)
    assert ready is False and slot in (1, 2) and SIM_OK_FLOOR_BAD[slot].level < 19
    training.gate_state(ctx, {}, SIM_OK_FLOOR_BAD, nv, None)
    assert [m for m in ctx.logs if m.startswith("[readiness] team floor for beat_misty")] == [
        "[readiness] team floor for beat_misty: need 2 members >= L19, have 1"]
