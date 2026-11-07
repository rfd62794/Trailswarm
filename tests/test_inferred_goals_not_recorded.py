"""An unverified goal is inferred from later goals; record_goals must not write a goal_frames line, checkpoint or milestone for it."""
import json
from types import SimpleNamespace

from pokeagent import campaign
from pokeagent.explorer import press_goals
from pokeagent.goals import GOALS


class FakeEmu:
    def save_state(self, path):
        open(path, "wb").write(b"s")

    def read(self, addr):
        return 0


def test_inferred_unverified_goals_get_no_record(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    unverified = [g for g in GOALS if campaign.is_unverified(g)]
    real = next(g for g in GOALS if not campaign.is_unverified(g) and GOALS.index(g) > GOALS.index(unverified[0]))
    state = {g: False for g in GOALS}
    state[real] = state[unverified[0]] = True            # the later real goal is reached; the inference marks the earlier one too
    monkeypatch.setattr(press_goals, "check_goals", lambda emu, ctx: dict(state))
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text("{}")
    logs = []
    ctx = SimpleNamespace(emu=FakeEmu(), run_dir=run, step=7, frame=70, goal_steps={}, initial_goals=set(), initial_goals_ready=True,
                          goal_left_house=False, log=lambda m, t=None: logs.append(m),
                          opts=SimpleNamespace(state_stem="", stop_at_goal=None, stop_at_map=None, headless=False, starter="x"))
    fr = SimpleNamespace(goals=None)
    press_goals.record_goals(ctx, fr)
    lines = [json.loads(x) for x in (run / "goal_frames.jsonl").read_text().splitlines()]
    assert [r["goal"] for r in lines] == [real]
    assert (tmp_path / "runs/checkpoints" / f"{real}.state").exists() and not (tmp_path / "runs/checkpoints" / f"{unverified[0]}.state").exists()
    assert set(json.loads((tmp_path / "runs/milestones.json").read_text())) == {real}
    assert fr.goals[unverified[0]] is True               # the in-memory inference for the ladder stays
    assert unverified[0] not in ctx.goal_steps
