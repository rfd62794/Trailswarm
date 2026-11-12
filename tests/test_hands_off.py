"""Hands-off regression checker, synthetic only: no emulator, no ROM, no real subprocess."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent.review.hands_off import judge_run
from pokeagent.review.hands_off_cases import Case, build_argv, load_cases, skip_reason

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("hands_off_check", ROOT / "tools" / "hands_off_check.py")
tool = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tool
_spec.loader.exec_module(tool)

CASE = Case(name="red_bedroom_potion_cold", game="red", state="bedroom", memory="none",
            goal="potion", budget=105, seed=42)


def make_run(base: Path, sources=("agent",) * 35, goal_step: int | None = 35, goal="potion",
             initial_goals=(), name="explore-X", extra_transition_lines=()) -> Path:
    """A synthetic run dir: one transitions row per entry of ``sources`` (None = no source key)."""
    run = base / name
    run.mkdir(parents=True)
    trans, decs = [], []
    for i, src in enumerate(sources, 1):
        row = {"step": i, "from": [38, 4, 6], "button": "A", "to": [38, 4, 6], "moved": False,
               "textbox": "none", "text": "", "facing": "DOWN"}
        if src is not None:
            row["source"] = src
        trans.append(json.dumps(row))
        if src == "agent":
            decs.append(json.dumps({"step": i, "behaviour": "procedures", "rule": "procedure_step",
                                    "button": "A", "goal_stage": goal}))
    (run / "transitions.jsonl").write_text("\n".join([*trans, *extra_transition_lines]) + "\n", encoding="utf-8")
    decs.append(json.dumps({"event": "bandit", "step": 1}))
    (run / "decisions.jsonl").write_text("\n".join(decs) + "\n", encoding="utf-8")
    frames = [] if goal_step is None else [json.dumps({"goal": goal, "step": goal_step, "frame": 4210})]
    (run / "goal_frames.jsonl").write_text("".join(f + "\n" for f in frames), encoding="utf-8")
    (run / "meta.json").write_text(json.dumps({"initial_goals": list(initial_goals)}), encoding="utf-8")
    return run


def _with(sources, at: dict):
    s = list(sources)
    for step, src in at.items():
        s[step - 1] = src
    return s


AGENT35 = ("agent",) * 35


# --- judge_run ------------------------------------------------------------------------------------

def test_clean_agent_run_passes(tmp_path):
    v = judge_run(make_run(tmp_path), "potion", 105)
    assert v.passed is True
    assert v.reasons == []
    assert v.goal_step == 35
    assert v.presses == 35
    assert v.non_agent == 0


def test_goal_at_budget_boundary_passes(tmp_path):
    v = judge_run(make_run(tmp_path, goal_step=105), "potion", 105)
    assert v.passed and v.goal_step == 105


def test_goal_one_past_budget_fails(tmp_path):
    v = judge_run(make_run(tmp_path, goal_step=106), "potion", 105)
    assert not v.passed
    assert len(v.reasons) == 1 and v.reasons[0].startswith("too slow")


def test_too_slow_names_step_and_budget(tmp_path):
    v = judge_run(make_run(tmp_path, goal_step=140), "potion", 105)
    assert not v.passed
    assert v.reasons == ["too slow: potion at step 140, budget 105"]
    assert v.goal_step == 140


def test_one_human_press_fails_even_in_budget(tmp_path):
    v = judge_run(make_run(tmp_path, sources=_with(AGENT35, {12: "human"})), "potion", 105)
    assert not v.passed
    assert v.non_agent == 1
    assert v.reasons == ["1 non-agent presses (human) at steps 12"]


def test_claude_press_fails(tmp_path):
    v = judge_run(make_run(tmp_path, sources=_with(AGENT35, {3: "claude"})), "potion", 105)
    assert not v.passed and v.non_agent == 1
    assert "claude" in v.reasons[0] and "3" in v.reasons[0]


def test_row_without_source_fails(tmp_path):
    v = judge_run(make_run(tmp_path, sources=_with(AGENT35, {7: None})), "potion", 105)
    assert not v.passed and v.non_agent == 1
    assert "missing" in v.reasons[0] and "7" in v.reasons[0]


def test_non_agent_reason_lists_sources_and_first_five_steps(tmp_path):
    srcs = _with(AGENT35, {2: "human", 4: "human", 6: "claude", 8: "human", 10: "human", 12: "human"})
    v = judge_run(make_run(tmp_path, sources=srcs), "potion", 105)
    assert v.reasons == ["6 non-agent presses (human, claude) at steps 2, 4, 6, 8, 10"]


def test_missing_transitions_fails(tmp_path):
    run = make_run(tmp_path)
    (run / "transitions.jsonl").unlink()
    v = judge_run(run, "potion", 105)
    assert not v.passed and v.presses == 0
    assert v.reasons == ["transitions.jsonl missing or empty"]


def test_empty_transitions_fails(tmp_path):
    run = make_run(tmp_path)
    (run / "transitions.jsonl").write_text("", encoding="utf-8")
    v = judge_run(run, "potion", 105)
    assert v.reasons == ["transitions.jsonl missing or empty"]


def test_missing_goal_frames_fails(tmp_path):
    run = make_run(tmp_path)
    (run / "goal_frames.jsonl").unlink()
    v = judge_run(run, "potion", 105)
    assert not v.passed and v.goal_step is None
    assert v.reasons == ["goal_frames.jsonl missing"]


def test_goal_never_reached_fails(tmp_path):
    v = judge_run(make_run(tmp_path, goal_step=None), "potion", 105)
    assert v.reasons == ["goal potion never reached"]


def test_goal_in_initial_goals_reason(tmp_path):
    v = judge_run(make_run(tmp_path, goal_step=None, initial_goals=["potion"]), "potion", 105)
    assert not v.passed
    assert v.reasons == ["goal potion was already true at the start state (initial_goals)"]


def test_non_integer_goal_step_fails(tmp_path):
    run = make_run(tmp_path)
    (run / "goal_frames.jsonl").write_text(json.dumps({"goal": "potion", "step": "35"}) + "\n", encoding="utf-8")
    v = judge_run(run, "potion", 105)
    assert v.reasons == ["goal row has no integer step"]


def test_corrupt_transitions_line_fails_and_is_counted(tmp_path):
    v = judge_run(make_run(tmp_path, extra_transition_lines=["{not json", "garbage"]), "potion", 105)
    assert not v.passed
    assert v.presses == 35
    assert len(v.reasons) == 1 and v.reasons[0].startswith("2 corrupt transitions.jsonl line")


def test_nonexistent_run_dir_fails_without_raising(tmp_path):
    v = judge_run(tmp_path / "nope", "potion", 105)
    assert not v.passed
    assert v.reasons == ["transitions.jsonl missing or empty", "goal_frames.jsonl missing"]
    assert v.goal_step is None and v.presses == 0 and v.non_agent == 0


def test_all_reasons_collected(tmp_path):
    v = judge_run(make_run(tmp_path, sources=_with(AGENT35, {5: "human"}), goal_step=140), "potion", 105)
    assert v.reasons == ["1 non-agent presses (human) at steps 5", "too slow: potion at step 140, budget 105"]


# --- build_argv / run_case ------------------------------------------------------------------------

EXPECTED_ARGV = ["tools/explore_demo.py", "--headless", "--state", "baselines/bedroom.state",
                 "--stop-at-goal", "potion", "--steps", "105", "--seed", "42",
                 "--maps", "runs/maps.json", "--control-port", "9103"]


def test_build_argv_exact():
    assert build_argv(CASE, 3) == EXPECTED_ARGV


def test_build_argv_has_maps_for_both_memory_modes():
    for memory in ("none", "live"):
        argv = build_argv(replace(CASE, memory=memory), 3)
        assert argv[argv.index("--maps") + 1] == "runs/maps.json"
        assert argv[argv.index("--control-port") + 1] == "9103"


class FakeRunner:
    def __init__(self, returncode=0, stderr="", on_call=None, raises=None):
        self.calls = []
        self.returncode, self.stderr, self.on_call, self.raises = returncode, stderr, on_call, raises

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        if self.on_call is not None:
            self.on_call(Path(kwargs["cwd"]))
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr=self.stderr)


def test_run_case_passes_argv_cwd_and_timeout(tmp_path):
    fake = FakeRunner()
    result = tool.run_case(CASE, 3, tmp_path, runner=fake)
    assert result.error is None and result.proc.returncode == 0
    (argv, kwargs), = fake.calls
    assert argv == [sys.executable, *EXPECTED_ARGV]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["timeout"] == 600
    assert kwargs["check"] is False and kwargs["capture_output"] is True and kwargs["text"] is True


def test_run_case_nonzero_exit_is_error_with_stderr_tail(tmp_path):
    stderr = "x" * 1000 + "Traceback: boom at the end"
    result = tool.run_case(CASE, 0, tmp_path, runner=FakeRunner(returncode=2, stderr=stderr))
    assert result.error == stderr[-400:]
    assert len(result.error) == 400 and result.error.endswith("boom at the end")


def test_run_case_timeout_is_error_not_exception(tmp_path):
    exc = subprocess.TimeoutExpired(cmd=["x"], timeout=600, stderr=b"stuck in a menu")
    result = tool.run_case(CASE, 0, tmp_path, runner=FakeRunner(raises=exc))
    assert result.proc is None
    assert "timeout" in result.error and "stuck in a menu" in result.error


def test_check_case_reports_error_line(tmp_path):
    (tmp_path / "runs").mkdir()
    status, line = tool.check_case(CASE, 0, tmp_path, runner=FakeRunner(returncode=1, stderr="bad rom"))
    assert status == "error"
    assert line == "ERROR red_bedroom_potion_cold: bad rom"


# --- end-to-end with a fake runner -----------------------------------------------------------------

def test_pipeline_pass_with_fake_runner(tmp_path):
    (tmp_path / "runs").mkdir()
    fake = FakeRunner(on_call=lambda cwd: make_run(cwd / "runs"))
    status, line = tool.check_case(CASE, 0, tmp_path, runner=fake)
    assert status == "pass"
    assert line == "PASS red_bedroom_potion_cold: potion at step 35 of budget 105, 0 non-agent presses"


def test_pipeline_fail_with_one_human_row(tmp_path):
    (tmp_path / "runs").mkdir()
    fake = FakeRunner(on_call=lambda cwd: make_run(cwd / "runs", sources=_with(AGENT35, {20: "human"})))
    status, line = tool.check_case(CASE, 0, tmp_path, runner=fake)
    assert status == "fail"
    assert line.startswith("FAIL red_bedroom_potion_cold: 1 non-agent presses (human) at steps 20")
    assert str(tmp_path / "runs" / "explore-X") in line


def test_pipeline_ignores_pre_existing_run_dirs(tmp_path):
    (tmp_path / "runs").mkdir()
    make_run(tmp_path / "runs", sources=_with(AGENT35, {1: "human"}), name="explore-old")
    fake = FakeRunner(on_call=lambda cwd: make_run(cwd / "runs", name="explore-new"))
    status, _ = tool.check_case(CASE, 0, tmp_path, runner=fake)
    assert status == "pass"


def test_pipeline_no_new_run_dir_fails(tmp_path):
    (tmp_path / "runs").mkdir()
    status, line = tool.check_case(CASE, 0, tmp_path, runner=FakeRunner())
    assert status == "fail" and "found 0" in line


# --- case table --------------------------------------------------------------------------------------

def test_checked_in_case_table():
    cases = load_cases(ROOT / "tools" / "hands_off_cases.json")
    assert cases[0] == CASE
    assert cases[0].budget == 105 and cases[0].goal == "potion"
    assert [c.memory for c in cases] == ["none", "live"]


def _table(tmp_path, **override):
    raw = {"name": "bad_case", "game": "red", "state": "bedroom", "memory": "none",
           "goal": "potion", "budget": 105, "seed": 42, **override}
    p = tmp_path / "cases.json"
    p.write_text(json.dumps({"cases": [raw]}), encoding="utf-8")
    return p


def test_bad_memory_raises_naming_case(tmp_path):
    with pytest.raises(ValueError, match="bad_case"):
        load_cases(_table(tmp_path, memory="warm"))


@pytest.mark.parametrize("override", [{"game": "blue"}, {"budget": 0}, {"budget": -5}])
def test_bad_game_or_budget_raises_naming_case(tmp_path, override):
    with pytest.raises(ValueError, match="bad_case"):
        load_cases(_table(tmp_path, **override))


def test_missing_field_raises_naming_case(tmp_path):
    p = _table(tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    del data["cases"][0]["seed"]
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="bad_case.*seed"):
        load_cases(p)


def _touch(root: Path, *rels: str) -> None:
    for rel in rels:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"")


def test_skip_reason_empty_root_names_rom(tmp_path):
    reason = skip_reason(CASE, tmp_path)
    assert reason.startswith("missing roms/")
    assert reason == "missing roms/Pokemon Red.gb"


def test_skip_reason_order_and_none_when_present(tmp_path):
    _touch(tmp_path, "roms/Pokemon Red.gb")
    assert skip_reason(CASE, tmp_path) == "missing baselines/bedroom.state"
    _touch(tmp_path, "baselines/bedroom.state")
    assert skip_reason(CASE, tmp_path) == "missing kb/rom_tables.json"
    _touch(tmp_path, "kb/rom_tables.json")
    live = replace(CASE, memory="live")
    assert skip_reason(live, tmp_path) == "missing runs/maps.json"
    _touch(tmp_path, "runs/maps.json")
    assert skip_reason(CASE, tmp_path) is None
    assert skip_reason(live, tmp_path) is None


# --- console.log, segment starts, main counts ---------------------------------------------------------

def test_step_errors_in_console_fail_with_count_and_first_text(tmp_path):
    run = make_run(tmp_path, sources=AGENT35)
    (run / "console.log").write_text(
        "ok\n[agent step error: ValueError('boom')]\nok\n[agent step error: KeyError('x')]\n", encoding="utf-8")
    v = judge_run(run, "potion", 105)
    assert not v.passed
    assert "2 agent step error" in v.reasons[0] and "boom" in v.reasons[0]


def test_human_console_lines_fail(tmp_path):
    run = make_run(tmp_path, sources=AGENT35)
    (run / "console.log").write_text("thinking: a\nhuman:    b\n", encoding="utf-8")
    v = judge_run(run, "potion", 105)
    assert not v.passed and "1 human: press line" in v.reasons[0]


def test_clean_console_log_still_passes(tmp_path):
    run = make_run(tmp_path, sources=AGENT35)
    (run / "console.log").write_text("thinking: fine\n", encoding="utf-8")
    assert judge_run(run, "potion", 105).passed


def test_segment_case_argv_uses_stop_at_map_and_state_path():
    seg = replace(CASE, state="runs/explore-1/end.state", goal="map:0x25")
    argv = build_argv(seg, 0)
    assert argv[argv.index("--state") + 1] == "runs/explore-1/end.state"
    assert argv[argv.index("--stop-at-map") + 1] == "0x25"
    assert "--stop-at-goal" not in argv


def test_judge_handles_stop_map_goal(tmp_path):
    run = make_run(tmp_path, sources=AGENT35, goal="map:0x25", goal_step=20)
    assert judge_run(run, "map:0x25", 105).passed
    assert judge_run(run, "map:37", 105).passed
    assert not judge_run(run, "map:0x26", 105).passed


def test_bad_stop_map_raises_naming_case(tmp_path):
    with pytest.raises(ValueError, match="bad_case"):
        load_cases(_table(tmp_path, goal="map:zz"))


def test_main_counts_error_separately(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tool, "skip_reason", lambda c, r: None)
    monkeypatch.setattr(tool, "copy_inputs", lambda c, s: None)
    monkeypatch.setattr(tool, "check_case", lambda c, i, s: ("error", f"ERROR {c.name}: x"))
    assert tool.main(["--case", CASE.name]) == 1
    assert "0 failed, 1 errored" in capsys.readouterr().out
