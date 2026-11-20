"""The trainer sight survey on a scripted FakeEmulator timeline: per-tile engage/start rows,
the per-trainer max_engage_dist / start_before_engage summaries, and the MAX_RUNS cap. No ROM."""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.glitch_signals import ENGAGED_TRAINER_CLASS
from pokeagent.glitchlab import survey
from pokeagent.novelty import discoveries as dc

KB = {"map_trainers": {"9": [{"class": "YOUNGSTER", "party": 1, "x": 10, "y": 8},
                             {"class": "BUG CATCHER", "party": 1, "x": 4, "y": 4},
                             {"class": "LASS", "party": 1, "x": 2, "y": 2}]},
      "trainers": {}}
DISTS = (2, 3, 4, 5, 6)


class SpotEmu(FakeEmulator):
    """Sets wEngagedTrainerClass after ``engage_after`` recorded presses (the fake's "!"
    moment); its ``menu`` flag toggles on each START press, an honest start_menu_open."""

    def __init__(self, engage_after):
        super().__init__()
        self.engage_after = engage_after
        self.menu = False

    def press(self, button, hold_frames=8, settle_frames=16):
        super().press(button, hold_frames, settle_frames)
        if button == Button.START:
            self.menu = not self.menu
        if len(self.presses) == self.engage_after:
            self.set(ENGAGED_TRAINER_CLASS, 5)


def _factory_for(sights, dists=DISTS):
    """emu_factory producing one SpotEmu per (trainer, distance) run in survey order: the
    trainer engages when the player reaches its sight distance (press 1 if already inside)."""
    plans = []
    for t in KB["map_trainers"]["9"]:
        for d in dists:
            s = sights.get(t["class"], 0)
            plans.append(max(1, d - s + 1) if s else 10 ** 9)
    it = iter(SpotEmu(p) for p in plans)
    return lambda _path: next(it)


def test_survey_measures_sight_ranges_per_trainer(tmp_path):
    state = tmp_path / "near.state"
    state.write_bytes(b"fake state")
    factory = _factory_for({"YOUNGSTER": 4, "BUG CATCHER": 2})   # LASS never engages
    out = survey.survey_map(factory, state, 9, KB, distances=DISTS, approach_presses=("UP",),
                            out_dir=tmp_path, menu_probe=lambda e: e.menu)
    assert out["runs"] == 15 and "aborted" not in out and out["map"] == 9
    a, b, c = out["trainers"]
    assert (a["class"], a["max_engage_dist"], a["start_before_engage"]) == ("YOUNGSTER", 4, False)
    assert (b["class"], b["max_engage_dist"], b["start_before_engage"]) == ("BUG CATCHER", 2, False)
    assert (c["class"], c["max_engage_dist"], c["start_before_engage"]) == ("LASS", None, True)

    report = Path(out["report"])
    assert report == tmp_path / "discoveries" / "glitchlab-survey-9.jsonl"
    rows = [json.loads(ln) for ln in report.read_text().splitlines()]
    keys = {"map", "trainer_idx", "class", "x", "y", "dist", "start_opened",
            "engaged", "misc_flags", "status5"}
    assert rows and all(keys <= set(r) for r in rows)
    # trainer 0 (sight 4): engaged only once the walk reaches tile 4
    seen = {r["dist"]: r["engaged"] for r in rows if r["trainer_idx"] == 0 and r["dist"] >= 4}
    assert seen == {4: 5, 5: 0, 6: 0}
    # tile-1 rows carry the START press: menu opened while engaged -> start_opened still True
    last = [r for r in rows if r["trainer_idx"] == 2 and r["dist"] == 1]
    assert all(r["start_opened"] is True and r["engaged"] == 0 for r in last)
    # scratch copies land inside discoveries/ so they pass the discovery-state guard
    scratch = list((tmp_path / "discoveries").glob("*.scratch.state"))
    assert scratch and all(dc.is_discovery_state(p) for p in scratch)
    # the input state was only read, never written
    assert state.read_bytes() == b"fake state"


def test_survey_stops_at_the_run_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(survey, "MAX_RUNS", 3)
    state = tmp_path / "s.state"
    state.write_bytes(b"x")
    out = survey.survey_map(lambda p: FakeEmulator(), state, 9, KB, distances=(2, 3),
                            out_dir=tmp_path, menu_probe=lambda e: False)
    assert out["runs"] == 3 and out["aborted"] == "cap"
    assert len(out["trainers"]) == 2          # third trainer never started
