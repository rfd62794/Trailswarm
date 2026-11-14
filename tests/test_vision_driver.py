"""ScriptDriver reads the JSON shape; RandomWalkDriver is deterministic per seed and varies by seed."""
from __future__ import annotations

import json

from pokeagent.emulator import Button
from pokeagent.vision.driver import DIRECTIONS, RandomWalkDriver, ScriptDriver


def test_script_driver_yields_the_file_presses(tmp_path):
    path = tmp_path / "script.json"
    path.write_text(json.dumps({"game": "pokemon-red", "start_state": None,
                                "presses": [["up", 8, 16], ["a", 4, 4]]}))
    driver = ScriptDriver(path)
    assert driver.game == "pokemon-red" and driver.start_state is None
    assert list(driver.iter_presses()) == [(Button.UP, 8, 16), (Button.A, 4, 4)]


def test_script_driver_start_state(tmp_path):
    path = tmp_path / "script.json"
    path.write_text(json.dumps({"game": "pokemon-red", "start_state": "baselines/x.state",
                                "presses": []}))
    assert ScriptDriver(path).start_state == "baselines/x.state"


def test_random_walk_deterministic_per_seed_different_for_another():
    seq1 = list(RandomWalkDriver(1, 40, DIRECTIONS).iter_presses())
    assert seq1 == list(RandomWalkDriver(1, 40, DIRECTIONS).iter_presses())
    assert seq1 != list(RandomWalkDriver(2, 40, DIRECTIONS).iter_presses())
    buttons = {b for b, _h, _s in seq1}
    assert buttons <= {Button.UP, Button.DOWN, Button.LEFT, Button.RIGHT, Button.A}
    assert Button.A in buttons                                   # every ~10th press is `a`
    assert all((h, s) == (8, 16) for _b, h, s in seq1)
    assert len(seq1) == 40
