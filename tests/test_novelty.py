"""Novelty rewards and discoveries on synthetic state (no ROM, no real emulator): feature extraction, the sqrt decay, the
swarm-wide merge, kill-safe delta flushes, explorer-only steering and bandit pay, each discovery detector, and the
guarantee that a discovery save is never a checkpoint."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokeagent.bandit import reward as rw
from pokeagent.bandit.driver import BanditDriver
from pokeagent.checkpoint_goals import valid
from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours.frontier import _frontier_move
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.memory import MapMemory
from pokeagent.novelty import backfill as bf
from pokeagent.novelty import discoveries as dc
from pokeagent.novelty import features as ft
from pokeagent.novelty import steer
from pokeagent.novelty.store import apply_delta, delta_path_for, empty, load_table, merge_delta, write_delta
from pokeagent.novelty.tracker import NoveltyTracker

TOOLS = Path(__file__).resolve().parents[1] / "tools"
MAP, PX, PY = 0xD35E, 0xD362, 0xD361


def _tool(name):
    spec = importlib.util.spec_from_file_location(f"tool_{name}_nv", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def snap(map=1, x=5, y=5, flags=b"", bag=(), pc=(), money=0, party=(), in_battle=False, enemy=0):
    return ft.Snapshot(map, x, y, flags.ljust(ft.FLAGS_LEN, b"\0"), tuple(bag), tuple(pc), money, tuple(party), in_battle, enemy)


def mon(species=177, level=5, exp=100, moves=(33,), ident=(1, 2)):
    return (species, level, exp, tuple(moves), ident)


class Script:
    """A `read` for NoveltyTracker: yields the next scripted snapshot per call."""

    def __init__(self, *snaps):
        self.snaps = list(snaps)

    def __call__(self, emu):
        return self.snaps.pop(0)


def tracker(tmp_path, snaps, role="explorer", shared=None, clock=lambda: 1000.0, **kw):
    t = NoveltyTracker(shared or tmp_path / "novelty.json", tmp_path / "d.json", role, "run-a", runs_dir=tmp_path,
                       clock=clock, read=Script(*snaps), **kw)
    return t


# --- feature extraction ----------------------------------------------------------------------------------------------
def test_features_cover_the_state_and_ignore_text_and_screen():
    a = snap(map=1, x=5, y=5, bag=[(20, 3)], party=[mon(177, moves=(33, 45))], in_battle=True, enemy=24)
    keys = ft.features(a)
    assert {"t:1:5:5", "m:1", "i:20", "so:177", "mv:33", "mv:45", "ss:24"} <= set(keys)
    assert not [k for k in keys if k.split(":")[0] not in ft.WEIGHTS]  # every key is a state feature; nothing like text:/menu:/pix:
    b = snap(map=2, x=1, y=1)
    assert "w:1>2" in ft.features(b, a) and "w:1>2" not in ft.features(a)


def test_flag_bits_report_only_new_bits_with_a_previous_snapshot():
    prev, cur = bytes([0b0001, 0]), bytes([0b0101, 0b1000])
    assert ft.flag_bits(cur) == [0, 2, 11]
    assert ft.flag_bits(cur, prev) == [2, 11]
    assert ft.flag_bits(prev, cur) == []  # a cleared bit is not a find


def test_read_snapshot_reads_game_state_from_ram():
    emu = FakeEmulator({MAP: 7, PX: 3, PY: 4, 0xD747 + 5: 0b10, 0xD163: 1, 0xD16B: 177, 0xD16B + 8: 33, 0xD31D: 1, 0xD31E: 20, 0xD31F: 2})
    s = ft.read_snapshot(emu)
    assert (s.map, s.x, s.y, 5 * 8 + 1 in ft.flag_bits(s.flags)) == (7, 3, 4, True)
    assert s.bag == ((20, 2),) and s.party[0][0] == 177 and 33 in s.party[0][3]


# --- the sqrt decay --------------------------------------------------------------------------------------------------
def test_bonus_is_weight_over_sqrt_of_one_plus_count():
    assert ft.bonus("m:7", 0) == ft.WEIGHTS["m"]                      # first-ever discovery: full weight
    assert ft.bonus("m:7", 3) == pytest.approx(ft.WEIGHTS["m"] / 2)   # 1/sqrt(4)
    assert ft.bonus("t:1:2:3", 8) == pytest.approx(ft.WEIGHTS["t"] / 3)
    assert ft.bonus("m:7", 99) < ft.bonus("m:7", 9) < ft.bonus("m:7", 0)


def test_weight_order_map_flag_item_species_warp_tile():
    w = ft.WEIGHTS
    assert w["m"] > w["f"] > w["i"] > w["so"] > w["w"] > w["t"]


# --- the global merge counts each run once ---------------------------------------------------------------------------
def test_merge_counts_each_run_once_and_replaces_a_reflushed_run(tmp_path):
    shared = tmp_path / "novelty.json"
    d = delta_path_for(tmp_path / "agent3-7.json")
    assert d.name == "agent3-7.novelty.json"
    write_delta(d, "r1", "explorer", {"m:7": 1.0, "t:7:1:1": 1.0}, {})
    assert merge_delta(shared, d, remove=False)
    assert merge_delta(shared, d, remove=False) is False                        # same delta again: no change
    assert load_table(shared)["counts"] == {"m:7": 1, "t:7:1:1": 1}
    write_delta(d, "r1", "explorer", {"m:7": 1.0, "t:7:1:1": 1.0, "t:7:1:2": 2.0}, {})  # the run found one more tile
    assert merge_delta(shared, d, remove=False)
    assert load_table(shared)["counts"] == {"m:7": 1, "t:7:1:1": 1, "t:7:1:2": 1}  # replaced, not added
    write_delta(d, "r2", "exploiter", {"m:7": 5.0}, {})
    assert merge_delta(shared, d)                                               # remove=True consumes the delta
    t = load_table(shared)
    assert t["counts"]["m:7"] == 2 and not d.exists()
    assert t["role_runs"] == {"explorer": 1, "exploiter": 1} and t["first"]["m:7"][1] == "explorer"


def test_merge_ignores_a_torn_delta(tmp_path):
    d = tmp_path / "x.novelty.json"
    d.write_text("{not json")
    assert merge_delta(tmp_path / "novelty.json", d) is False


def test_stage_keeps_the_earliest_goal_index_seen():
    t = empty()
    apply_delta(t, {"run_id": "a", "found": {"f:9": 1}, "stage": {"f:9": 12}})
    apply_delta(t, {"run_id": "b", "found": {"f:9": 2}, "stage": {"f:9": 8}})
    assert t["stage"]["f:9"] == 8 and t["counts"]["f:9"] == 2


# --- the tracker: baseline, bonus, flush survives a kill -------------------------------------------------------------
def test_start_state_is_baseline_then_new_features_pay_by_global_rarity(tmp_path):
    shared = tmp_path / "novelty.json"
    write_delta(tmp_path / "s.json", "old", "explorer", {"m:2": 1.0, "t:2:1:1": 1.0}, {})
    merge_delta(shared, tmp_path / "s.json")
    t = tracker(tmp_path, [snap(map=1, x=1, y=1), snap(map=1, x=1, y=2), snap(map=2, x=1, y=1)], shared=shared)
    assert t.observe(None, 1) == 0.0                                   # baseline: nothing found
    g1 = t.observe(None, 2)
    assert g1 == pytest.approx(ft.bonus("t:1:1:2", 0))                 # new tile nobody found
    g2 = t.observe(None, 3)                                            # map 2 + tile 2:1:1 (found by 1 run) + warp 1>2
    assert g2 == pytest.approx(ft.bonus("m:2", 1) + ft.bonus("t:2:1:1", 1) + ft.bonus("w:1>2", 0))


def test_no_double_pay_for_a_feature_seen_twice_in_one_run(tmp_path):
    t = tracker(tmp_path, [snap(x=1), snap(x=2), snap(x=1), snap(x=2)])
    t.observe(None, 1); t.observe(None, 2)
    assert t.observe(None, 3) == 0.0 and t.observe(None, 4) == 0.0


def test_delta_is_flushed_on_every_find_so_a_kill_loses_nothing(tmp_path):
    t = tracker(tmp_path, [snap(x=1), snap(x=2), snap(x=3)])
    t.observe(None, 1)
    assert not (tmp_path / "d.json").exists()                          # nothing found yet
    t.observe(None, 2)
    on_disk = json.loads((tmp_path / "d.json").read_text())           # killed here: this is what the supervisor merges
    assert set(on_disk["found"]) == {"t:1:2:5"} and on_disk["run_id"] == "run-a" and on_disk["role"] == "explorer"
    t.observe(None, 3)
    assert set(json.loads((tmp_path / "d.json").read_text())["found"]) == {"t:1:2:5", "t:1:3:5"}
    assert merge_delta(tmp_path / "novelty.json", tmp_path / "d.json")
    assert load_table(tmp_path / "novelty.json")["counts"] == {"t:1:2:5": 1, "t:1:3:5": 1}


def test_only_the_explorer_role_is_paid_but_every_role_counts(tmp_path):
    snaps = [snap(x=1), snap(map=9, x=1)]
    ex = tracker(tmp_path, list(snaps), role="exploiter")
    ex.observe(None, 1)
    assert ex.observe(None, 2) == 0.0                                  # not paid...
    assert "m:9" in json.loads((tmp_path / "d.json").read_text())["found"]  # ...but counted for the swarm
    assert ex.rewarding is False


def test_flag_stage_is_recorded_with_the_find(tmp_path):
    flags = bytes([0b100])
    t = tracker(tmp_path, [snap(), snap(flags=flags)], stage_fn=lambda: 7)
    t.observe(None, 1); t.observe(None, 2)
    assert json.loads((tmp_path / "d.json").read_text())["stage"] == {"f:2": 7}


# --- explorer-only effect on frontier scoring ------------------------------------------------------------------------
def frontier_ctx(tmp_path, role, counts):
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(1)
    for x in range(9):
        d["visited"][f"{x},5"] = 1
        d["blocked"] += [f"{x},5,UP", f"{x},5,DOWN"]
    emu = FakeEmulator({MAP: 1, PX: 4, PY: 5})
    ctx = ExplorerContext(emu=emu, mem=mem, opts=ExplorerOptions(role=role), run_dir=tmp_path, stable_frames=10, facing="RIGHT")
    if counts is not None:
        ctx.novelty = NoveltyTracker(tmp_path / "none.json", tmp_path / "d.json", role, "r", runs_dir=tmp_path)
        ctx.novelty.counts.update(counts)
    ctx.refresh()
    return ctx


WEST_WELL_TRODDEN = {"t:1:-1:5": 400}  # the swarm has stood west of the corridor 400 times; nobody east of it


def test_explorer_prefers_the_frontier_the_swarm_has_seen_least(tmp_path):
    ctx = frontier_ctx(tmp_path, "explorer", WEST_WELL_TRODDEN)
    assert steer.active(ctx)
    button, why = _frontier_move(ctx, 1, 4, 5)
    assert button == "RIGHT" and ctx.frontier_target == (1, 8, 5), why


def test_exploiter_and_flag_off_runs_are_unchanged(tmp_path):
    for role, counts in (("exploiter", WEST_WELL_TRODDEN), ("explorer", None), ("", None)):
        ctx = frontier_ctx(tmp_path, role, counts)
        assert not steer.active(ctx)
        button, _ = _frontier_move(ctx, 1, 4, 5)
        assert button == "LEFT" and ctx.frontier_target == (1, 0, 5), role  # the equidistant tie the Explorer always broke west


def test_steering_is_bounded_distance_still_dominates(tmp_path):
    ctx = frontier_ctx(tmp_path, "explorer", {"t:1:-1:5": 400})
    ctx.mem.m(1)["blocked"].remove("4,5,UP")                            # a frontier right here (distance 0 is skipped: route empty)
    node, route = steer.plan(ctx, 1, 4, 5)
    assert node in ((1, 8, 5), (1, 0, 5)) and len(route) == 4
    far = steer.plan(ctx, 1, 0, 5)                                      # standing at the west end: the east end is 8 away, west is 0
    assert far is None or len(far[1]) <= 8


# --- bandit novelty term -----------------------------------------------------------------------------------------------
def test_novelty_is_small_capped_and_default_off_in_the_bandit_reward():
    ep = rw.Episode("wild_battle", "k", "fight", "fight")
    ep.add({"step": 1, "outcome": "moved"})
    base = ep.reward
    ep.add({"event": "novelty", "bonus": 1.0})
    assert ep.reward == pytest.approx(base + rw.NOVELTY_SCALE * 1.0)
    for _ in range(50):
        ep.add({"event": "novelty", "bonus": 5.0})
    assert ep.novelty == pytest.approx(rw.NOVELTY_CAP) and rw.NOVELTY_CAP < rw.GOAL    # a goal still outweighs all the novelty
    plain = rw.Episode("wild_battle", "k", "fight", "fight")
    plain.add({"step": 1, "outcome": "moved"})
    assert plain.reward == base                                          # no novelty event, no change


def test_engine_pays_novelty_into_the_bandit_only_when_the_tracker_returns_a_bonus(tmp_path):
    ctx = frontier_ctx(tmp_path, "explorer", {})
    drv = BanditDriver(tmp_path / "b.json", tmp_path / "bd.json", 1)
    ctx.bandit = drv
    ep = rw.Episode("heal", "k", "heal_now", "heal_now")
    drv.open.append(ep)
    ctx.novelty = SimpleNamespace(observe=lambda emu, step: 2.0)
    Engine(ctx)._note_novelty()
    assert ep.novelty == pytest.approx(rw.NOVELTY_SCALE * 2.0)
    ctx.novelty = SimpleNamespace(observe=lambda emu, step: 0.0)         # an exploiter's tracker returns 0
    Engine(ctx)._note_novelty()
    assert ep.novelty == pytest.approx(rw.NOVELTY_SCALE * 2.0)


def test_engine_swallows_a_tracker_error(tmp_path):
    ctx = frontier_ctx(tmp_path, "explorer", {})
    logs = []
    ctx.log = lambda t, tag=None: logs.append(t)
    ctx.novelty = SimpleNamespace(observe=lambda emu, step: 1 / 0)
    Engine(ctx)._note_novelty()
    assert "novelty skipped" in logs[0]


# --- discovery detectors -----------------------------------------------------------------------------------------------
def disc(tmp_path, step=10):
    return dc.DiscoveryLog(tmp_path, "run-a", "explorer", clock=lambda: 5.0)


def ctx_for(**kw):
    return {"counts": {}, "maps_known": True, "stage": {}, "seen_species": set(), "stage_now": None, **kw}


def test_glitch_map_and_never_seen_map(tmp_path):
    assert dc.odd_map(250) and dc.odd_map(11) and not dc.odd_map(1)           # past the table / UNUSED_MAP_0B / PALLET_TOWN
    emu = FakeEmulator({1: 2})
    out = disc(tmp_path).check(snap(map=1), snap(map=250), 3, emu, ctx_for())
    assert [(r["kind"], r["feature"], r["before"], r["after"]) for r in out] == [("glitch_map", "m:250", 1, 250)]
    out = disc(tmp_path).check(snap(map=1), snap(map=5), 3, emu, ctx_for())
    assert out[0]["kind"] == "new_map"
    assert disc(tmp_path).check(snap(map=1), snap(map=5), 3, emu, ctx_for(counts={"m:5": 4})) == []
    assert disc(tmp_path).check(snap(map=1), snap(map=5), 3, emu, ctx_for(maps_known=False)) == []   # empty table: nothing is "new"


def test_flag_set_out_of_campaign_order(tmp_path):
    flags = bytes([0b1000])
    c = ctx_for(stage={"f:3": 20}, stage_now=4)                                # usually set at goal 20, now at goal 4
    out = disc(tmp_path).check(snap(), snap(flags=flags), 3, FakeEmulator(), c)
    assert out and out[0]["kind"] == "flag_out_of_order" and (out[0]["before"], out[0]["after"]) == (20, 4)
    assert disc(tmp_path).check(snap(), snap(flags=flags), 3, FakeEmulator(), ctx_for(stage={"f:3": 20}, stage_now=18)) == []  # within slack
    assert disc(tmp_path).check(snap(), snap(flags=flags), 3, FakeEmulator(), ctx_for(stage_now=4)) == []                      # never seen: no baseline


def test_item_duplication_vs_pickup_purchase_and_pc_withdraw(tmp_path):
    d = lambda: disc(tmp_path)
    emu = FakeEmulator()
    dup = d().check(snap(bag=[(20, 1)]), snap(bag=[(20, 9)]), 3, emu, ctx_for())
    assert dup and dup[0]["kind"] == "item_jump" and (dup[0]["before"], dup[0]["after"]) == (1, 9)
    assert d().check(snap(bag=[(20, 1)]), snap(bag=[(20, 2)]), 3, emu, ctx_for()) == []                         # a pickup
    assert d().check(snap(bag=[(20, 1)], money=3000), snap(bag=[(20, 6)], money=1500), 3, emu, ctx_for()) == []  # bought 5
    assert d().check(snap(bag=[], pc=[(20, 9)]), snap(bag=[(20, 9)], pc=[]), 3, emu, ctx_for()) == []             # PC withdraw


def test_money_jump_vs_prize_and_sale(tmp_path):
    emu = FakeEmulator()
    assert disc(tmp_path).check(snap(money=100), snap(money=9100), 50, emu, ctx_for())[0]["kind"] == "money_jump"
    lg = disc(tmp_path)
    lg.check(snap(in_battle=True), snap(in_battle=True), 40, emu, ctx_for())                                     # a battle at step 40
    assert lg.check(snap(money=100), snap(money=900), 45, emu, ctx_for()) == []                                  # prize shortly after
    assert disc(tmp_path).check(snap(money=100, bag=[(20, 3)]), snap(money=500, bag=[(20, 1)]), 50, emu, ctx_for()) == []  # a sale


def test_level_gained_without_xp(tmp_path):
    emu = FakeEmulator()
    out = disc(tmp_path).check(snap(party=[mon(level=5, exp=100)]), snap(party=[mon(level=6, exp=100)]), 3, emu, ctx_for())
    assert out and out[0]["kind"] == "level_without_xp"
    assert disc(tmp_path).check(snap(party=[mon(level=5, exp=100)]), snap(party=[mon(level=6, exp=180)]), 3, emu, ctx_for()) == []  # normal level up
    lg = disc(tmp_path)    # exp is written first, the level field catches up later: not a level without XP
    lg.check(None, snap(party=[mon(level=5, exp=100)]), 1, emu, ctx_for())
    lg.check(snap(party=[mon(level=5, exp=100)]), snap(party=[mon(level=5, exp=342)]), 2, emu, ctx_for())
    assert lg.check(snap(party=[mon(level=5, exp=342)]), snap(party=[mon(level=6, exp=342)]), 3, emu, ctx_for()) == []
    # a re-ordered party (the mon changed slot) is followed by identity, not slot
    a, b = mon(177, 5, 100, ident=(1, 2)), mon(25, 9, 400, ident=(7, 8))
    assert disc(tmp_path).check(snap(party=[a, b]), snap(party=[b, a]), 3, emu, ctx_for()) == []


def test_species_obtained_without_being_seen(tmp_path):
    emu = FakeEmulator()
    prev, cur = snap(party=[mon(177, ident=(1, 2))]), snap(party=[mon(177, ident=(1, 2)), mon(150, ident=(3, 4))])
    out = disc(tmp_path).check(prev, cur, 3, emu, ctx_for())
    assert out and out[0]["kind"] == "species_unseen" and out[0]["after"] == 150
    assert disc(tmp_path).check(prev, cur, 3, emu, ctx_for(seen_species={150})) == []                           # met in battle this run
    assert disc(tmp_path).check(prev, cur, 3, emu, ctx_for(counts={"ss:150": 2})) == []                         # met by the swarm
    evolved = snap(party=[mon(178, ident=(1, 2))])
    assert disc(tmp_path).check(prev, evolved, 3, emu, ctx_for()) == []                                         # an evolution


def test_record_has_run_step_feature_before_after_and_a_state_file(tmp_path):
    out = disc(tmp_path).check(snap(map=1), snap(map=250), 77, FakeEmulator({1: 2}), ctx_for())[0]
    for key in ("run", "step", "feature", "before", "after", "state", "kind", "role"):
        assert key in out
    assert out["step"] == 77 and out["run"] == "run-a"
    st = Path(out["state"])
    assert st.exists() and st.parent == tmp_path / "discoveries" and st.name.endswith(".discovery.state")
    assert json.loads((tmp_path / "discoveries.jsonl").read_text().splitlines()[0]) == out


def test_one_record_per_event_per_run_and_a_cap(tmp_path):
    lg = disc(tmp_path)
    for step in range(3):
        lg.check(snap(map=1), snap(map=250), step, FakeEmulator(), ctx_for())
    assert len(lg.records) == 1
    for m in range(248, 256):
        lg.check(snap(map=1), snap(map=m), m, FakeEmulator(), ctx_for())
    assert len(lg.records) == 1 + 7   # 250 was already logged; 248..255 minus it
    lg.check(snap(map=1), snap(map=11), 99, FakeEmulator(), ctx_for())
    assert len(lg.records) <= dc.MAX_PER_RUN


def test_a_detector_that_raises_never_stops_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "DETECTORS", (lambda *a: 1 / 0, dc.new_map))
    assert disc(tmp_path).check(snap(map=1), snap(map=250), 3, FakeEmulator(), ctx_for())[0]["kind"] == "glitch_map"


def test_tracker_runs_the_detectors_for_every_role(tmp_path):
    t = tracker(tmp_path, [snap(map=1), snap(map=250)], role="exploiter")
    t.observe(FakeEmulator(), 1); t.observe(FakeEmulator(), 2)
    assert [r["kind"] for r in t.disc.records] == ["glitch_map"] and t.disc.records[0]["role"] == "exploiter"


# --- discovery saves are never checkpoints ----------------------------------------------------------------------------
def test_a_discovery_state_is_never_a_valid_checkpoint(tmp_path):
    out = disc(tmp_path).check(snap(map=1), snap(map=250), 9, FakeEmulator({1: 2}), ctx_for())[0]
    state = Path(out["state"])
    assert dc.is_discovery_state(state)
    assert valid("to_route1", state, ("potion", "to_route1"), lambda g: True) is False
    plain = tmp_path / "runs" / "checkpoints" / "potion.state"
    plain.parent.mkdir(parents=True); plain.write_text("{}")
    assert not dc.is_discovery_state(plain)
    assert valid("potion", plain, ("potion", "to_route1"), lambda g: True) is True      # guard does not touch real checkpoints


def test_no_checkpoint_or_segment_code_reads_the_discoveries_directory():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in list((root / "src").rglob("*.py")) + list((root / "tools").rglob("*.py")):
        if "novelty" in path.parts or path.name in ("novelty.py", "checkpoint_goals.py"):
            continue
        if re.search(r"discoveries[\"'/\\]", path.read_text(encoding="utf-8", errors="ignore")):  # the directory, not discoveries.jsonl
            offenders.append(path.name)
    assert not offenders, offenders  # only the novelty package and its tool know the directory; checkpoint globs stay on runs/checkpoints


# --- supervisor hook ---------------------------------------------------------------------------------------------------
sc = _tool("swarm_continuous")


def make_sup(tmp_path):
    logs = []
    sup = sc.Supervisor.__new__(sc.Supervisor)
    sup.shared, sup.log = tmp_path / "maps.json", logs.append
    return sup, logs


def test_supervisor_merges_a_novelty_delta_once(tmp_path):
    sup, logs = make_sup(tmp_path)
    own = tmp_path / "agent1-1.json"
    write_delta(delta_path_for(own), "r1", "explorer", {"m:7": 1.0}, {})
    sup._merge_novelty(own)
    sup._merge_novelty(own)                                           # delta consumed: the second call is a no-op
    assert load_table(tmp_path / "novelty.json")["counts"] == {"m:7": 1} and not logs


def test_supervisor_hook_swallows_errors(tmp_path, monkeypatch):
    sup, logs = make_sup(tmp_path)
    own = tmp_path / "agent1-1.json"
    write_delta(delta_path_for(own), "r1", "explorer", {"m:7": 1.0}, {})
    import pokeagent.novelty.store as store
    monkeypatch.setattr(store, "merge_delta", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    sup._merge_novelty(own)                                           # must not raise
    assert "not merged" in logs[0] and delta_path_for(own).exists()   # the delta stays for a later merge
    sup._merge_novelty(tmp_path / "none.json")                        # no delta at all: silent no-op


def test_finish_calls_the_novelty_hook_right_after_the_bandit_hook():
    src = (TOOLS / "swarm_continuous.py").read_text(encoding="utf-8")
    assert src.index("self._merge_bandit(cfg[\"own\"])") < src.index("self._merge_novelty(cfg[\"own\"])") < src.index("self._refresh_grind()")


# --- backfill and the tool -----------------------------------------------------------------------------------------------
def make_runs(root):
    runs = root / "runs"
    for name, rows in {"explore-20261101-100000-1": [([1, 1, 1], [1, 1, 2]), ([1, 1, 2], [2, 3, 3])],
                       "explore-20261101-110000-2": [([1, 1, 1], [1, 1, 2])]}.items():
        d = runs / name
        d.mkdir(parents=True)
        (d / "transitions.jsonl").write_text("".join(json.dumps({"step": i, "from": a, "to": b}) + "\n" for i, (a, b) in enumerate(rows)))
    (runs / "milestones.json").write_text(json.dumps({"to_viridian": [{"run": "explore-20261101-100000-1", "step": 9}],
                                                     "potion": [{"run": "explore-20261101-110000-2", "step": 3}]}))
    (runs / "battles.jsonl").write_text(json.dumps({"run": "explore-20261101-100000-1", "enemy_species": 24, "party_before": [[177, 5, 1, 1, 1]],
                                                    "party_after": [[177, 5, 1, 1, 1]], "moves_learned": [{"slot": 0, "species": 177, "moves": [45]}]}) + "\n")
    return runs


def test_backfill_counts_runs_per_feature(tmp_path):
    t = bf.build_table(make_runs(tmp_path))
    c = t["counts"]
    assert c["t:1:1:1"] == 2 and c["t:1:1:2"] == 2 and c["t:2:3:3"] == 1 and c["w:1>2"] == 1
    assert c["m:1"] == 2 and c["m:2"] == 1 and c["m:1"] == 2     # map goal detector: to_viridian -> map 1
    assert c["i:20"] == 1 and c["ss:24"] == 1 and c["so:177"] == 1 and c["mv:45"] == 1
    assert t["first"]["t:1:1:1"][0] < t["first"]["t:2:3:3"][0] + 1 and set(t["merged"]) == {"explore-20261101-100000-1", "explore-20261101-110000-2"}


def test_tool_backfill_writes_once_then_prints_a_diff_and_top_discoveries_read(tmp_path, capsys):
    nv = _tool("novelty")
    runs = make_runs(tmp_path)
    assert nv.main(["--runs", str(runs), "backfill"]) == 0
    assert (runs / "novelty.json").exists() and "wrote" in capsys.readouterr().out
    before = (runs / "novelty.json").read_text()
    (runs / "explore-20261101-120000-3").mkdir()
    (runs / "explore-20261101-120000-3" / "transitions.jsonl").write_text(json.dumps({"from": [9, 1, 1], "to": [9, 1, 2]}) + "\n")
    nv.main(["--runs", str(runs), "backfill"])
    out = capsys.readouterr().out
    assert "not writing" in out and '"added"' in out and (runs / "novelty.json").read_text() == before   # never overwritten
    assert nv.main(["--runs", str(runs), "top", "-n", "5"]) == 0
    top = capsys.readouterr().out
    assert "rarest 5" in top and "first finds by role" in top and "backfill" in top
    assert nv.main(["--runs", str(runs), "discoveries"]) == 0 and "no discoveries" in capsys.readouterr().out
    disc(runs).check(snap(map=1), snap(map=250), 4, FakeEmulator({1: 2}), ctx_for())
    assert nv.main(["--runs", str(runs), "discoveries", "--since", "99999999"]) == 0
    assert "glitch_map" in capsys.readouterr().out
