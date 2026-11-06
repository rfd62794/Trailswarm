import shutil
from pathlib import Path

import pytest

from pokeagent.ramlab import report
from pokeagent.ramlab.flags import flag_bits

ROOT = Path(__file__).resolve().parent.parent
ROM, STATE = ROOT / "roms" / "Pokemon Red.gb", ROOT / "runs" / "checkpoints" / "to_route1.state"


def finding(name, status, verified, score=1.0, event="money"):
    return {"addr": "0xD347", "name": name, "event": event, "kind": "inc1", "status": status, "verified": verified,
            "label": name, "evidence": "e", "stats": {"support": 5, "runs": 2, "specificity": 0.9, "consistency": 1.0, "score": score}}


def test_report_sections_and_coverage():
    entries = [{"name": "a", "addr": "0xD000", "size": 2, "region": "items", "verified": True},
               {"name": "b", "addr": "0xD002", "size": 1, "region": "items", "verified": False}]
    data = {"findings": [finding("wPlayerMoney", "confirms", True), finding("unk_D123", "new", False, 2.0)],
            "failed": [{**finding("wX", "confirms", False), "evidence": "replay: 0/3"}], "flags": []}
    bits = flag_bits([{"run": "r", "map": 0, "x": 5, "y": 6, "text": "hi", "d": [[0xD74B, 0, 1]]}])
    txt = report.build(entries, data, bits, 10, 2, flipped=1)
    for needle in ("NEWLY CONFIRMED labels (1", "NEW FINDINGS (1", "FAILED HYPOTHESES (1", "items", "1 /    2 labels",
                   "D74B.0", "Pallet Town (5,6)"):
        assert needle in txt


@pytest.mark.skipif(not (ROM.is_file() and STATE.is_file()), reason="needs the ROM and a checkpoint")
def test_headless_run_with_ram_diff_replays_in_sync(tmp_path):
    from pokeagent.ramlab.headless import run_agent
    from pokeagent.ramlab.records import load_all
    from pokeagent.ramlab.replay import Replayer, load_trace
    states = tmp_path / "states"; states.mkdir()
    shutil.copy(STATE, states / "to_route1.state")
    run = tmp_path / "run"
    res = run_agent(ROM, states / "to_route1.state", tmp_path / "maps.json", run, 40, ram_diff=True, seed=3)
    assert res["steps"] == 40 and res["records"] > 0 and res["ram_diff_share"] < 0.2
    recs, metas = load_all([run])
    meta, presses = load_trace(run)
    assert len(presses) >= 40 and meta["start"] == "to_route1"
    rec = next(r for r in recs if r["d"] and r["step"] > 3)
    rep = Replayer(ROM, states, tmp_path / "tmp")
    try:
        pre = rep.pre_states(run, [rec["step"]])
        ev, _ = rep.branches(pre[rec["step"]], presses[rec["step"] - 1], 60, [a for a, _, _ in rec["d"][:4]])
    finally:
        rep.close()
    for addr, before, after in rec["d"][:4]:
        assert ev[addr][0] == before, "replay out of sync with the recorded run"
