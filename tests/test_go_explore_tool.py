"""tools/go_explore.py: the argparse wrapper over runner.drive; --dry-run prints, never touches."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import go_explore  # noqa: E402

from pokeagent import statefp  # noqa: E402


def test_dry_run_prints_the_next_return_command(tmp_path, capsys):
    start = tmp_path / "start.state"
    start.write_bytes(b"state")
    code = go_explore.main(["--archive", str(tmp_path / "arch"), "--start-state", str(start),
                            "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "tools/explore_demo.py" in out and "--cell-dump" in out and "--headless" in out
    assert not (tmp_path / "arch" / "archive.json").exists()
    assert not (tmp_path / "arch" / "driver.lock").exists()


def test_synthetic_start_state_is_a_refusal(tmp_path, capsys):
    start = tmp_path / "synth.state"
    start.write_bytes(b"state")
    statefp.write(start, {"v": 1, "lineage": "synthetic"})
    code = go_explore.main(["--archive", str(tmp_path / "arch"), "--start-state", str(start),
                            "--dry-run"])
    captured = capsys.readouterr()
    assert code == 2 and captured.out == "" and "refused" in captured.err
