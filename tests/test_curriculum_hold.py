"""Curriculum hold list: held segments are skipped in every category, expire, tolerate a bad file, and the CLI edits it."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import curriculum_hold  # noqa: E402
import seg_hold  # noqa: E402
import seg_sched  # noqa: E402
import seg_store as ss  # noqa: E402
from test_segment_curriculum import fill, mkroot  # noqa: E402

T0 = datetime(2026, 11, 7, 12, 0).astimezone()


def write_holds(root, holds):
    p = root / "runs" / "curriculum_hold.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"holds": holds}), encoding="utf-8")


def until(hours):
    return (T0 + timedelta(hours=hours)).isoformat(timespec="seconds")


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def sched(root, logs, clock):
    return seg_sched.Curriculum(root, clock=clock, log=logs.append, quiet_s=0)


def test_held_frontier_is_skipped_and_slots_fall_through(tmp_path):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    logs = []
    c = sched(root, logs, Clock(T0.timestamp()))
    assert {s.key for s in c.groups()["frontier"]} == {"left_house"}
    write_holds(root, [{"segment": "left_house", "until": until(2), "reason": "stall"}])
    cats = [c.choose() for _ in range(9)]
    assert all(p is not None for p in cats)
    assert {k for k, _ in cats} == {"unsolved"}   # the frontier never wins a slot; unsolved takes them all
    assert "left_house" not in {s.key for _, s in cats}
    assert sum(1 for m in logs if m.startswith("curriculum: holding left_house until")) == 1


def test_hold_applies_to_polish_and_unsolved_too(tmp_path):
    root = mkroot(tmp_path)
    c = sched(root, [], Clock(T0.timestamp()))
    fill(c.doc, "potion", [True] * 20)
    fill(c.doc, "left_house", [True] * 10 + [False] * 10)
    write_holds(root, [{"segment": "potion", "until": until(2), "reason": "r"},
                       {"segment": "left_house", "until": until(2), "reason": "r"}])
    picked = {s.key for _ in range(30) if (p := c.choose()) for s in [p[1]]}
    assert not picked & {"potion", "left_house"}
    assert picked                                  # the rest of the ladder still runs


def test_stem_matches_split_sub_segments(tmp_path):
    root = mkroot(tmp_path)
    c = sched(root, [], Clock(T0.timestamp()))
    c.doc["splits"]["left_house"] = [0x61]
    keys = {s.key for g in c.groups().values() for s in g}
    assert "left_house@61" in keys                  # the sub-segment is a candidate before the hold
    write_holds(root, [{"segment": "left_house", "until": until(2), "reason": "r"}])
    picked = {s.key for _ in range(40) if (p := c.choose()) for s in [p[1]]}
    assert "left_house@61" not in picked and picked
    assert seg_hold.Hold("ss_anne_captain", "x", T0, "").covers("ss_anne_captain@61")
    assert not seg_hold.Hold("ss_anne_captain@61", "x", T0, "").covers("ss_anne_captain")
    assert not seg_hold.Hold("gyarados", "x", T0, "").covers("gyarados_extra")


def test_hold_expires_once_and_logs_expiry_once(tmp_path):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    write_holds(root, [{"segment": "left_house", "until": until(1), "reason": "stall"}])
    logs, clk = [], Clock(T0.timestamp())
    c = sched(root, logs, clk)
    assert all(k == "unsolved" for k, _ in [c.choose() for _ in range(5)])
    clk.t = (T0 + timedelta(hours=2)).timestamp()
    cats = [c.choose() for _ in range(9)]
    assert "frontier" in {k for k, _ in cats}      # the expired hold no longer blocks left_house
    c.choose()
    assert [m for m in logs if "expired" in m] == ["curriculum: hold on left_house expired"]
    assert sum(1 for m in logs if m.startswith("curriculum: holding")) == 1


def test_hold_file_is_reread_when_changed(tmp_path):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    c = sched(root, [], Clock(T0.timestamp()))
    write_holds(root, [{"segment": "left_house", "until": until(2), "reason": "r"}])
    assert {k for k, _ in [c.choose() for _ in range(6)]} == {"unsolved"}
    write_holds(root, [])                           # the operator clears it while the scheduler runs
    assert "frontier" in {k for k, _ in [c.choose() for _ in range(6)]}


@pytest.mark.parametrize("text", [
    "{not json",
    '{"holds": "gyarados"}',
    '["gyarados"]',
    '{"holds": [{"segment": "left_house"}]}',           # no until
    '{"holds": [{"segment": "left_house", "until": "tomorrow"}]}',
])
def test_malformed_file_means_no_holds(tmp_path, text):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    p = root / "runs" / "curriculum_hold.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    logs = []
    c = sched(root, logs, Clock(T0.timestamp()))
    cats = [c.choose() for _ in range(6)]
    assert "frontier" in {k for k, _ in cats}
    assert not [m for m in logs if "holding" in m]


def test_malformed_entry_is_skipped_and_valid_one_kept(tmp_path):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    write_holds(root, [{"segment": "left_house", "until": "nope"}, 7,
                       {"segment": "left_house", "until": until(2), "reason": "ok"}])
    c = sched(root, [], Clock(T0.timestamp()))
    assert {k for k, _ in [c.choose() for _ in range(6)]} == {"unsolved"}


def test_cli_add_list_clear_on_tmp_root(tmp_path, capsys):
    root = tmp_path
    curriculum_hold.main(["--root", str(root), "add", "gyarados", "--hours", "2", "--reason", "training stall fix pending"])
    p = root / "runs" / "curriculum_hold.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert [h["segment"] for h in data["holds"]] == ["gyarados"]
    assert data["holds"][0]["reason"] == "training stall fix pending"
    assert seg_hold.parse_until(data["holds"][0]["until"]) > datetime.now().astimezone()
    assert not list(p.parent.glob("*.tmp"))         # atomic write leaves no temp file behind

    curriculum_hold.main(["--root", str(root), "add", "gyarados", "--hours", "1", "--reason", "again"])
    assert len(json.loads(p.read_text(encoding="utf-8"))["holds"]) == 1   # re-adding replaces

    capsys.readouterr()
    curriculum_hold.main(["--root", str(root), "list"])
    out = capsys.readouterr().out
    assert "gyarados" in out and "active" in out and "again" in out

    curriculum_hold.main(["--root", str(root), "clear", "gyarados"])
    assert json.loads(p.read_text(encoding="utf-8"))["holds"] == []
    capsys.readouterr()
    curriculum_hold.main(["--root", str(root), "list"])
    assert capsys.readouterr().out.strip() == "no holds"
    curriculum_hold.main(["--root", str(root), "clear", "gyarados"])
    assert "no hold on gyarados" in capsys.readouterr().out


def test_cli_rejects_non_positive_hours(tmp_path):
    with pytest.raises(SystemExit):
        curriculum_hold.main(["--root", str(tmp_path), "add", "gyarados", "--hours", "0", "--reason", "x"])


def test_out_of_range_entries_are_skipped_alone(tmp_path):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    write_holds(root, [{"segment": "won_battle", "until": "9999-12-31T23:59:59", "reason": "far"},
                       {"segment": "won_battle", "until": "0001-01-01T00:00:00", "reason": "past"},
                       {"segment": "left_house", "until": "9999-12-31T23:59:59+00:00", "reason": "aware"},
                       {"segment": "won_battle", "until": until(2), "reason": "ok"}])
    c = sched(root, [], Clock(T0.timestamp()))
    assert {k for k, _ in [c.choose() for _ in range(6)]} == {"unsolved"}   # the valid won_battle hold still applies
    assert {h.segment for h in seg_hold.read_file(root / "runs" / "curriculum_hold.json")} == {"won_battle", "left_house"}


def test_unreadable_read_keeps_last_good_holds(tmp_path, monkeypatch):
    root = mkroot(tmp_path, ("bedroom", "potion"))
    write_holds(root, [{"segment": "won_battle", "until": until(2), "reason": "r"}])
    hf = seg_hold.HoldFile(root)
    assert [h.segment for h in hf.current()] == ["won_battle"]
    write_holds(root, [])                            # a new write changes the signature...
    real = Path.read_text

    def flaky(self, *a, **k):
        if self == hf.path:
            raise PermissionError("locked by a writer")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert [h.segment for h in hf.current()] == ["won_battle"]   # ...but a failed read keeps the last good holds
    monkeypatch.setattr(Path, "read_text", real)
    assert hf.current() == []                        # not cached as failed: the next call reads the file


def test_cli_rejects_nan_inf_and_huge_hours(tmp_path):
    for bad in ("nan", "inf", "-inf", "1e300"):
        with pytest.raises(SystemExit):
            curriculum_hold.main(["--root", str(tmp_path), "add", "gyarados", "--hours", bad, "--reason", "x"])
    assert not (tmp_path / "runs" / "curriculum_hold.json").exists()
