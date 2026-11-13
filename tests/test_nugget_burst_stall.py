"""Nugget Bridge stall (2026-11-12): an item gain after a trainer fight set a 60-step explore_burst that looped
A -> retalk_veto B -> START menu. SYNTHETIC fixtures."""
from types import SimpleNamespace

from pokeagent.explorer.behaviours import frontier
from pokeagent.explorer.burst_gate import TRAINER_WIN_WINDOW, burst_allowed
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.procedures.state import of

NUGGET, MAP = 0x31, 0x23


def _ctx2(npc=None, step=1700):
    c = SimpleNamespace(step=step, facing="UP", mem=SimpleNamespace(npc_at=lambda m, x, y: npc))
    return c


def test_new_item_found_by_exploring_earns_a_burst():
    assert burst_allowed(_ctx2(), NUGGET, {}, "A", False, (MAP, 10, 15))


def test_more_of_a_held_item_is_not_new():
    assert not burst_allowed(_ctx2(), NUGGET, {NUGGET: 1}, "A", False, (MAP, 10, 15))


def test_no_burst_while_an_after_victory_push_is_pending():
    c = _ctx2(); of(c)["twins"] = 1
    assert not burst_allowed(c, NUGGET, {}, "A", True, (MAP, 10, 15))


def test_no_burst_right_after_a_trainer_win():
    c = _ctx2(); c.__dict__["trainer_win_step"] = 1646
    assert not burst_allowed(c, NUGGET, {}, "A", True, (MAP, 10, 15))
    c.step = 1646 + TRAINER_WIN_WINDOW + 1
    assert burst_allowed(c, NUGGET, {}, "A", False, (MAP, 10, 15))


def test_no_burst_when_a_person_handed_it_over():
    assert not burst_allowed(_ctx2(npc={"pic": 5}), NUGGET, {}, "A", True, (MAP, 10, 15))


def _boxed_in(tmp_path, entry):
    mem = MapMemory(tmp_path / "maps.json")
    d = mem.m(MAP)
    d["visited"]["10,15"] = 1
    d["blocked"] += [f"10,15,{n}" for n in ("UP", "DOWN", "LEFT", "RIGHT")]
    mem.recent_talk.add("10,15,UP")
    if entry is not None:
        d.setdefault("interactions", {})["10,15,UP"] = entry
    return mem


def test_boxed_in_facing_a_memorised_sign_presses_nothing(tmp_path):
    mem = _boxed_in(tmp_path, {"type": "sign", "pages": ["TRAINER TIPS"], "count": 2})
    assert mem.choose_local(MAP, 10, 15, "UP") is None
    assert mem.choose(MAP, 10, 15, "UP")[0] == "B"
    ctx = SimpleNamespace(mem=mem, facing="UP", view=SimpleNamespace(tm=None, m=MAP, x=10, y=15), emu=SimpleNamespace(read=lambda a: 0),
                          last_dir=None, recent_tiles={}, frontier_target=None, frontier_route=[], frontier_at=None,
                          last_press=None, novelty=None)
    assert frontier._memory_step(ctx, MAP, 10, 15) is None


def test_boxed_in_with_no_memorised_entry_still_presses_a(tmp_path):
    mem = _boxed_in(tmp_path, None)
    assert mem.choose_local(MAP, 10, 15, "UP")[0] == "A"
    mem = _boxed_in(tmp_path, {"type": "shop"})
    assert mem.choose_local(MAP, 10, 15, "UP")[0] == "A"
