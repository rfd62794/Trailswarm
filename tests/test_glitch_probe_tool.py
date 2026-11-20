"""The glitch_probe CLI on injected fakes: a tiny script file runs end to end, the report lands
under discoveries/, the input state is byte-identical afterwards, and curriculum-directory
sources are refused. Loading the tool module must not start an emulator."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.novelty import discoveries as dc

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _tool():
    spec = importlib.util.spec_from_file_location("tool_glitch_probe", TOOLS / "glitch_probe.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_repro_runs_a_tiny_script_and_reports_under_discoveries(tmp_path, capsys):
    tool = _tool()
    state = tmp_path / "near.state"
    state.write_bytes(b"fake state")
    script = tmp_path / "s.json"
    script.write_text(json.dumps([{"id": "before_spot", "mark": True},
                                  {"id": "walk", "press": ["UP", "UP"]}]))
    runs = tmp_path / "runs"
    made = []
    rc = tool.main(["repro", "--state", str(state), "--script", str(script),
                    "--runs-dir", str(runs), "--name", "t"],
                   emu_factory=lambda p: made.append(p) or FakeEmulator())
    assert rc == 0
    report = runs / "discoveries" / "glitchlab-t.jsonl"
    assert report.is_file() and dc.is_discovery_state(report)
    rows = [json.loads(ln) for ln in report.read_text().splitlines()]
    assert [r["id"] for r in rows] == ["before_spot", "walk"]
    out = capsys.readouterr().out.splitlines()
    verdict_line = json.loads(out[0])
    assert "bit meanings UNVERIFIED" in verdict_line["notes"]
    assert "glitchlab-t" in out[1]
    # the factory was handed a scratch copy under discoveries/, not the original
    assert len(made) == 1 and dc.is_discovery_state(made[0]) and made[0] != state
    assert state.read_bytes() == b"fake state"          # never opened for writing
    assert not list(tmp_path.rglob("checkpoints"))      # nothing written under a checkpoints dir


def test_repro_refuses_placeholders_and_missing_or_bad_input(tmp_path):
    tool = _tool()
    state = tmp_path / "s.state"
    state.write_bytes(b"x")
    runs = tmp_path / "runs"
    # default RECIPE still holds placeholders: refused
    assert tool.main(["repro", "--state", str(state), "--runs-dir", str(runs)],
                     emu_factory=lambda p: FakeEmulator()) == 2
    # --allow-placeholder runs the recipe's concrete presses only
    assert tool.main(["repro", "--state", str(state), "--runs-dir", str(runs),
                      "--allow-placeholder"], emu_factory=lambda p: FakeEmulator()) == 0
    # missing state and malformed script are usage errors
    assert tool.main(["repro", "--state", str(tmp_path / "nope.state"), "--runs-dir", str(runs)],
                     emu_factory=lambda p: FakeEmulator()) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert tool.main(["repro", "--state", str(state), "--script", str(bad),
                      "--runs-dir", str(runs)], emu_factory=lambda p: FakeEmulator()) == 2


def test_a_source_under_checkpoints_is_refused(tmp_path):
    tool = _tool()
    cp = tmp_path / "checkpoints"
    cp.mkdir()
    state = cp / "leg.state"
    state.write_bytes(b"x")
    rc = tool.main(["repro", "--state", str(state), "--runs-dir", str(tmp_path / "runs"),
                    "--allow-placeholder"], emu_factory=lambda p: FakeEmulator())
    assert rc == 2


def test_survey_writes_under_discoveries_and_refuses_checkpoints(tmp_path, capsys):
    tool = _tool()
    state = tmp_path / "near.state"
    state.write_bytes(b"fake state")
    runs = tmp_path / "runs"
    rc = tool.main(["survey", "--state", str(state), "--map", "0x24", "--runs-dir", str(runs), "--name", "sv"],
                   emu_factory=lambda p: FakeEmulator())
    assert rc == 0 and (runs / "discoveries" / "glitchlab-sv.jsonl").is_file()
    assert json.loads(capsys.readouterr().out.splitlines()[0])["trainers"] == []
    assert state.read_bytes() == b"fake state"
    cp = tmp_path / "checkpoints"
    cp.mkdir()
    (cp / "x.state").write_bytes(b"x")
    assert tool.main(["survey", "--state", str(cp / "x.state"), "--map", "1", "--runs-dir", str(runs)],
                     emu_factory=lambda p: FakeEmulator()) == 2
