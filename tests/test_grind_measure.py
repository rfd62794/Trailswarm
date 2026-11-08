"""grind.measure (synthetic fixtures): frames/step calibration from run records, measured episode XP."""
from __future__ import annotations

import json

from pokeagent.grind import measure


def _t(step, frame=None, moved=True, source="agent"):
    r = {"step": step, "moved": moved, "source": source}
    if frame is not None:
        r["frame"] = frame
    return r


def test_frames_per_step_from_transition_frames():
    rows = [_t(1, 0), _t(2, 16), _t(3, 32), _t(4, 48)]
    assert measure.frames_per_step(rows) == 16.0
    rows[1]["source"] = "human"                       # only agent presses count
    assert measure.frames_per_step(rows) == 24.0      # deltas 32, 16 -> median 24
    assert measure.frames_per_step([_t(1, 0, moved=False)]) is None


def test_frames_per_step_falls_back_to_levels_pairs():
    transitions = [_t(1), _t(2)]                       # no frame field: the levels pairs answer
    levels = [{"step": 0, "frame": 0}, {"step": 10, "frame": 160}, {"step": 20, "frame": 330}]
    assert measure.frames_per_step(transitions, levels) == 16.5   # rates 16, 17 -> median
    assert measure.frames_per_step(transitions, [{"step": 5}]) is None


def test_calibration_and_default(tmp_path):
    d = tmp_path / "explore-1"
    d.mkdir()
    (d / "transitions.jsonl").write_text(json.dumps(_t(1)) + "\n", encoding="utf-8")
    (d / "levels.jsonl").write_text(
        json.dumps({"step": 0, "frame": 0}) + "\n" + json.dumps({"step": 10, "frame": 160}) + "\n",
        encoding="utf-8")
    assert measure.calibration(tmp_path) == (16.0, 1)
    assert measure.frames_per_step_or_default(tmp_path) == 16.0
    assert measure.calibration(tmp_path / "missing") == (None, 0)
    assert measure.frames_per_step_or_default(tmp_path / "missing") == measure.FRAMES_PER_STEP_DEFAULT


def test_calibration_scans_only_the_newest_runs(tmp_path, monkeypatch):
    """The runs/ cap (PR #165): only the ``last`` newest names are stat'ed - the live checkout has 4,700+ dirs."""
    from pathlib import Path
    for i in range(30):
        d = tmp_path / f"explore-2026{i:04d}"
        d.mkdir()
        (d / "transitions.jsonl").write_text(
            json.dumps(_t(1, 0)) + "\n" + json.dumps(_t(2, i + 1)) + "\n", encoding="utf-8")
    seen = []
    orig = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: seen.append(self) or orig(self))
    fps, n = measure.calibration(tmp_path, last=20)
    assert n == 20 and fps == 20.5        # runs 10..29: fps 11..30, median 20.5 (all 30 would give 16)
    assert len(seen) == 20                # the ten oldest run dirs were never stat'ed


def test_xp_gained_in_episode():
    rows = [{"step": 1, "party": [[1, 5, 100, 10, 10]]},
            {"step": 5, "party": [[1, 5, 140, 10, 10], [2, 9, 30, 8, 8]]},
            {"step": 9, "party": [[1, 6, 200, 10, 10], [2, 9, 80, 8, 8]]}]
    assert measure.xp_gained_in_episode(rows, 1, 9) == 180     # (200+80) - 100
    assert measure.xp_gained_in_episode(rows, 5, 9) == 110     # (200+80) - (140+30): between the snapshots
    assert measure.xp_gained_in_episode(rows, 0, 9) == 180     # no row at/before 0: the first stands in
    assert measure.xp_gained_in_episode([], 0, 9) == 0
