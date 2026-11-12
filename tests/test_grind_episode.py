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
    emu = FakeEmulator({MAP: m, PX: x, PY: y, LEVEL: lvl, 0xD163: 1, 0xD164: 0x99, 0xD16B: 0x99,
                        HP_LO: hp[0] >> 8, HP_HI: hp[0] & 0xFF, MX_LO: hp[1] >> 8, MX_HI: hp[1] & 0xFF})
    mem = MapMemory(tmp_path / "maps.json")
    for k, v in (maps or {}).items():
        mem.data["maps"][k] = v
    ctx = SimpleNamespace(
        emu=emu, mem=mem, opts=SimpleNamespace(drill_grind=None, state_path=""),
        step=1, battles=0, train_need=need, train_member=None, in_battle=False,
        view=Frame(m, x, y, bytes(TILEMAP_LEN)), run_dir=tmp_path, logs=[],
        facing="UP", recent_tiles={}, last_dir=None, frontier_target=None, frontier_route=[],
        frontier_at=None, train_route_live=False, hunt_grass=False, party_log=None, blackouts_row=0,
        center_intent=None, goto=None, proc=None)
    ctx.log = lambda t, tag=None: ctx.logs.append(t)
    ctx.goals = lambda: {}
    ctx.pos = lambda: (ctx.view.m, ctx.view.x, ctx.view.y)
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
    assert grind_episode.update(ctx) is not None     # the tick starts the episode
    assert drill.applies(ctx)                        # applies() only reads the result
    ep = grind_episode.active(ctx)
    assert ep["point"].map_id == 35 and ep["maps"] == {35} and ep["point"].patch == [[9, 35]]
    d = drill.step(ctx)
    assert d is not None and d.button == "LEFT"        # toward the patch tile (9,35)
    ctx2 = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, need=8), make_ledger())   # level above need
    assert grind_episode.update(ctx2) is None and not drill.applies(ctx2)


def _start(ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp.json")
    assert grind_episode.update(ctx) is not None     # the engine tick's start path
    return grind_episode.active(ctx)


def test_episode_ends_on_need_and_writes_the_drill_row(tmp_path, monkeypatch):
    led = make_ledger()
    led.path = tmp_path / "gp.json"                         # the ledger file lands in the run's own dir
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), led)
    ep = _start(ctx, monkeypatch, tmp_path)
    ctx.step += 60                                  # run long enough to be a measurement (2 battles)
    ctx.battles += 2
    ctx.emu.set(LEVEL, 20)                            # the trainee reached the need
    assert grind_episode.update(ctx) is None        # the tick ends and folds it
    assert not GrindDrill(grids=lambda _m: None).applies(ctx)
    assert grind_episode.active(ctx) is None
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[0])
    assert row["status"] == "measured"
    assert row["kind"] == "grind_episode" and row["map"] == 35 and row["reason"].startswith("trainee reached")
    assert {"run", "start_step", "end_step", "xp_gained", "steps", "blackouts", "xp_per_min", "provenance"} <= set(row)
    doc = json.loads((tmp_path / "gp.json").read_text())
    assert doc["points"]["35"]["n_measured"] == 1     # folded into the run-local ledger file
    assert ctx.mem.data["grind_points"]["35"]["n_measured"] == 1   # ... and the shared table the swarm merges


def test_episode_ends_on_blackouts_and_the_step_budget(tmp_path, monkeypatch):
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), make_ledger())
    _start(ctx, monkeypatch, tmp_path)
    ctx.party_log.blackouts = GRIND_BLACKOUTS
    assert grind_episode.update(ctx) is None and grind_episode.active(ctx) is None
    ctx2 = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), make_ledger())
    _start(ctx2, monkeypatch, tmp_path)
    ctx2.step += GRIND_STEPS
    assert grind_episode.update(ctx2) is None
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])
    assert row["reason"].endswith("steps") and row["status"] == "aborted"


def test_episode_ends_hurt_with_no_potion(tmp_path, monkeypatch):
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), make_ledger())
    _start(ctx, monkeypatch, tmp_path)
    ctx.emu.set(HP_LO, 0)
    ctx.emu.set(HP_HI, 2)                              # 2/20 = 10% < the survival margin and no heal items in the bag
    assert grind_episode.update(ctx) is None
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])
    assert row["reason"] == "hurt with no potion" and row["status"] == "aborted"


def test_episode_ends_hurt_with_slot_zero_fainted_and_no_potion(tmp_path, monkeypatch):
    """A fainted member behind a healthy fighter still ends the episode: the whole party feeds the check."""
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), make_ledger())
    ctx.emu.set(0xD163, 2)                                   # slot 1 joins: a healthy second member
    for a, v in {0xD165: 0x9A, 0xD16B + 44: 0x9A, 0xD16D + 44: 32, 0xD18E + 44: 32}.items():
        ctx.emu.set(a, v)
    _start(ctx, monkeypatch, tmp_path)
    ctx.emu.set(0xD16D, 0)                                   # the lead faints mid-episode
    assert grind_episode.update(ctx) is None
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])
    assert row["reason"] == "hurt with no potion" and row["status"] == "aborted"


def test_grind_drill_episode_step_gets_heal_gate_hp_when_slot_zero_fainted(tmp_path, monkeypatch):
    """heal_gate_hp feeds train_route.step: the fighter's numbers, or (0, fighter max) while a member is fainted."""
    from pokeagent.explorer import train_route
    ctx = make_ctx(tmp_path, m=13, hp=(20, 35))                       # off the episode's point map
    ctx.emu.set(0xD163, 2)
    for a, v in {0xD165: 0x9A, 0xD16B + 44: 0x9A, 0xD16D + 44: 32, 0xD18E + 44: 32}.items():
        ctx.emu.set(a, v)
    seen = []
    monkeypatch.setattr(train_route, "step", lambda *a, **k: seen.append(a[3]) or None)
    ep = {"maps": {35}, "point": gp.GrindPoint(35)}
    GrindDrill(grids=lambda _m: None)._episode_step(ctx, ep)
    assert seen[-1] == 20                                             # healthy: the fighter's HP
    ctx.emu.set(0xD16D, 0)                                            # the lead faints
    GrindDrill(grids=lambda _m: None)._episode_step(ctx, ep)
    assert seen[-1] == 0                                              # (0, fighter max): the heal gate fires


def test_hurt_restart_loop_yields_one_aborted_row_and_no_ledger_change(tmp_path, monkeypatch):
    """The PR #165 blocker: hurt-no-potion must not cycle start/end every other step into the ledger.
    The aborted end writes one row, never folds, and the cooldown blocks the immediate restart."""
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), led)
    _start(ctx, monkeypatch, tmp_path)
    ctx.emu.set(HP_LO, 0)
    ctx.emu.set(HP_HI, 2)
    assert grind_episode.update(ctx) is None                       # aborted end
    rows = (tmp_path / "rows.jsonl").read_text().splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["status"] == "aborted"
    assert led.points[35].n_measured == 0                          # never folded into the mean
    ctx.emu.set(HP_LO, 0)
    ctx.emu.set(HP_HI, 20)                                         # healed again
    ctx.step += 10
    assert grind_episode.update(ctx) is None                       # EPISODE_COOLDOWN blocks the restart
    assert not (tmp_path / "gp.json").exists()                     # and the ledger file was never written
    ctx.step += grind_episode.EPISODE_COOLDOWN
    assert grind_episode.update(ctx) is not None                   # after the cooldown a start is allowed
    assert len((tmp_path / "rows.jsonl").read_text().splitlines()) == 1


def test_never_starts_into_a_state_that_would_end(tmp_path, monkeypatch):
    """Start-gate: every _end_reason check runs at start too - hurt-with-no-potion can never begin."""
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(2, 20)), led)
    _start_blocked_ctx(ctx, monkeypatch, tmp_path)
    assert grind_episode.update(ctx) is None and grind_episode.active(ctx) is None
    assert not (tmp_path / "rows.jsonl").exists()                  # no episode, no row
    assert any("not starting" in line for line in ctx.logs)


def _start_blocked_ctx(ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp.json")
    return ctx


def test_start_gates_center_intent_goto_and_proc(tmp_path, monkeypatch):
    """A buy/heal inside a Pokecenter (center_intent), an in-flight goto, or a running procedure
    must not start an episode that routes the agent out."""
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), led)
    _start_blocked_ctx(ctx, monkeypatch, tmp_path)
    for attr, value in (("center_intent", "status_care"), ("goto", ["UP"]), ("proc", {"name": "x"})):
        setattr(ctx, attr, value)
        assert grind_episode.update(ctx) is None and grind_episode.active(ctx) is None
        setattr(ctx, attr, None)
    assert grind_episode.update(ctx) is not None                   # gates clear: it starts


def test_start_is_the_explicit_entry_point(tmp_path, monkeypatch):
    """PR #166 (Team Management) calls grind_episode.start(ctx) via getattr - same gates + cooldown."""
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), led)
    _start_blocked_ctx(ctx, monkeypatch, tmp_path)
    assert grind_episode.start(ctx, "team management") and grind_episode.active(ctx) is not None
    assert grind_episode.start(ctx, "team management")             # already running: still True
    ctx2 = use_ledger(make_ctx(tmp_path, need=8), make_ledger())
    assert not grind_episode.start(ctx2)                           # level not under the need
    assert any("not starting" in line for line in ctx2.logs)


def test_applies_is_a_pure_read_no_choose_no_writes(tmp_path, monkeypatch):
    """applies() performs no file writes and no BFS: it reads active() / the under-level flag only."""
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), make_ledger())
    calls = []
    monkeypatch.setattr(gp, "choose", lambda *a, **k: calls.append("choose"))
    monkeypatch.setattr(gp, "travel_steps", lambda *a, **k: calls.append("travel"))
    monkeypatch.setattr(gp.GrindLedger, "save", lambda *a, **k: calls.append("save"))
    monkeypatch.setattr(grind_episode, "log_episode", lambda *a, **k: calls.append("row"))
    drill = GrindDrill(grids=lambda _m: None)
    for _ in range(20):
        drill.applies(ctx)                                         # under-level, no episode yet
    ctx._grind_state["episode"] = {"maps": {35}, "point": gp.GrindPoint(35)}
    for _ in range(20):
        drill.applies(ctx)                                         # episode active
    assert calls == []


def test_finish_measures_xp_from_levels_jsonl(tmp_path, monkeypatch):
    """The measured xp comes from the levels.jsonl exp delta (replayable), not party_log.exp_total."""
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), led)
    _start_blocked_ctx(ctx, monkeypatch, tmp_path)
    (tmp_path / "levels.jsonl").write_text(
        json.dumps({"step": 1, "party": [[1, 10, 100, 20, 20]]}) + "\n"
        + json.dumps({"step": 80, "party": [[1, 10, 250, 20, 20]]}) + "\n", encoding="utf-8")
    assert grind_episode.update(ctx) is not None                   # start_step = ctx.step (1)
    ctx.step, ctx.battles = 80, 3
    ctx.train_need = 0                                             # the gate lifts: end it
    assert grind_episode.update(ctx) is None
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])
    assert row["xp_gained"] == 150 and row["status"] == "measured"  # 250-100: levels.jsonl won over exp_total=0


def test_leaves_set_counts_a_one_sighting_edge(tmp_path):
    """warp_cand (a map change seen once, not yet a confirmed warp) also counts as leaving the set."""
    maps = {"35": {"visited": {"10,35": 1}, "blocked": [], "warps": {},
                   "warp_cand": {"10,35,UP": 1}, "paths": {"10,36,LEFT": {"to": [3, 10, 36]}}}}
    ctx = make_ctx(tmp_path, m=35, x=10, y=35, maps=maps)
    allowed = frozenset({35, 64})
    assert grind_episode.leaves_set(ctx, "UP", allowed)            # one-sighting edge: leaving
    ctx.view.x, ctx.view.y = 10, 36
    assert grind_episode.leaves_set(ctx, "LEFT", allowed)          # recorded paths edge to map 3: leaving
    assert not grind_episode.leaves_set(ctx, "RIGHT", allowed)     # nothing recorded: stays


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


def test_patrol_fallback_never_leaves_the_episode_map_set(tmp_path):
    """Synthetic: map 35 fully explored (no frontier), its only way on is the learned warp UP to map 3. The
    patrol fallback (PR #164) must not take it while an episode holds {35, 64}; with no episode it may."""
    from pokeagent.explorer.behaviours.frontier import _memory_step
    maps = {"35": {"visited": {"10,35": 5}, "blocked": ["10,35,DOWN", "10,35,LEFT", "10,35,RIGHT"],
                   "warps": {"10,35,UP": [3, 10, 35]}, "encounters": {}},
            "3": {"visited": {"10,35": 1}, "blocked": [], "warps": {"10,35,DOWN": [35, 10, 35]}, "encounters": {}}}
    ctx = make_ctx(tmp_path, m=35, x=10, y=35, maps=maps)
    ctx.mem.recent_talk |= {"10,35,DOWN", "10,35,LEFT", "10,35,RIGHT"}
    free = _memory_step(ctx, 35, 10, 35)[0]
    bounded = _memory_step(ctx, 35, 10, 35, allowed=frozenset({35, 64}))[0]
    assert free == "UP"                                   # no episode: the warp is the way on
    assert bounded != "UP"                                # the episode boundary holds for the patrol too


def test_start_honours_the_no_point_cache(tmp_path, monkeypatch):
    """start() (called every step by PR #166) must not re-run the per-point search inside the cache window."""
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp.json")
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), make_ledger())
    calls = []
    monkeypatch.setattr(gp, "choose", lambda *a, **k: calls.append(1))
    assert not grind_episode.start(ctx) and len(calls) == 1
    for s in range(2, 50):
        ctx.step = s
        assert not grind_episode.start(ctx)
    assert len(calls) == 1
    ctx.step = 1 + grind_episode.NO_POINT_RECHECK
    grind_episode.start(ctx)
    assert len(calls) == 2


def test_membership_change_aborts_instead_of_a_false_measured_row(tmp_path, monkeypatch):
    """A deposit mid-episode (species list changes) is an 'aborted' row, never folded into the ledger mean."""
    led = make_ledger()
    led.path = tmp_path / "gp.json"
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS), led)
    _start_blocked_ctx(ctx, monkeypatch, tmp_path)
    (tmp_path / "levels.jsonl").write_text(
        json.dumps({"step": 1, "party": [[1, 10, 100, 20, 20], [2, 30, 5000, 50, 50]]}) + "\n"
        + json.dumps({"step": 80, "party": [[1, 10, 250, 20, 20]]}) + "\n", encoding="utf-8")
    assert grind_episode.update(ctx) is not None
    ctx.step, ctx.battles = 80, 3
    ctx.train_need = 0
    grind_episode.update(ctx)
    row = json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])
    assert row["status"] == "aborted" and "membership" in row["reason"]
    assert led.points[35].xp_per_min_measured in (None, 0) or not led.points[35].xp_per_min_measured


def test_trainee_check_failure_fails_safe_and_warns(tmp_path, monkeypatch, caplog):
    import pokeagent.explorer.trainee_gate as tg
    monkeypatch.setattr(tg, "trainee_check", lambda c: (_ for _ in ()).throw(RuntimeError("boom")))
    grind_episode._warned.discard("trainee")
    ctx = make_ctx(tmp_path)
    with caplog.at_level("WARNING"):
        assert grind_episode._trainee_ok(ctx) is False
    assert any(r.levelname == "WARNING" and "trainee check failed" in r.getMessage() for r in caplog.records)


def test_warn_once_logs_at_warning(caplog):
    from pokeagent.grind import measure
    grind_episode._warned.discard("t-w"); measure._warned.discard("t-w")
    with caplog.at_level("INFO"):
        grind_episode._warn_once("t-w", "x %s", 1)
        measure._warn_once("t-w", "y %s", 2)
    assert [r.levelname for r in caplog.records if r.getMessage() in ("x 1", "y 2")] == ["WARNING", "WARNING"]


# --- story blocker (the drunk old man north of Viridian, 2026-11-11): synthetic fixtures ---
VIRIDIAN = {"1": {"visited": {"19,11": 1, "19,10": 1, "19,9": 1}, "blocked": [], "encounters": {},
                  "warps": {"19,9,UP": [13, 5, 35]},
                  "interactions": {"19,10,UP": {"type": "blocker", "goal": "oaks_parcel", "count": 9}}},
            "13": {"visited": {"5,35": 1, "5,34": 1}, "blocked": [], "warps": {}, "encounters": {"5,34": 2}}}


def _viridian_ctx(tmp_path, maps=None, stage_done=()):
    from pokeagent.goals import GOALS
    ctx = make_ctx(tmp_path, m=1, x=19, y=11, lvl=5, need=8, maps=maps or VIRIDIAN)
    ctx.goals = lambda: {g: True for g in GOALS[:GOALS.index("oaks_parcel")]}   # the stage is oaks_parcel
    return use_ledger(ctx, make_ledger(13, band=(0, 100)))


def test_no_episode_toward_a_map_a_story_blocker_cuts_off(tmp_path, monkeypatch):
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    ctx = _viridian_ctx(tmp_path)
    assert grind_episode.update(ctx) is None
    assert any("no grind point fits" in t for t in ctx.logs)


def test_blocker_from_an_earlier_goal_no_longer_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    ctx = _viridian_ctx(tmp_path)
    ctx.mem.data["maps"]["1"]["interactions"]["19,10,UP"]["goal"] = "to_viridian"   # the goal moved on
    assert grind_episode.update(ctx) is not None


def test_live_episode_ends_when_a_blocker_is_recorded_on_the_way(tmp_path, monkeypatch):
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp.json")
    clean = {k: dict(v) for k, v in VIRIDIAN.items()}
    clean["1"] = {**VIRIDIAN["1"], "interactions": {}}
    ctx = _viridian_ctx(tmp_path, maps=clean)
    assert grind_episode.update(ctx) is not None                       # nothing known yet: it starts
    ctx.mem.data["maps"]["1"]["interactions"]["19,10,UP"] = {"type": "blocker", "goal": "oaks_parcel", "count": 1}
    assert grind_episode.update(ctx) is None                           # the first bump ends it
    assert grind_episode.active(ctx) is None
    assert "story blocker" in (tmp_path / "rows.jsonl").read_text()


def test_hurt_stop_reason_consults_party_survives(tmp_path, monkeypatch):
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), make_ledger())
    _start(ctx, monkeypatch, tmp_path)
    monkeypatch.setattr(grind_episode, "party_survives", lambda emu, m: False)
    assert grind_episode.update(ctx) is None                      # full HP, nobody survives, no potion
    assert json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])["reason"] == "hurt with no potion"
    ctx2 = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(1, 20)), make_ledger())
    monkeypatch.setattr(grind_episode, "party_survives", lambda emu, m: True)
    monkeypatch.setattr(grind_episode, "LOG", tmp_path / "rows2.jsonl")
    monkeypatch.setattr(grind_episode, "LEDGER", tmp_path / "gp2.json")
    assert grind_episode.update(ctx2) is not None                 # 5% HP but the party survives: it goes on


def test_a_fainted_member_is_never_a_survivor_and_still_ends_the_episode(tmp_path, monkeypatch):
    """party_survives is False with any member down, even next to a healthy one; with no potion the gate stops the episode
    (the slot-0-fainted test above runs the same path through the real emulator party)."""
    from dataclasses import replace

    from pokeagent.explorer import retreat_risk as rr
    from test_after_victory import _mon
    ctx = use_ledger(make_ctx(tmp_path, maps=PATCH_MAPS, hp=(20, 20)), make_ledger())
    _start(ctx, monkeypatch, tmp_path)
    monkeypatch.setattr(rr, "party_now", lambda emu: [replace(_mon("AQUAMON", 12), hp=0), _mon("AQUAMON", 12, 1.0)])
    assert rr.party_survives(ctx.emu, 35) is False
    assert grind_episode.update(ctx) is None
    assert json.loads((tmp_path / "rows.jsonl").read_text().splitlines()[-1])["reason"] == "hurt with no potion"
