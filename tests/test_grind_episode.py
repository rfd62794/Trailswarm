"""Grind episodes (synthetic fixtures, labelled): self-started drills, end conditions, the boundary guard."""
from __future__ import annotations

import json
from types import SimpleNamespace

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import grind_episode
from pokeagent.explorer.behaviours.frontier import Frontier
from pokeagent.explorer.behaviours.grind_drill import GrindDrill
from pokeagent.explorer.context import Frame
from pokeagent.explorer.grind import GRIND_BLACKOUTS, GRIND_STEPS
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.party_log import PartyLog
from pokeagent.explorer.perceive import TILEMAP_LEN
from pokeagent.grind import points as gp

MAP, PX, PY, LEVEL = 0xD35E, 0xD362, 0xD361, 0xD18C
HP_LO, HP_HI, MX_LO, MX_HI = 0xD16C, 0xD16D, 0xD18D, 0xD18E


def make_ctx(tmp_path, m=35, x=10, y=35, lvl=10, need=20, maps=None, hp=(20, 20)):
    emu = FakeEmulator({MAP: m, PX: x, PY: y, LEVEL: lvl,
                        HP_LO: hp[0] >> 8, HP_HI: hp[0] & 0xFF, MX_LO: hp[1] >> 8, MX_HI: hp[1] & 0xFF})
    mem = MapMemory(tmp_path / "maps.json")
    for k, v in (maps or {}).items():
        mem.data["maps"][k] = v
    ctx = SimpleNamespace(
        emu=emu, mem=mem, opts=SimpleNamespace(drill_grind=None, state_path=""),
        step=1, battles=0, train_need=need, train_member=None, in_battle=False,
        view=Frame(m, x, y, bytes(TILEMAP_LEN)), run_dir=tmp_path, logs=[],
        facing="UP", recent_tiles={}, last_dir=None, frontier_target=None, frontier_route=[],
        frontier_at=None, train_route_live=False, hunt_grass=False, party_log=None, blackouts_row=0)
    ctx.log = lambda t, tag=None: ctx.logs.append(t)
    ctx.goals = lambda: {}
    return ctx


def make_ledger(map_id=35, band=(5, 15), prior=100.0):
    return gp.GrindLedger({map_id: gp.GrindPoint(map_id, "ROUTE_24", level_band=band, xp_per_min_prior=prior)})


def use_ledger(ctx, led):
    ctx._grind_state = {"heading": "RIGHT", "ledger": led}
    return ctx


PATCH_MAPS = {"35": {"visited": {"10,35": 1, "9,35": 1}, "blocked": [], "warps": {}, "encounters": {"9,35": 3}}}
EDGE_MAPS = {"35": {"visited": {"10,35": 1, "9,35": 1, "11,35": 1, "10,36": 1},
                    "blocked": ["10,35,DOWN", "10,35,LEFT", "10,35,RIGHT"],
                    "warps": {"10,35,UP": [3, 10, 35]}, "encounters": {}},
             "3": {"visited": {"10,35": 1}, "blocked": [], "warps": {}, "encounters": {}}}


def test_episode_starts_when_under_level_and_walks_the_patch(tmp_path):
    """Synthetic: the gate says L10 < L20, the ledger has a band-covering point, an episode starts and
    GrindDrill walks to the encounter-proven patch tile."""
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), make_ledger())
    drill = GrindDrill(grids=lambda _m: None)
    assert drill.applies(ctx)
    ep = grind_episode.active(ctx)
    assert ep["point"].map_id == 35 and ep["maps"] == {35} and ep["point"].patch == [[9, 35]]
    d = drill.step(ctx)
    assert d is not None and d.button == "LEFT"        # toward the patch tile (9,35)
    ctx2 = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, need=8), make_ledger())   # level above need
    assert not drill.applies(ctx2) and grind_episode.active(ctx2) is None


def _start(ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp.json")
    assert GrindDrill(grids=lambda _m: None).applies(ctx)
    return grind_episode.active(ctx)


def test_episode_ends_on_need_and_writes_the_drill_row(tmp_path, monkeypatch):
    led = make_ledger()
    led.path = tmp_path / "gp.json"                         # the ledger file lands in the run's own dir
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), led)
    ep = _start(ctx, monkeypatch, tmp_path)
    ctx.emu.set(LEVEL, 20)                            # the trainee reached the need
    assert not GrindDrill(grids=lambda _m: None).applies(ctx)
    assert grind_episode.active(ctx) is None
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[0])
    assert row["kind"] == "grind_episode" and row["map"] == 35 and row["reason"].startswith("trainee reached")
    assert {"run", "start_step", "end_step", "xp_gained", "steps", "blackouts", "xp_per_min", "provenance"} <= set(row)
    doc = json.loads((tmp_path / "gp.json").read_text())
    assert doc["points"]["35"]["n_measured"] == 1     # folded into the run-local ledger file
    assert ctx.mem.data["grind_points"]["35"]["n_measured"] == 1   # ... and the shared table the swarm merges


def test_episode_ends_on_blackouts_and_the_step_budget(tmp_path, monkeypatch):
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), make_ledger())
    _start(ctx, monkeypatch, tmp_path)
    ctx.party_log.blackouts = GRIND_BLACKOUTS
    assert not GrindDrill(grids=lambda _m: None).applies(ctx) and grind_episode.active(ctx) is None
    ctx2 = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), make_ledger())
    _start(ctx2, monkeypatch, tmp_path)
    ctx2.step += GRIND_STEPS
    assert not GrindDrill(grids=lambda _m: None).applies(ctx2)
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])
    assert row["reason"].endswith("steps")


def test_episode_ends_hurt_with_no_potion(tmp_path, monkeypatch):
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), make_ledger())
    _start(ctx, monkeypatch, tmp_path)
    ctx.emu.set(HP_LO, 0)
    ctx.emu.set(HP_HI, 4)                              # 4/20 < 0.5 and no heal items in the bag
    assert not GrindDrill(grids=lambda _m: None).applies(ctx)
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])
    assert row["reason"] == "hurt with no potion"


def test_episode_boundary_keeps_frontier_on_map_35(tmp_path):
    """Synthetic Nugget Bridge fixture: map 35's only way on is the learned edge warp to map 3; with an
    active episode on 35 the chosen press never leaves the map; without one it may."""
    ctx = make_ctx(tmp_path, m=35, x=10, y=35, maps=EDGE_MAPS)
    ctx._grind_state = {"episode": {"maps": {35, 64}, "point": gp.GrindPoint(35)}}
    assert Frontier().step(ctx).button == "A"          # UP warps to map 3: the episode forbids it
    ctx2 = make_ctx(tmp_path, m=35, x=10, y=35, maps=EDGE_MAPS)
    assert Frontier().step(ctx2).button == "UP"        # no episode: the same press crosses the edge


def test_frontier_plan_never_routes_through_a_forbidden_map(tmp_path):
    """The only route to the unexplored tile detours through map 3: allowed={35} makes it unplannable."""
    maps = {"35": {"visited": {"10,35": 1, "9,35": 1}, "blocked": ["10,35,DOWN", "10,35,LEFT", "10,35,RIGHT"],
                   "warps": {"10,35,UP": [3, 10, 35]}, "encounters": {}},
            "3": {"visited": {"10,35": 1, "9,35": 1}, "blocked": [], "warps": {"9,35,DOWN": [35, 9, 35]},
                  "encounters": {}}}
    ctx = make_ctx(tmp_path, m=35, x=10, y=35, maps=maps)
    plan = ctx.mem.frontier_plan(35, 10, 35)            # synthetic: without the guard it goes via map 3
    assert plan is not None and plan[0] == (35, 9, 35) and plan[1][0] == "UP"
    assert ctx.mem.frontier_plan(35, 10, 35, allowed={35, 64}) is None
