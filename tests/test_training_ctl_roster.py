"""Training controller slice 4 (Roster): roster.trainee_slot is the one trainee-selection owner."""
from __future__ import annotations

import inspect
import subprocess
import sys
from types import SimpleNamespace

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import grind_episode, trainee_gate
from pokeagent.explorer.behaviours import catch as catch_behav
from pokeagent.explorer.behaviours import switch_out as so_mod
from pokeagent.explorer.training_ctl import roster
from pokeagent.knowledge import team_plan
from pokeagent.magikarp import MAGIKARP, trainee_slot_for
from test_magikarp import party_mem


def _ctx(emu, train_member=None, step=100):
    return SimpleNamespace(emu=emu, train_member=train_member, step=step)


def test_roster_trainee_slot_equals_trainee_slot_for():
    karp = FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (0xB1, 18, 51, 51)]))
    ctx = _ctx(karp, 1)
    assert roster.trainee_slot(ctx) == trainee_slot_for(karp, 1) == 0          # the Magikarp always wins

    weak = FakeEmulator(party_mem([(0xB1, 30, 79, 79), (0x54, 9, 20, 20)]))
    ctx = _ctx(weak, 1)
    assert roster.trainee_slot(ctx) == trainee_slot_for(weak, 1) == 1          # the named weak member
    ctx = _ctx(weak, None)
    assert roster.trainee_slot(ctx) == trainee_slot_for(weak, None) is None    # nobody named, no breakers

    team_plan.of(ctx)["breakers"] = (1,)
    assert roster.trainee_slot(ctx, breakers=True) == trainee_slot_for(weak, None, (1,)) == 1
    assert roster.trainee_slot(ctx) is None                                    # breakers=False: the old read


def test_migrated_modules_do_not_mention_trainee_slot_for():
    for mod in (catch_behav, so_mod, grind_episode, trainee_gate):
        assert "trainee_slot_for" not in inspect.getsource(mod), mod.__name__


def test_roster_and_its_callers_import_in_a_fresh_process():
    # behaviours.* first: trainee_gate -> heal_walk -> behaviours/__init__ -> grind_drill -> trainee_gate
    # is a pre-existing cycle on main; it only bites when trainee_gate is imported before behaviours.
    r = subprocess.run([sys.executable, "-c",
                        "import pokeagent.explorer.behaviours.catch, pokeagent.explorer.behaviours.switch_out, "
                        "pokeagent.explorer.training_ctl.roster, pokeagent.explorer.grind_episode, "
                        "pokeagent.explorer.trainee_gate"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
