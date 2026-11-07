"""``pokeagent review``: CLI wiring, --json shape, exit codes, registration under cli.py."""
import json
from pathlib import Path

import pytest

from pokeagent import cli, cli_review

FIX = Path(__file__).resolve().parent / "fixtures" / "review"
RUNS = FIX / "runs"
RUN_OK = "explore-20261107-150000-1001"
RUN_OK_B = "explore-20261107-150100-1006"
RUN_STALL = "explore-20261107-151000-1002"


@pytest.fixture(autouse=True)
def _no_real_invariants(monkeypatch):
    monkeypatch.setattr("pokeagent.invariants.runner.run_all", lambda *a, **k: [])


def test_run_text_and_exit_codes(capsys):
    assert cli_review.main(["run", RUN_OK, "--runs-dir", str(RUNS)]) == 0
    out = capsys.readouterr().out
    assert "run explore-20261107-150000-1001" in out and "end (inferred): solved" in out
    assert cli_review.main(["run", RUN_STALL, "--runs-dir", str(RUNS)]) == 1
    assert "BREAKS" in capsys.readouterr().out


def test_run_json_shape(capsys):
    assert cli_review.main(["run", RUN_OK, "--runs-dir", str(RUNS), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["run"] == RUN_OK and s["header"]["seed"] == 42 and s["breaks"] == []
    assert isinstance(s["events"], list)


def test_run_missing_is_usage_error(capsys):
    assert cli_review.main(["run", "explore-20990101-000000-1", "--runs-dir", str(RUNS)]) == 2
    assert "error" in capsys.readouterr().out
    assert cli_review.main(["run", "explore-20990101-000000-1", "--runs-dir", str(RUNS),
                            "--json"]) == 2
    assert "error" in json.loads(capsys.readouterr().out)


def test_swarm_json_and_exit_codes(capsys):
    argv = ["swarm", "--since", "2026-11-07T00:00:00", "--runs-dir", str(RUNS), "--json"]
    assert cli_review.main(argv) == 1                     # fixture has crashed/loop breaks
    s = json.loads(capsys.readouterr().out)
    assert s["broken"] and s["runs"]["count"] == 6
    argv += ["--segment", "to_bill"]
    assert cli_review.main(argv) == 0                     # one clean solved segment run
    s = json.loads(capsys.readouterr().out)
    assert not s["broken"] and s["runs"]["count"] == 1


def test_swarm_bad_since_is_usage_error(capsys):
    assert cli_review.main(["swarm", "--since", "bogus", "--runs-dir", str(RUNS)]) == 2
    assert "error" in capsys.readouterr().out


def test_diff_json(capsys):
    assert cli_review.main(["diff", RUN_OK, RUN_OK_B, "--runs-dir", str(RUNS), "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["divergence"]["step"] == 7
    assert cli_review.main(["diff", RUN_OK, "explore-20990101-000000-1",
                            "--runs-dir", str(RUNS)]) == 2


def test_replay_json_unrecoverable(capsys):
    assert cli_review.main(["replay", RUN_STALL, "--steps", "5",
                            "--runs-dir", str(RUNS), "--json"]) == 2
    s = json.loads(capsys.readouterr().out)
    assert s["status"] == "start_state_unrecoverable"


def test_review_registered_under_pokeagent_cli(capsys):
    assert cli.main(["review", "run", RUN_OK, "--runs-dir", str(RUNS), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["run"] == RUN_OK
