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
    assert r["bench_xp_total"] == 0 and r["bench_xp_per_1k_run_steps"] == 0.0
    assert r["second_member_l9_step"] is None and r["walk_to_grass_per_episode"] == 0.0


def test_slice3_rows_bench_xp_l9_and_walk_to_grass(tmp_path):
    """bench xp = non-lead per-species exp deltas over run steps; L9 = first step with one more member >= L9 than at the start;
    walk-to-grass lines inside an episode's start -> first-BATTLE window count separately."""
    _jl(tmp_path / "levels.jsonl", [{"step": 1, "party": [[1, 5, 100, 1, 1], [2, 6, 50, 1, 1]]},
                                    {"step": 2, "party": [[2, 6, 60, 1, 1], [1, 5, 140, 1, 1]]},   # reordered: species-keyed
                                    {"step": 3, "party": [[2, 6, 70, 1, 1], [1, 5, 180, 1, 1], [3, 9, 10, 1, 1]]},
                                    {"step": 4, "party": [[2, 9, 80, 1, 1], [1, 9, 200, 1, 1], [3, 9, 20, 1, 1]]}])
    walk = lambda n, i: f"thinking: goal team_ready: {n - i} steps to Route 24's grass\n"
    (tmp_path / "console.log").write_text(
        block(1, 0x23, "goal team_ready: 70 steps to Route 24's grass")          # outside any episode: total only
        + "[grind episode] start on ROUTE_24: trainee L5 -> L15\n"
        + "".join(walk(56, i) for i in range(56))                              # a 56-line episode walk
        + "thinking: BATTLE vs RATTATA: FIGHT with TACKLE\n"                     # the window closes
        + "thinking: goal team_ready: 4 steps to Route 24's grass\n"             # mid-episode: total only
        + "[grind episode] start on ROUTE_24: trainee L5 -> L15\n"
        + "".join(walk(3, i) for i in range(3)))                               # a 3-line walk, still open at EOF
    r = step_budget.run_rows(tmp_path)
    # species deltas: 1: +40+40+20=100 (lead, excluded), 2: +10*3=30, 3: +10 -> bench 40 over 4 steps
    assert r["bench_xp_total"] == 40 and r["bench_xp_per_1k_run_steps"] == 10000.0
    assert r["second_member_l9_step"] == 3            # start: 0 at L9; step 3 has one (species 3 at L9)
    assert r["walk_to_grass_lines"] == 61             # every walk line, inside windows or not
    assert r["walk_to_grass_after_episode_start"] == 59 and r["walk_to_grass_per_episode"] == 29.5


def test_second_member_l9_is_relative_to_the_start():
    """heal_cerulean starts with three members at L9+: the row must wait for a fourth, not read 0."""
    rows = [{"step": 0, "party": [[1, 23, 0, 1, 1], [2, 9, 0, 1, 1], [3, 9, 0, 1, 1], [4, 8, 0, 1, 1]]},
            {"step": 50, "party": [[1, 24, 0, 1, 1], [2, 9, 0, 1, 1], [3, 9, 0, 1, 1], [4, 8, 0, 1, 1]]},
            {"step": 90, "party": [[1, 24, 0, 1, 1], [2, 9, 0, 1, 1], [3, 9, 0, 1, 1], [4, 9, 0, 1, 1]]}]
    assert step_budget.second_member_l9_step(rows) == 90
    assert step_budget.second_member_l9_step(rows[:2]) is None


def test_bench_xp_duplicate_species_and_catch():
    """Two members of one species (KAKUNA 113) must not alternate-count; a catch / deposit jump is skipped; negatives ignored."""
    rows = [{"step": 1, "party": [[113, 9, 500, 1, 1], [113, 7, 100, 1, 1], [20, 6, 50, 1, 1]]},
            {"step": 2, "party": [[20, 6, 60, 1, 1], [113, 7, 100, 1, 1], [113, 9, 530, 1, 1]]},   # reorder; lead +30 (excluded), RATTATA +10
            {"step": 3, "party": [[113, 7, 130, 1, 1], [20, 6, 60, 1, 1], [113, 9, 530, 1, 1]]},     # second KAKUNA +30
            {"step": 4, "party": [[113, 7, 130, 1, 1], [20, 6, 60, 1, 1], [113, 9, 530, 1, 1], [19, 3, 900, 1, 1]]},  # catch: skipped
            {"step": 5, "party": [[113, 7, 130, 1, 1], [20, 6, 60, 1, 1], [113, 9, 530, 1, 1]]},      # deposit: skipped
            {"step": 6, "party": [[113, 7, 120, 1, 1], [20, 6, 60, 1, 1], [113, 9, 560, 1, 1]]}]      # negative bench delta: ignored
    assert step_budget.bench_xp(rows) == 40
