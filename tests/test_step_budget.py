"""tools/step_budget.py on a synthetic console.log, and LoopGuard's training-pace exemption."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import step_budget  # noqa: E402

from pokeagent.explorer.behaviours import grind_loop  # noqa: E402


def block(step, m, why):
    return f"--- step {step}/12000  map=0x{m:02x} pos=(1,2) party=2 badges=1 battle=no money=1\nthinking: {why}\nbutton:   UP\n"


def test_budget_counts_activities_and_maps(tmp_path):
    log = tmp_path / "console.log"
    log.write_text(
        block(1, 0x23, "BATTLE vs RATTATA: FIGHT with TACKLE")
        + block(2, 0x23, "BATTLE vs RATTATA: FIGHT with TACKLE")
        + block(3, 0x03, "goal team_ready: 12 steps to Route 24's grass to train the trainee")
        + block(4, 0x40, "to the Pokecenter to heal")
        + block(5, 0x23, "SHAKE: breaking a loop with a random walk UP (3 left)")
        + block(6, 0x23, "shake: closing a box (2 left)")
        + block(7, 0x23, "a text box is open"))
    b = step_budget.budget(log)
    assert b["steps"] == 7
    a = b["activities"]
    assert a["BATTLE ... FIGHT"] == 2 and a["SHAKE random walk"] == 1 and a["shake: closing a box"] == 1
    assert a["to the Pokecenter to heal"] == 1 and a["walking to grass (goal team_ready)"] == 1
    assert b["maps"] == {"0x23": 5, "0x03": 1, "0x40": 1}
    assert "| Route" not in step_budget.render(b) and "BATTLE ... FIGHT | 2" in step_budget.render(b)


def test_main_missing_log(tmp_path):
    assert step_budget.main([str(tmp_path)]) == 2


class Ctx:
    def __init__(self, live):
        self.train_route_live, self.battles = live, 0


def feed(ctx, n, battle_at=None):
    for i in range(n):
        if i == battle_at:
            ctx.battles += 1
        grind_loop.note_step(ctx)


def test_pace_with_a_battle_is_training_not_a_loop():
    c = Ctx(True)
    feed(c, 60, battle_at=30)
    assert grind_loop.paced_in_training(c)


def test_pace_without_a_battle_still_shakes():
    c = Ctx(True)
    feed(c, 60)
    assert not grind_loop.paced_in_training(c)


def test_not_training_never_exempt():
    c = Ctx(False)
    feed(c, 60, battle_at=30)
    assert not grind_loop.paced_in_training(c)


def test_old_battle_outside_window_does_not_count():
    c = Ctx(True)
    feed(c, 10, battle_at=0)
    feed(c, 60)
    assert not grind_loop.paced_in_training(c)
