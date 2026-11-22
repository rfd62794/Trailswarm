import importlib.util
import json
from pathlib import Path

from pokeagent.emulator import FakeEmulator
from pokeagent.ram_lookup import MapEntry, is_usable
from pokeagent.ramlab import probe
from pokeagent.ramlab.trust import tier_of, validate

_spec = importlib.util.spec_from_file_location("ram_probe", Path(__file__).resolve().parents[1] / "tools" / "ram_probe.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

GAP, LABELLED, NOISE, FLAKY = 0xD430, 0xD362, 0xD500, 0xD600
ENTRIES = [{"name": "wFakeCoord", "addr": "0xD362", "size": 1, "encoding": "u8",
            "region": "map", "verified": False}]


class ScriptedEmu(FakeEmulator):
    """press('up') writes the gap/labelled bytes (and the flaky one on the first two presses);
    every tick churns the noise byte."""

    def __init__(self):
        super().__init__()
        self.npress = 0

    def press(self, button, hold_frames=8, settle_frames=16):
        super().press(button, hold_frames, settle_frames)
        self.npress += 1
        self.memory[GAP] = 9
        self.memory[LABELLED] = 7
        if self.npress <= 2:
            self.memory[FLAKY] = 5
        self.tick(4)

    def tick(self, frames):
        super().tick(frames)
        self.memory[NOISE] = (self.memory.get(NOISE, 0) + 1) & 0xFF


def test_probe_run_splits_unlabeled_labelled_and_drops_noise(tmp_path):
    emu = ScriptedEmu()
    state = tmp_path / "start.state"
    state.write_text(json.dumps({}))
    script = {"version": 1, "game": "pokemon-red", "idle_frames": 2, "repeat": 3,
              "events": [{"label": "step_up", "presses": ["up"]}]}
    run_dir = probe.probe_run(emu, state, script, ENTRIES, tmp_path, "pokemon-red", stamp="t1")
    assert run_dir.parent == tmp_path and run_dir.name == "ramprobe-pokemon-red-start-t1"
    rep = json.loads((run_dir / "probe.json").read_text())
    (run_dir / "report.txt").read_text()
    ev = rep["events"][0]
    assert ev["unlabeled"] == [{"addr": GAP, "before": 0, "after": 9, "label": "step_up"}]
    assert ev["labelled"] == {"wFakeCoord": 1}                       # labelled counted, not listed
    assert rep["noise"] >= 1 and rep["state"] == "start.state" and rep["state_sha1"]


def _run_dir(root, name, unl, label="step_up"):
    d = root / name
    d.mkdir()
    (d / "probe.json").write_text(json.dumps({"events": [{"label": label, "unlabeled": unl}]}))
    return d


def _ns(tmp_path, addr="0xD430", size=1, name="wDisc_D430", apply=False, runs=()):
    import argparse
    return argparse.Namespace(addr=addr, size=size, name=name, evidence_run=list(runs),
                              region="other", game="pokemon-red", apply=apply)


def _tmp_map(tmp_path, monkeypatch):
    map_path = tmp_path / "ram_map.json"
    map_path.write_text(json.dumps(ENTRIES))
    monkeypatch.setattr(tool, "map_path_for", lambda game: map_path)
    return map_path


def test_promote_refusals(tmp_path, monkeypatch, capsys):
    _tmp_map(tmp_path, monkeypatch)
    unl = [{"addr": GAP, "before": 0, "after": 9, "label": "step_up"}]
    r1 = _run_dir(tmp_path, "run-a", unl)
    r2 = _run_dir(tmp_path, "run-b", unl)
    assert tool.cmd_promote(_ns(tmp_path, addr="0xD362", runs=(r1, r2))) == 1     # overlaps a labelled entry
    assert tool.cmd_promote(_ns(tmp_path, name="wFakeCoord", runs=(r1, r2))) == 1  # name already used
    assert tool.cmd_promote(_ns(tmp_path, runs=(r1,))) == 1                        # needs two run dirs
    r3 = _run_dir(tmp_path, "run-c", unl, label="open_menu")
    assert tool.cmd_promote(_ns(tmp_path, runs=(r1, r3))) == 1                     # different labels don't pair
    assert tool.cmd_promote(_ns(tmp_path, runs=(r1, tmp_path / "nope"))) == 1      # dir must exist
    out = capsys.readouterr().out
    assert out.count("refused") == 5


def test_promote_writes_discovered_row(tmp_path, monkeypatch, capsys):
    map_path = _tmp_map(tmp_path, monkeypatch)
    unl = [{"addr": GAP, "before": 0, "after": 9, "label": "step_up"}]
    r1 = _run_dir(tmp_path, "run-a", unl)
    r2 = _run_dir(tmp_path, "run-b", unl)
    assert tool.cmd_promote(_ns(tmp_path, runs=(r1, r2))) == 0                     # dry run
    assert not any("wDisc_D430" in ln for ln in map_path.read_text().splitlines())
    assert tool.cmd_promote(_ns(tmp_path, runs=(r1, r2), apply=True)) == 0
    rows = json.loads(map_path.read_text())
    row = next(e for e in rows if e["name"] == "wDisc_D430")
    assert row["trust"] == "discovered" and not row["verified"]
    assert row["source"].startswith("ram_probe run-a") or "run-a" in row["source"]
    assert "step_up" in row["evidence"] and "0->9" in row["evidence"]
    assert validate(rows) == []
    assert [r["name"] for r in rows] == ["wFakeCoord", "wDisc_D430"]     # inserted sorted by addr
    d = MapEntry(row["name"], int(row["addr"], 16), row["size"], row["region"], trust=row["trust"])
    assert not is_usable(d) and is_usable(d, allow_discovered=True)
    assert tier_of(row) == "discovered"
