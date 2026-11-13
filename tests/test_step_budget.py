"""tools/step_budget.py on a synthetic console.log, and LoopGuard's training-pace exemption."""
from __future__ import annotations

import json
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


def _jl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_training_controller_rows_on_a_synthetic_run(tmp_path):
    dec = [{"step": s, "rule": "reorder_party: X", "map": 0x40} for s in (10, 12, 15)]       # gaps 2, 3: one session
    dec += [{"step": 40, "rule": "reorder_party: X", "map": 35}, {"step": 90, "rule": "plan_goal", "map": 35}]
    _jl(tmp_path / "decisions.jsonl", dec)
    (tmp_path / "console.log").write_text(
        "[grind episode] start on VIRIDIAN_FOREST: trainee L5\n[grind episode] start on VIRIDIAN_FOREST: x\n"
        "[grind episode] start on ROUTE_24: y\n" + block(1, 0x23, "SHAKE"))
    _jl(tmp_path / "levels.jsonl", [{"step": 5, "party": [[1, 8, 0, 1, 1], [2, 10, 0, 1, 1]], "blackouts": 0},
                                    {"step": 70, "party": [[1, 19, 0, 1, 1]], "blackouts": 2}])
    _jl(tmp_path / "xp_rates.jsonl", [{"kind": "window", "map": 35, "xp_per_1k_steps": 1.0},
                                      {"kind": "map_summary", "map": 35, "xp_per_1k_steps": 210.5}])
    r = step_budget.run_rows(tmp_path)
    assert (r["reorder_sessions"], r["reorder_lines"], r["reorder_in_pokecenter"]) == (2, 4, 1)
    assert r["episode_starts"] == {"VIRIDIAN_FOREST": 2, "ROUTE_24": 1}
    assert r["blackouts"] == 2 and r["route24_xp_per_1k"] == 210.5
    assert r["floor_first_step"]["0:19"] == 70 and r["floor_first_step"]["1:10"] == 5


def test_run_rows_tolerate_missing_files_and_torn_lines(tmp_path):
    (tmp_path / "decisions.jsonl").write_text('{"step": 1, "rule": "reorder_party"}\n{"step": 2, "ru')
    r = step_budget.run_rows(tmp_path)
    assert r["reorder_sessions"] == 1 and r["episode_starts"] == {} and r["route24_xp_per_1k"] == 0.0
