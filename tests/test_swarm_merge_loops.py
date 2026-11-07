"""merge_loops: the swarm merge rule for the shared 'loops' dead-action table."""
import importlib.util
import json
import sys
from pathlib import Path

from pokeagent.explorer.loop_memory import LOOP_PROMOTE_RUNS, LOOP_RUNS_KEPT, LOOP_TTL_DAYS

TOOLS = Path(__file__).resolve().parents[1] / "tools"
NOW = 1_700_000_000


def _load(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}_ml", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sm = _load("swarm_merge")


def e(runs, last=NOW, clear=0):
    return {"runs": list(runs), "last": last, "clear": clear}


def test_union_of_runs_max_of_times_never_summed():
    dst = {"loops": {"k": e(["a", "b"], last=NOW - 10, clear=NOW - 20)}}
    sm.merge_loops(dst, {"loops": {"k": e(["b", "c"], last=NOW - 5, clear=1)}}, now=NOW)
    assert dst["loops"]["k"] == {"runs": ["a", "b", "c"], "last": NOW - 5, "clear": NOW - 20}


def test_runs_capped_to_the_newest_kept():
    dst = {"loops": {"k": e([f"d{i}" for i in range(8)])}}
    sm.merge_loops(dst, {"loops": {"k": e([f"s{i}" for i in range(8)])}}, now=NOW)
    assert dst["loops"]["k"]["runs"] == [f"d{i}" for i in range(8 - (LOOP_RUNS_KEPT - 8), 8)] + \
        [f"s{i}" for i in range(8)]
    assert len(dst["loops"]["k"]["runs"]) == LOOP_RUNS_KEPT


def test_merging_the_same_src_twice_changes_nothing():
    dst = {"loops": {"k": e(["a"])}}
    src = {"loops": {"k": e(["a", "b"])}}
    sm.merge_loops(dst, src, now=NOW)
    first = json.loads(json.dumps(dst))
    sm.merge_loops(dst, src, now=NOW)
    assert dst == first and dst["loops"]["k"]["runs"] == ["a", "b"]


def test_stale_cleared_underpromoted_and_malformed_dropped():
    dst = {"loops": {
        "old": e(["a", "b", "c"], last=NOW - LOOP_TTL_DAYS * 86400),           # stale
        "cleared": e(["a"], last=NOW - 10, clear=NOW - 10),                    # cleared while never promoted
        "mal": "junk",
        "keep": e(["a"], last=NOW),
        "history": e(["a", "b", "c"], last=NOW - 10, clear=NOW - 10),          # cleared but promoted: stays
    }}
    sm.merge_loops(dst, {"loops": {}}, now=NOW)
    assert set(dst["loops"]) == {"keep", "history"}


def test_malformed_loops_is_ignored():
    dst = {"maps": {}}
    sm.merge_loops(dst, {"loops": "junk"}, now=NOW)
    assert "loops" not in dst
    dst2 = {"loops": "junk"}
    sm.merge_loops(dst2, {"loops": {"k": e(["a"])}}, now=NOW)
    assert dst2["loops"] == {"k": e(["a"])}


def test_merge_memory_calls_merge_loops():
    import time
    dst = {"maps": {}}
    sm.merge_memory(dst, {"maps": {}, "loops": {"35,5,20,A": e(["x", "y"], last=time.time())}})
    assert dst["loops"]["35,5,20,A"]["runs"] == ["x", "y"]
