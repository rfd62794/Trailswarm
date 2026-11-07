"""Stall dossiers on synthetic run dirs (no emulator, no ROM)."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pokeagent import stalls

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _tool(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}_st", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _jl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def make_run(root, name, *, map_id=35, x=5, y=5, button="UP", outcome="blocked", behaviour="frontier", rule="frontier",
             n=700, text="", textbox="none", tag="seg:to_bill:1-2", state="to_cerulean", seed=7, npcs=None, anomalies=()):
    r = root / "runs" / name
    r.mkdir(parents=True)
    _jl(r / "decisions.jsonl", [{"step": i, "behaviour": behaviour, "rule": rule, "button": button, "map": map_id, "x": x, "y": y,
                                 "goal_stage": "to_bill", "box": False, "battle": False, "outcome": outcome, "reversal": False}
                                for i in range(1, n + 1)])
    _jl(r / "transitions.jsonl", [{"step": n, "from": [map_id, x, y], "button": button, "to": [map_id, x, y], "moved": False,
                                   "textbox": textbox, "text": text, "source": "agent"}])
    (r / "meta.json").write_text(json.dumps({"tag": tag, "seed": seed, "starter": "charmander", "state": state,
                                             "stop_at_goal": "to_bill"}), encoding="utf-8")
    mp = root / "runs" / "maps.json"
    doc = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {"maps": {}}
    doc["maps"][str(map_id)] = {"npcs": npcs or {}}
    mp.write_text(json.dumps(doc), encoding="utf-8")
    if anomalies:
        _jl(root / "runs" / "anomalies.jsonl", list(anomalies))
    return r


NPC = {"slot1:pic7": {"pic": 7, "slot": 1, "last": [5, 4], "positions": {"5,4": 9}}}


def test_signature_and_dossier_fields(tmp_path):
    make_run(tmp_path, "explore-a", npcs=NPC)
    d = stalls.build_dossier(tmp_path, "explore-a", {"pos": [35, 5, 5], "slot": 2, "seed": 7, "presses": 700, "t": "2026-11-06T22:00:00"})
    assert d["signature"] == {"map": 35, "behaviour": "frontier", "rule": "frontier", "button": "UP", "outcome": "blocked",
                              "sprite_adjacent": True}
    assert (d["map"], d["x"], d["y"], d["segment"], d["seed"], d["starter"]) == (35, 5, 5, "to_bill", 7, "charmander")
    assert len(d["decisions_tail"]) == stalls.TAIL
    assert d["histogram"]["window"] == stalls.WINDOW and d["histogram"]["buttons"] == {"UP": 600}
    assert d["sprites_near"][0]["adjacent"] and d["start_state"]["state"] == "to_cerulean"


def test_route24_cases_share_one_signature_and_cluster(tmp_path):
    for i in range(3):
        make_run(tmp_path, f"explore-r24-{i}", npcs=NPC)
    make_run(tmp_path, "explore-other", map_id=40, x=1, y=1, button="DOWN")
    for r in ("explore-r24-0", "explore-r24-1", "explore-r24-2", "explore-other"):
        stalls.write_dossier(tmp_path, r, {"t": "2026-11-06T22:00:00"})
    rows = stalls.cluster(stalls.load_dossiers(tmp_path))
    assert [r["count"] for r in rows] == [3, 1]
    assert rows[0]["likely_cause"].startswith("pressing into a sprite")
    assert len(rows[0]["example_runs"]) == 3
    assert stalls.cluster(stalls.load_dossiers(tmp_path), segment="nope") == []
    assert stalls.cluster(stalls.load_dossiers(tmp_path), since_t="2027-01-01") == []


def test_sprite_from_anomaly_row(tmp_path):
    an = {"run": "explore-a", "map": 35, "details": {"npc_at": [5, 6], "npc_pic": 7, "npc_slot": 2}}
    make_run(tmp_path, "explore-a", anomalies=[an])
    d = stalls.build_dossier(tmp_path, "explore-a")
    assert d["signature"]["sprite_adjacent"] and d["sprites_near"][0]["source"] == "anomaly"


def test_cause_heuristics(tmp_path):
    make_run(tmp_path, "explore-a", button="A", outcome="none", text="Hello there", textbox="text")
    assert stalls.build_dossier(tmp_path, "explore-a")["likely_cause"] == "A-mash in a text box"
    make_run(tmp_path, "explore-m", button="B", outcome="none", behaviour="guards", rule="menu_back_out")
    assert stalls.build_dossier(tmp_path, "explore-m")["likely_cause"] == "menu loop"
    make_run(tmp_path, "explore-w", button="LEFT", outcome="blocked")
    assert stalls.build_dossier(tmp_path, "explore-w")["likely_cause"].startswith("blocked by a learned wall")
    make_run(tmp_path, "explore-u", button="LEFT", outcome="moved")
    assert stalls.build_dossier(tmp_path, "explore-u")["likely_cause"].startswith("wandering inside 1 tiles")


def test_no_decisions_gives_none(tmp_path):
    (tmp_path / "runs" / "explore-e").mkdir(parents=True)
    assert stalls.build_dossier(tmp_path, "explore-e") is None
    assert stalls.safe_write_for_stall(tmp_path, "explore-e") is None


def test_backfill_cli_top_show(tmp_path, capsys):
    make_run(tmp_path, "explore-a", npcs=NPC)
    make_run(tmp_path, "explore-b", npcs=NPC)
    (tmp_path / "runs" / "swarm").mkdir()
    rows = [{"t": "2026-11-06T22:00:00", "slot": 1, "seed": 7, "reason": "r", "pos": [35, 5, 5], "presses": 700, "run": "explore-a"},
            {"t": "2026-11-06T22:01:00", "slot": 2, "seed": 8, "reason": "r", "pos": [35, 5, 5], "presses": 700, "run": "explore-b"},
            {"t": "x", "slot": 3, "seed": 1, "reason": "r", "pos": [1, 1, 1], "presses": 9, "run": "explore-gone"},
            {"t": "x", "slot": 3, "seed": 1, "reason": "r", "pos": None, "presses": 0, "run": None}]
    _jl(tmp_path / "runs" / "swarm" / "stalls.jsonl", rows)
    before = sorted(p.name for p in (tmp_path / "runs").iterdir())
    cli = _tool("stalls")
    assert cli.main(["--root", str(tmp_path), "backfill"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert (st["rows"], st["written"], st["no_run"]) == (4, 2, 2)
    assert sorted(p.name for p in (tmp_path / "runs").iterdir()) == sorted(before + ["stalls"])  # only runs/stalls is new
    assert cli.main(["--root", str(tmp_path), "backfill"]) == 0 and json.loads(capsys.readouterr().out)["existing"] == 2
    cli.main(["--root", str(tmp_path), "top"])
    top = json.loads(capsys.readouterr().out)
    assert top["dossiers"] == 2 and top["top"][0]["count"] == 2
    cli.main(["--root", str(tmp_path), "show", "explore-b"])
    assert json.loads(capsys.readouterr().out)["run"] == "explore-b"


def test_supervisor_hook_swallows_errors(tmp_path, monkeypatch):
    sc = _tool("swarm_continuous")
    make_run(tmp_path, "explore-a", npcs=NPC)

    class W:
        run_dir = tmp_path / "runs" / "explore-a"
        last_pos, presses = [35, 5, 5], 700

    sc.write_stall_dossier(tmp_path, W(), 1, 7, "r")
    assert (tmp_path / "runs" / "stalls" / "explore-a.json").exists()
    monkeypatch.setattr(stalls, "write_dossier", lambda *a, **k: 1 / 0)
    sc.write_stall_dossier(tmp_path, W(), 1, 7, "r")           # inner failure
    sc.write_stall_dossier(tmp_path, object(), 1, 7, "r")      # no run_dir at all
    sc.write_stall_dossier(None, None, 1, 7, "r")              # garbage


def test_replay_args_and_compare(tmp_path):
    rs = _tool("replay_stall")
    d = {"presses": 1000, "seed": 7, "starter": "charmander", "signature": {"a": 1}, "signature_key": "k",
         "start_state": {"state_file": "s.state", "maps_copy": "m.json", "stop_at_goal": "to_bill"}}
    a = rs.replay_args(d, tmp_path)
    assert a[:4] == ["--state", "s.state", "--seed", "7"] and "--maps-copy" in a and a[a.index("--steps") + 1] == "1100"
    assert a[a.index("--stop-at-goal") + 1] == "to_bill"
    b = rs.replay_args(d, tmp_path, steps=50)
    assert b[b.index("--steps") + 1] == "50"
    d["start_state"]["maps_copy"] = None
    c = rs.replay_args(d, tmp_path)
    assert c[c.index("--maps-copy") + 1].endswith("maps.json")
    with pytest.raises(ValueError):
        rs.replay_args({"start_state": {}}, tmp_path)
    fresh = {"signature": {"a": 1}, "signature_key": "k"}
    assert rs.compare(d, fresh, 1050)["reproduced"]
    assert not rs.compare(d, fresh, 1300)["reproduced"]
    assert not rs.compare(d, {"signature": {}, "signature_key": "z"}, 1000)["reproduced"]
