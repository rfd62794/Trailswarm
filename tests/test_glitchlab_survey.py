"""The engagement survey on FakeEmulator timelines: no stale-byte engagement, the seen edge, off-line and
blocked reasons, the adjacent START probe and the MAX_RUNS cap. No ROM."""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.glitch_signals import ENGAGED_TRAINER_CLASS, MISC_FLAGS
from pokeagent.glitchlab import sprites as sp
from pokeagent.glitchlab import survey
from pokeagent.ram import RAM_MAP


class WalkEmu(FakeEmulator):
    """Player at (px, py); UP/DOWN/LEFT/RIGHT move it unless ``wall``; misc bit 0 set when within ``sees`` tiles."""

    def __init__(self, trainers, px, py, sees=None, wall=False, stale=0):
        super().__init__()
        for i, (x, y, facing) in enumerate(trainers, start=1):
            b = sp.SPRITE_STATE1 + 16 * i
            self.set(b, 1)
            self.set(b + 9, facing)
            self.set(sp.SPRITE_STATE2 + 16 * i + 4, y + 4)
            self.set(sp.SPRITE_STATE2 + 16 * i + 5, x + 4)
            self.set(sp.MAP_SPRITE_EXTRA + (i - 1) * 2, 201)
        self.trainers, self.sees, self.wall = trainers, sees, wall
        self.set(RAM_MAP["player_x"], px)
        self.set(RAM_MAP["player_y"], py)
        self.set(ENGAGED_TRAINER_CLASS, stale)
        self.menu = False

    def press(self, button, hold_frames=8, settle_frames=16):
        super().press(button, hold_frames, settle_frames)
        if button == Button.START:
            self.menu = True
            return
        d = {Button.UP: (0, -1), Button.DOWN: (0, 1), Button.LEFT: (-1, 0), Button.RIGHT: (1, 0)}[button]
        if not self.wall:
            self.set(RAM_MAP["player_x"], self.read(RAM_MAP["player_x"]) + d[0])
            self.set(RAM_MAP["player_y"], self.read(RAM_MAP["player_y"]) + d[1])
        if self.sees and self.trainers:
            x, y, _ = self.trainers[0]
            if abs(self.read(RAM_MAP["player_x"]) - x) + abs(self.read(RAM_MAP["player_y"]) - y) <= self.sees:
                self.set(MISC_FLAGS, 1)


def run(tmp_path, emus, **kw):
    state = tmp_path / "s.state"
    state.write_bytes(b"fake")
    it = iter(emus)
    out = survey.survey_map(lambda _p: next(it), state, 9, None, out_dir=tmp_path, **kw)
    rows = [json.loads(ln) for ln in Path(out["report"]).read_text().splitlines()]
    return out, rows


def test_no_trainer_and_stale_engaged_class_means_nothing_engaged(tmp_path):
    out, rows = run(tmp_path, [WalkEmu([], 10, 14, stale=21)])
    assert out["trainers"] == [] and not any(r.get("engaged") for r in rows)


def test_engagement_edge_stops_the_walk_at_the_spotting_tile(tmp_path):
    t = [(10, 8, 0)]
    scout, walker = WalkEmu(t, 10, 14, sees=3), WalkEmu(t, 10, 14, sees=3)
    out, rows = run(tmp_path, [scout, walker])
    tr = out["trainers"][0]
    assert tr["engage_dist"] == 3 and tr["reason"] is None and tr["facing"] == "down"
    by = {r["dist"]: r for r in rows}
    assert by[4]["engaged"] is False and by[4]["edge"] is None
    assert by[3]["engaged"] is True and by[3]["edge"] == "seen" and 2 not in by
    assert len(walker.presses) == 3 and Button.START not in walker.presses
    assert Path(out["report"]) == tmp_path / "discoveries" / "glitchlab-survey-9.jsonl"


def test_off_line_trainer_gets_no_presses(tmp_path):
    walker = WalkEmu([(10, 8, 0)], 11, 14, sees=3)
    out, rows = run(tmp_path, [WalkEmu([(10, 8, 0)], 11, 14), walker])
    assert out["trainers"][0]["reason"] == "off_line" and walker.presses == []
    assert rows[0]["reason"] == "off_line"


def test_a_wall_reports_blocked(tmp_path):
    t = [(10, 8, 0)]
    out, _ = run(tmp_path, [WalkEmu(t, 10, 14), WalkEmu(t, 10, 14, wall=True)])
    assert out["trainers"][0]["reason"] == "blocked"


def test_never_engaging_trainer_ends_adjacent_with_one_start(tmp_path):
    t = [(10, 8, 0)]
    for opened, expect in ((True, True), (False, False)):
        walker = WalkEmu(t, 10, 12)
        out, rows = run(tmp_path, [WalkEmu(t, 10, 12), walker], menu_probe=lambda e, o=opened: o)
        assert walker.presses.count(Button.START) == 1 and walker.presses[-1] == Button.START
        assert out["trainers"][0]["engage_dist"] is None
        assert out["trainers"][0]["start_before_engage"] is expect
        assert rows[-1]["dist"] == 1 and rows[-1]["start_opened"] is opened


def test_survey_stops_at_the_run_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(survey, "MAX_RUNS", 1)
    t = [(10, 8, 0), (2, 2, 0)]
    out, _ = run(tmp_path, [WalkEmu(t, 5, 5)] * 4)
    assert out["runs"] == 1 and out["aborted"] == "cap" and len(out["trainers"]) == 1
