"""SYNTHETIC replay of the 2026-11-07 catch stall (run explore-20261107-191457-26240: 1,365 alternations of
catch/item_open A and battle/item_list_close B inside battles). Battle runs BEFORE Catch in the registry, so its
"stray item list" close fired on the list Catch had just opened. Fixture ctx + monkeypatched ROM data only; the
real Selector over [Battle, Catch] is what answers."""
from __future__ import annotations

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import catch as catch_mod
from pokeagent.explorer.behaviours.battle import Battle
from pokeagent.explorer.behaviours.catch import CATCH_BAG_PRESSES, Catch
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.selector import Selector
from pokeagent.knowledge.catch_policy import CatchStep

MAP, PX, PY = 0xD35E, 0xD362, 0xD361
FAKE_KB = {"dex_of_internal": {"36": 16}, "name_of_internal": {"36": "PIDGEY"}, "items": {}}
BATTLE_MENU = [">ITEM RUN", "FIGHT PKMN"]
ITEM_LIST = ["POKe BALL", "x 5", ">POTION", "x 2"]       # the bag list: 'x N' quantity rows


def _ctx(tmp_path, monkeypatch):
    emu = FakeEmulator({MAP: 0x28, PX: 5, PY: 6, 0xD057: 1, 0xCFE5: 36, 0xCFE7: 7, 0xCFF5: 20, 0xCFF3: 5,
                        0xD31D: 1, 0xD31E: 0x04, 0xD31F: 5})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(),
                          run_dir=tmp_path, stable_frames=10)
    ctx.refresh()
    ctx.view.battling = True
    ctx.refresh = lambda: None                      # the fixture owns the screen: lines are set by the test
    monkeypatch.setattr(catch_mod, "ROM_KB", FAKE_KB)
    monkeypatch.setattr(catch_mod, "catch_wanted", lambda *a, **k: "wanted")
    monkeypatch.setattr(catch_mod, "cave_catch_allowed", lambda c, s: True)
    monkeypatch.setattr(catch_mod, "dex_owned_count", lambda e: 3)
    monkeypatch.setattr(catch_mod, "upcoming_needs", lambda g: [])
    monkeypatch.setattr(catch_mod, "our_party", lambda e: [])
    monkeypatch.setattr(catch_mod, "_policy_hint", lambda *a, **k: CatchStep("throw", ball="POKE", p=0.4))
    return ctx


def _choose(sel, ctx, lines):
    ctx.view.lines = lines
    ctx.step += 1
    return sel.choose(ctx)


def test_battle_does_not_close_the_list_catch_just_opened(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    sel = Selector([Battle(), Catch()])
    d1 = _choose(sel, ctx, BATTLE_MENU)
    assert d1 is not None and d1.behaviour == "catch" and d1.rule == "item_open" and d1.button == "A"
    d2 = _choose(sel, ctx, ITEM_LIST)                      # the bag is open now: Catch's sequence, not a stray list
    assert d2 is None or d2.rule != "item_list_close", d2  # main: battle/item_list_close B (the tug of war)
    assert d2 is not None and d2.behaviour == "catch"


def test_a_stray_list_with_no_catch_in_progress_is_still_closed(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(catch_mod, "_policy_hint", lambda *a, **k: CatchStep("skip", why="x"))
    sel = Selector([Battle(), Catch()])
    d = _choose(sel, ctx, ITEM_LIST)
    assert d is not None and d.rule == "item_list_close"


def test_the_bag_sequence_is_abandoned_with_a_cap_and_a_log(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    sel = Selector([Battle(), Catch()])
    logs = []
    ctx.log = lambda t, tag=None: logs.append(t)
    # a bag screen on which the ball never lands (e.g. the list never scrolls): presses pile up
    monkeypatch.setattr(catch_mod, "item_step", lambda *a, **k: __import__("pokeagent.explorer.behaviours.base", fromlist=["Decision"]).Decision("DOWN", "item_list_scroll", "x"))
    _choose(sel, ctx, BATTLE_MENU)                         # Catch starts the sequence (its first press)
    seen = [_choose(sel, ctx, ITEM_LIST) for _ in range(CATCH_BAG_PRESSES + 2)]
    assert any(d is not None and d.rule == "catch_bag_failed" for d in seen)
    assert any("bag sequence gave up" in t for t in logs)
    assert ctx.catch_mode is False and ctx.catch_hint is None
    after = _choose(sel, ctx, ITEM_LIST)                   # abandoned: Battle may close the list again, catch stays out
    assert after is not None and after.rule == "item_list_close"


def test_the_attempt_record_is_stable_across_presses(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    sel = Selector([Battle(), Catch()])
    _choose(sel, ctx, BATTLE_MENU)
    first = ctx.catch_attempt
    s0 = first["step"]
    _choose(sel, ctx, ITEM_LIST)
    assert ctx.catch_attempt is first and first["step"] == s0     # the turn signature does not change per press
