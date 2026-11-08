"""The catch behaviour seam: may_throw_ctx on ctx-like objects, the battle_moves branch that follows the
policy's hinted move, catch.py in trainer / no-ROM-data battles, the switch press cap, the skip log.
Headless: FakeEmulator and monkeypatched ROM data only."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import battle_moves as bm
from pokeagent.explorer.behaviours import catch as catch_mod
from pokeagent.explorer.behaviours.battle import BattleView
from pokeagent.explorer.behaviours.catch import Catch
from pokeagent.explorer.behaviours.switch_out import MAX_PRESSES
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.knowledge.catch_policy import CatchStep, may_throw_ctx

MAP, PX, PY = 0xD35E, 0xD362, 0xD361
FAKE_KB = {"dex_of_internal": {"36": 16}, "name_of_internal": {"36": "PIDGEY"}, "items": {}}


def _ctx(tmp_path, kind=1, e_hp=3, e_max=20, lines=None):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6, 0xD057: kind, 0xCFE7: e_hp, 0xCFF5: e_max})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, stable_frames=10)
    ctx.refresh()
    ctx.view.battling = True
    if lines is not None:
        ctx.view.lines = lines
    ctx.bv = BattleView(kind=kind, hp=3, mx=20, run_line="RUN", species=36, e_lvl=5)
    return ctx


def _wire(monkeypatch, hint):
    """Catch sees a wanted, unowned PIDGEY with 5 Poke Balls; the policy returns ``hint`` (a CatchStep, or
    None = no ROM data to decide with). Returns the list of times the policy was consulted."""
    calls = []
    monkeypatch.setattr(catch_mod, "ROM_KB", FAKE_KB)
    monkeypatch.setattr(catch_mod, "catch_wanted", lambda *a, **k: "wanted")
    monkeypatch.setattr(catch_mod, "cave_catch_allowed", lambda ctx, sp: True)
    monkeypatch.setattr(catch_mod, "bag_contents", lambda emu: {0x04: 5})
    monkeypatch.setattr(catch_mod, "our_party", lambda emu: [])
    monkeypatch.setattr(catch_mod, "dex_owned_count", lambda emu: 3)
    monkeypatch.setattr(catch_mod, "upcoming_needs", lambda goals: [])
    monkeypatch.setattr(catch_mod, "_policy_hint", lambda *a, **k: calls.append(1) or hint)
    return calls


# --- may_throw_ctx on a ctx-like object ---
def test_may_throw_ctx_trainer_wild_unknown():
    def like(kind, npc=None, log=None):
        return SimpleNamespace(bv=SimpleNamespace(kind=kind), trainer_npc=npc, battle_log=log)
    assert may_throw_ctx(like(1)) is True
    assert may_throw_ctx(like(2)) is False
    assert may_throw_ctx(like(1, npc={"pic": 3})) is False
    assert may_throw_ctx(like(1, log={"kind": 2})) is False
    assert may_throw_ctx(like(None)) is False
    assert may_throw_ctx(SimpleNamespace(bv=None, trainer_npc=None, battle_log=None)) is False
    assert may_throw_ctx(SimpleNamespace()) is False                      # no fields at all: unknown -> False


# --- battle_moves follows the policy's named move, else the old weakest-hit heuristic ---
def _move_menu_ctx(tmp_path, monkeypatch, hint):
    ctx = _ctx(tmp_path, lines=["TYPE/", "NORMAL", "29/30", "TACKLE", ">WATER GUN"])
    monkeypatch.setattr(bm, "move_scores", lambda emu, catching=False: {"TACKLE": (10, ""), "WATER GUN": (30, "")})
    ctx.catch_mode, ctx.catch_hint = True, hint
    return ctx


def test_battle_moves_chooses_the_hinted_move(tmp_path, monkeypatch):
    hint = CatchStep("damage_move", move="WATER GUN", why="weakening: WATER GUN")
    ctx = _move_menu_ctx(tmp_path, monkeypatch, hint)
    dec = bm.BattleMoves().step(ctx)
    assert dec is not None and dec.button == "A" and "catch policy" in ctx.move_reason   # cursor already on it
    ctx = _move_menu_ctx(tmp_path, monkeypatch, CatchStep("skip", why="x"))
    dec = bm.BattleMoves().step(ctx)                                      # no named move: weakest hit = TACKLE
    assert dec.button in ("DOWN", "UP") and ctx.move_reason == "weakest hit, catching"


# --- catch.py ---
def test_catch_trainer_battle_leaves_hint_and_mode_off(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, CatchStep("throw", ball="POKE"))
    ctx = _ctx(tmp_path, kind=2)
    ctx.catch_mode, ctx.catch_hint = True, CatchStep("throw", ball="POKE")   # stale from an earlier fight
    assert Catch().step(ctx) is None
    assert ctx.catch_hint is None and ctx.catch_mode is False and ctx.catch_attempt is None and calls == []
    ctx = _ctx(tmp_path, kind=1)
    ctx.trainer_npc = {"pic": 1}
    assert Catch().step(ctx) is None and ctx.catch_hint is None and ctx.catch_mode is False and calls == []


def test_catch_falls_back_to_the_35_percent_rule_without_rom_data(tmp_path, monkeypatch):
    _wire(monkeypatch, None)
    ctx = _ctx(tmp_path, e_hp=7, e_max=20, lines=[">FIGHT PKMN", "ITEM RUN"])      # 35% exactly
    dec = Catch().step(ctx)
    assert dec is not None and dec.rule == "item_menu_down"                # walking the menu toward ITEM
    assert ctx.catch_hint is None and ctx.catch_mode is True and ctx.catch_attempt["species"] == 36
    ctx = _ctx(tmp_path, e_hp=12, e_max=20, lines=[">FIGHT PKMN", "ITEM RUN"])     # 60%: not weak enough yet
    assert Catch().step(ctx) is None and ctx.catch_attempt is None and ctx.catch_mode is True


def test_policy_hint_is_none_without_party_data(tmp_path, monkeypatch):
    monkeypatch.setattr(catch_mod, "our_party", lambda emu: [])
    ctx = _ctx(tmp_path)
    assert catch_mod._policy_hint(ctx, "PIDGEY", 5, 3, 20, {4: 5}, 1) is None


def test_catch_switch_gives_up_after_the_press_cap(tmp_path, monkeypatch):
    calls = _wire(monkeypatch, CatchStep("switch", slot=1, why="overpowered"))
    monkeypatch.setattr(catch_mod, "switch_press", lambda *a: "DOWN")
    ctx = _ctx(tmp_path, e_hp=20, e_max=20)
    for _ in range(MAX_PRESSES):
        dec = Catch().step(ctx)
        assert dec.rule == "catch_switch" and ctx.catch_hint is not None
    dec = Catch().step(ctx)                                               # one press too many: back out and stop
    assert dec.rule == "catch_switch_failed" and dec.button == "B"
    assert ctx.catch_hint is None and ctx.catch_mode is False
    seen = len(calls)
    assert Catch().step(ctx) is None and len(calls) == seen              # no new hint for the rest of this battle
    assert ctx.catch_hint is None and ctx.catch_mode is False
    ctx.battles += 1                                                     # a new battle starts the counter over
    assert Catch().step(ctx).rule == "catch_switch"


def test_catch_logs_the_skip_reason_once_per_battle(tmp_path, monkeypatch):
    _wire(monkeypatch, CatchStep("skip", why="overpowered, no catcher, P(catch) too low"))
    ctx = _ctx(tmp_path, e_hp=20, e_max=20)
    logs = []
    ctx.log = lambda text, tag=None: logs.append(text)
    for _ in range(3):
        Catch().step(ctx)
    assert sum("P(catch) too low" in t for t in logs) == 1
    assert ctx.catch_mode is False


def test_party_full_skip_resets_a_stale_catch_mode(tmp_path, monkeypatch):
    from pokeagent.knowledge import team_plan
    _wire(monkeypatch, CatchStep("throw", ball="POKE"))
    monkeypatch.setattr(catch_mod, "read_party", lambda emu: [object()] * 6)      # a full party
    monkeypatch.setattr(catch_mod, "full_party_slot", lambda ctx, party: None)   # every member protected
    ctx = _ctx(tmp_path)
    ctx.catch_mode, ctx.catch_hint = True, CatchStep("throw", ball="POKE")        # stale from an earlier battle
    assert Catch().step(ctx) is None
    assert ctx.catch_mode is False and ctx.catch_hint is None                     # no weaken-only mode survives
    assert team_plan.of(ctx).get("release_pending") is None                       # ... and no mark was made


def test_party_full_mark_records_the_battle_and_is_computed_once(tmp_path, monkeypatch):
    from pokeagent.knowledge import team_plan
    _wire(monkeypatch, CatchStep("throw", ball="POKE"))
    monkeypatch.setattr(catch_mod, "read_party", lambda emu: [object()] * 6)
    calls = []
    monkeypatch.setattr(catch_mod, "full_party_slot",
                        lambda ctx, party: calls.append(1) or 5)
    ctx = _ctx(tmp_path)
    Catch().step(ctx)
    st = team_plan.of(ctx)
    assert st["release_pending"] == {"species": "PIDGEY", "slot": 5, "battle": ctx.battles}
    Catch().step(ctx)
    assert calls == [1]                                        # settled once for the battle


def test_turn_signature_does_not_use_object_ids(tmp_path, monkeypatch):
    _wire(monkeypatch, CatchStep("skip", why="x"))
    ctx = _ctx(tmp_path, e_hp=20, e_max=20)
    ctx.pending_move = {"step": 4}
    Catch().step(ctx)
    ctx.pending_move = {"step": 4}                                        # a new dict (maybe the same id), same event
    Catch().step(ctx)
    assert ctx.catch_turns[2] == 1
    ctx.pending_move = {"step": 9}
    Catch().step(ctx)
    assert ctx.catch_turns[2] == 2
