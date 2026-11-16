"""tools/marathon_watch.py: the JSON-lines CLI over the marathon rules (synthetic run dirs)."""
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(name):
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(f"tool_{name}", ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mw = _load("marathon_watch")
from pokeagent.marathon.reader import find_runs  # noqa: E402


def make_run(runs_dir, name, tag, meta=None):
    d = Path(runs_dir) / name
    d.mkdir(parents=True)
    m = {"tag": tag, "seed": 7, "start": "bedroom", "steps": 99999}
    m.update(meta or {})
    (d / "meta.json").write_text(json.dumps(m))
    return d


def presses(d, spec):
    with open(d / "transitions.jsonl", "a") as f:
        for m, n in spec:
            for i in range(n):
                f.write(json.dumps({"to": [m, i % 17, 0], "button": "A"}) + "\n")


def goals(d, *rows):
    with open(d / "goal_frames.jsonl", "a") as f:
        for g, s in rows:
            f.write(json.dumps({"goal": g, "step": s, "frame": s}) + "\n")


def stalled_run(runs_dir, name="explore-s-5", meta=None):
    d = make_run(runs_dir, name, "marathon-x", meta)
    goals(d, ("ss_ticket", 100))
    presses(d, [(0x58, 4000)])
    return d


def lines(capsys):
    return [json.loads(ln) for ln in capsys.readouterr().out.splitlines() if ln.strip()]


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"ok": true, "path": "/tmp/stall.state"}'


def _record_posts(monkeypatch):
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: (calls.append(req), _Resp())[1])
    return calls


def test_find_runs_selects_by_tag_prefix(tmp_path):
    runs = tmp_path / "runs"
    a = make_run(runs, "explore-a-11", "marathon-a")
    c = make_run(runs, "explore-c-33", "marathon-c")
    make_run(runs, "explore-b-22", "other-x")
    make_run(runs, "explore-d-44", "")
    assert {d.name for d in find_runs(runs, "marathon-")} == {a.name, c.name}


def test_once_emits_one_line_per_tagged_run(tmp_path, capsys):
    runs = tmp_path / "runs"
    a = make_run(runs, "explore-a-1", "marathon-a")
    presses(a, [(0x58, 400)])
    make_run(runs, "explore-b-2", "other-x")
    presses(runs / "explore-b-2", [(0x58, 4000)])  # stalled too, but not tagged: never judged
    assert mw.main(["--tag", "marathon-", "--runs-dir", str(runs), "--once"]) == 0
    out = lines(capsys)
    assert len(out) == 1 and out[0]["run"] == "explore-a-1"
    assert out[0]["status"] == "ok" and out[0]["step"] == 400 and out[0]["tag"] == "marathon-a"
    assert out[0]["bundle"] is None
    assert set(out[0]) == {"t", "run", "tag", "step", "status", "reason", "detail", "bundle"}


def test_run_override_and_young(tmp_path, capsys):
    d = make_run(tmp_path / "runs", "explore-y-9", "anything")
    presses(d, [(0x58, 50)])
    assert mw.main(["--run", str(d), "--once"]) == 0  # --run ignores the tag entirely
    out = lines(capsys)
    assert out[0]["status"] == "young" and out[0]["run"] == "explore-y-9" and out[0]["step"] == 50


def test_stalled_run_writes_bundle_and_posts_save_and_stop(tmp_path, capsys, monkeypatch):
    calls = _record_posts(monkeypatch)
    runs = tmp_path / "runs"
    stalled_run(runs, meta={"control_port": 9901})  # the meta.json port is the fallback
    assert mw.main(["--tag", "marathon-", "--runs-dir", str(runs), "--once", "--stop"]) == 0
    out = lines(capsys)[0]
    assert out["status"] == "stalled" and out["reason"] == "map_dwell"
    assert out["bundle"] and Path(out["bundle"]).exists()
    assert out["save"] == "/tmp/stall.state" and out["stop"] == "ok"
    cmds = [json.loads(c.data)["cmd"] for c in calls]
    assert cmds == ["save_state", "stop"]
    assert all(c.full_url == "http://127.0.0.1:9901/command" for c in calls)


def test_save_state_posts_only_once_per_stall_episode(tmp_path, capsys, monkeypatch):
    calls = _record_posts(monkeypatch)
    runs = tmp_path / "runs"
    stalled_run(runs, meta={"control_port": 9901})
    mw.main(["--tag", "marathon-", "--runs-dir", str(runs), "--once"])
    assert [json.loads(c.data)["cmd"] for c in calls] == ["save_state"]
    calls.clear()
    mw.main(["--tag", "marathon-", "--runs-dir", str(runs), "--once"])
    assert calls == []  # the episode's bundle already exists: no second save, no rewrite


def test_registry_entry_wins_over_meta_and_carries_the_token(tmp_path, capsys, monkeypatch):
    calls = _record_posts(monkeypatch)
    runs = tmp_path / "runs"
    stalled_run(runs, name="explore-t-4242", meta={"control_port": 9901})
    (runs / "agents").mkdir()
    (runs / "agents" / "explore-4242.json").write_text(
        json.dumps({"pid": 4242, "port": 7777, "token": "tok"}))
    assert mw.main(["--tag", "marathon-", "--runs-dir", str(runs), "--once"]) == 0
    assert calls and calls[0].full_url == "http://127.0.0.1:7777/command"
    assert calls[0].get_header("X-pokeagent-token") == "tok"


def test_no_port_and_no_registry_is_report_only(tmp_path, capsys, monkeypatch):
    calls = _record_posts(monkeypatch)
    runs = tmp_path / "runs"
    stalled_run(runs)  # no control_port in meta, no registry entry, no --port
    assert mw.main(["--tag", "marathon-", "--runs-dir", str(runs), "--once", "--stop"]) == 0
    out = lines(capsys)[0]
    assert out["status"] == "stalled" and out["save"] == "no port" and out["stop"] == "no port"
    assert calls == []


def test_missing_runs_dir_still_exits_zero(tmp_path, capsys):
    assert mw.main(["--runs-dir", str(tmp_path / "gone"), "--once"]) == 0
    assert lines(capsys) == []


def test_explore_demo_meta_carries_control_port():
    ed = _load("explore_demo")
    ed._git_sha = lambda: ""
    a = SimpleNamespace(state=None, stop_at_goal=None, stop_at_map=None, tag="marathon-x", steps=10,
                        explore_rate=0.3, box_pace=5, starter=None, seed=1, frame_share=0.2,
                        train_level=0, headless=True, control_port=0)
    m = ed._meta_dict(a)
    assert m["control_port"] == 0 and m["start"] == "baseline" and m["window"] is False
