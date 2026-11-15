"""brain seed: flagless copy equals the source; each strip flag removes exactly its data."""
import copy
import io
import json
from contextlib import redirect_stdout

import pokeagent.brain as brain
from pokeagent.cli_brain import main as brain_main


def _data():
    return {"updated": "2026-01-01T00:00:00",
            "loops": {"a": {"runs": ["r1"]}, "b": {"runs": []}},
            "grass_ids": {"0": {"0102": 3}},
            "maps": {
                "1": {"visited": {"0,0": 1},
                      "encounters": {"0,0": 2},
                      "demos": [{"at": [1, 1], "screen": 1}, {"at": [2, 2], "screen": 2}],
                      "interactions": {"1,1,UP": {"count": 1, "done": True, "done_run": "r1"},
                                       "2,2,DOWN": {"count": 3}},
                      "npcs": {"n1": {"pic": 4, "last": [3, 3],
                                    "results": {"count": 1, "done": True}},
                               "n2": {"pic": 5, "last": [4, 4], "results": {"count": 2}}}},
                "2": {"visited": {"5,5": 1}, "encounters": {"5,5": 1}},
            }}


def test_no_flags_copies_document():
    data = _data()
    out, removed = brain.seed_memory(data)
    assert out == data and out is not data
    assert removed == {"encounters": 0, "loops": 0, "demos": 0,
                       "playthrough_state": {"interaction_done": 0, "npc_results_done": 0}}


def test_each_flag_removes_exactly_its_data():
    data = _data()
    out, removed = brain.seed_memory(data, no_encounters=True)
    assert removed["encounters"] == 2
    assert all("encounters" not in m for m in out["maps"].values())
    assert out["loops"] == data["loops"] and "demos" in out["maps"]["1"]

    out, removed = brain.seed_memory(data, no_loops=True)
    assert removed["loops"] == 2 and "loops" not in out

    out, removed = brain.seed_memory(data, no_demos=True)
    assert removed["demos"] == 2 and "demos" not in out["maps"]["1"]

    out, removed = brain.seed_memory(data, no_playthrough_state=True)
    assert removed["playthrough_state"] == {"interaction_done": 1, "npc_results_done": 1}
    inter = out["maps"]["1"]["interactions"]
    assert "done" not in inter["1,1,UP"] and inter["1,1,UP"]["done_run"] == "r1"  # only "done" goes
    assert inter["2,2,DOWN"] == {"count": 3}
    npcs = out["maps"]["1"]["npcs"]
    assert "done" not in npcs["n1"]["results"] and npcs["n1"]["results"]["count"] == 1
    assert npcs["n2"]["results"] == {"count": 2}


def test_input_never_mutated():
    data = _data()
    snapshot = copy.deepcopy(data)
    brain.seed_memory(data, no_encounters=True, no_loops=True, no_demos=True,
                      no_playthrough_state=True)
    assert data == snapshot


# --- CLI ---

def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = brain_main(argv)
    return rc, buf.getvalue()


def test_cli_seed_refusals_and_happy_path(tmp_path):
    src = tmp_path / "src.json"
    src.write_text(json.dumps(_data()), encoding="utf-8")
    src_bytes = src.read_bytes()

    rc, out = _run(["seed", str(src), str(src)])
    assert rc == 1 and not (tmp_path / "src.json.out").exists()

    dst = tmp_path / "dst.json"
    dst.write_text("{}", encoding="utf-8")
    rc, out = _run(["seed", str(src), str(dst)])
    assert rc == 1 and dst.read_text() == "{}"

    dst.unlink()
    rc, out = _run(["seed", str(src), str(dst), "--no-encounters", "--no-loops", "--text"])
    assert rc == 0 and "encounters=2" in out and "loops=2" in out
    seeded = json.loads(dst.read_text(encoding="utf-8"))
    assert "loops" not in seeded and all("encounters" not in m for m in seeded["maps"].values())
    assert seeded["maps"]["1"]["visited"] == {"0,0": 1}
    assert src.read_bytes() == src_bytes  # SRC never written, journal never touched

    dst2 = tmp_path / "dst2.json"
    rc, out = _run(["seed", str(src), str(dst2)])
    assert rc == 0
    rep = json.loads(out)
    assert rep["maps"] == 2 and rep["top_level_keys_kept"] == len(_data())
    assert rep["removed"]["encounters"] == 0 and rep["removed"]["playthrough_state"] == {
        "interaction_done": 0, "npc_results_done": 0}
    assert json.loads(dst2.read_text(encoding="utf-8")) == _data()  # no flag: copy equals source
