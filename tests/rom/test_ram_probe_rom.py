"""ROM-backed probe smoke test: a one-event probe (up from bedroom) writes its run dir under the
given out root. Skips without the ROM; the controller runs this on the laptop.
"""
from rom_helpers import STATES, load


def test_probe_run_writes_report_dir(rom_emu, tmp_path):
    from pokeagent.ramlab import probe
    from pokeagent.ramlab.labels import load_entries
    emu = load(rom_emu, "bedroom")
    script = {"version": 1, "game": "pokemon-red", "idle_frames": 10, "repeat": 1,
              "events": [{"label": "step_up", "presses": ["up"]}]}
    run_dir = probe.probe_run(emu, STATES / "bedroom.state", script, load_entries(),
                              tmp_path, "pokemon-red")
    assert run_dir.parent == tmp_path and run_dir.name.startswith("ramprobe-pokemon-red-bedroom-")
    assert (run_dir / "probe.json").is_file() and (run_dir / "report.txt").is_file()
