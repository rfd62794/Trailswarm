"""Training v2 slice 3 (2026-11-13 A/B): pace INSIDE the grass, a Pokecenter visit is not a loop, heal on the survival floor,
Potion instead of a long walk, straight back to the grass after a heal. ROM-free."""
from __future__ import annotations

from types import SimpleNamespace

from pokeagent.explorer import after_heal, center_visit, grass_pace, grind_heal, train_route
from pokeagent.explorer.behaviours import retreat_heal
from pokeagent.explorer.behaviours.guards import LoopGuard
from test_battle_types import BATTLE, make_ctx

PX, MAPID = 0xD362, 0xD35E


# --- 1. pace inside the grass -------------------------------------------------------------------------------------------

PATCH = {f"{x},{y}" for x in (4, 5) for y in (16, 17)}   # Route 24's 2x2 patch where the shakes clustered


def test_on_grass_the_walker_stays_on_grass(monkeypatch):
    monkeypatch.setattr(grass_pace, "rom_grass", lambda m: None)
    maps = {"35": {"encounters": {t: 1 for t in PATCH}}}
    pos, heading, seen = (35, 4, 16), "RIGHT", set()
    for _ in range(40):
        r = train_route.step(maps, pos, set(), 30, 30, target=35, heading=heading)
        assert r is not None and "pacing inside the grass" in r[1]   # slice 2 answered None here: frontier took the edge
        heading = r[0]
        dx, dy = grass_pace.DIRS[r[0]]
        pos = (35, pos[1] + dx, pos[2] + dy)
        assert f"{pos[1]},{pos[2]}" in PATCH                         # every press lands on a grass tile
        seen.add(pos)
    assert len(seen) >= 2                                            # it keeps moving between grass tiles


def test_isolated_grass_tile_falls_back_to_frontier(monkeypatch):
    monkeypatch.setattr(grass_pace, "rom_grass", lambda m: None)
    assert train_route.step({"35": {"encounters": {"4,16": 1}}}, (35, 4, 16), set(), 30, 30, target=35) is None


def test_pacer_avoids_blocked_tiles_and_uses_rom_grid(monkeypatch):
    assert grass_pace.next_button({(4, 16), (5, 16), (4, 17)}, (4, 16), "RIGHT", {(5, 16)}) == "DOWN"
    monkeypatch.setattr(grass_pace, "rom_grass", lambda m: {(1, 1), (2, 1), (3, 1)})
    assert grass_pace.step(35, (2, 1), {}, None, "LEFT")[0] == "LEFT"   # ROM grid beats the sparse encounter list


# --- 2. Pokecenter visit ------------------------------------------------------------------------------------------------

def _visit(tmp_path, map_id, presses):
    ctx = make_ctx(tmp_path, memory={BATTLE: 0, MAPID: map_id})
    for i in range(presses):
        ctx.step = i
        ctx.emu.set(PX, 2 + i % 2)                                   # nurse dialog / door column: <=6 tiles, never a battle
        ctx.refresh()
        LoopGuard().step(ctx)
    return ctx


def test_pokecenter_visit_does_not_shake(tmp_path):
    assert _visit(tmp_path, 0x40, 100).shakes == 0                   # walk in + nurse dialog + walk out


def test_same_window_outside_a_center_still_shakes(tmp_path):
    assert _visit(tmp_path, 0x23, 100).shakes >= 1


def test_center_exemption_is_capped_and_resets_per_visit():
    c = SimpleNamespace(view=SimpleNamespace(m=0x40), step=0)
    c.__dict__.pop("center_presses", None)
    res = []
    for i in range(center_visit.MAX_VISIT_PRESSES + 1):
        c.step = i
        res.append(center_visit.exempt(c))
    assert res[-2] is True and res[-1] is False
    c.step += 100                                                     # a later visit
    assert center_visit.exempt(c) is True


# --- 3. heal on the survival floor, Potion for the walk, straight back ------------------------------------------------

def _ctx(grind=True):
    return SimpleNamespace(train_route_live=grind, view=SimpleNamespace(m=0x23), emu=object(), step=8, __dict__={})


def test_grinding_heal_follows_the_survival_floor(monkeypatch):
    monkeypatch.setattr(grind_heal, "read_party_view", lambda e: SimpleNamespace(any_fainted=False))
    monkeypatch.setattr(grind_heal, "party_needs_heal", lambda e, f: True)   # the old fixed fraction says "hurt"
    monkeypatch.setattr(grind_heal, "party_survives", lambda e, m: True)
    assert grind_heal.needs_heal(_ctx(), 0.4) is False               # grinding: survivable -> no heal, stay in the grass
    assert grind_heal.needs_heal(_ctx(grind=False), 0.4) is True     # not grinding: unchanged
    monkeypatch.setattr(grind_heal, "party_survives", lambda e, m: False)
    assert grind_heal.needs_heal(_ctx(), 0.4) is True


def test_retreat_heal_gate_uses_the_floor_while_grinding(monkeypatch):
    party = [SimpleNamespace(hp=15, max_hp=30, species=1, level=9)]  # 50%: under the old 0.8 / 0.7 pre-gates
    monkeypatch.setattr(retreat_heal, "fighter_slot", lambda e: 0)
    monkeypatch.setattr(grind_heal, "needs_heal", lambda ctx, f: False)
    assert retreat_heal.RetreatHeal._hurt(_ctx(), party) is False    # survivable: no walk
    monkeypatch.setattr(grind_heal, "needs_heal", lambda ctx, f: True)
    assert retreat_heal.RetreatHeal._hurt(_ctx(), party) is True


def test_potion_replaces_the_walk(monkeypatch):
    from pokeagent.explorer.behaviours import cave_topup
    monkeypatch.setattr(grind_heal, "read_party_view", lambda e: SimpleNamespace(any_fainted=False))
    monkeypatch.setattr(cave_topup, "wants_topup", lambda ctx: True)
    assert grind_heal.potion_instead(_ctx()) is True
    assert grind_heal.potion_instead(_ctx(grind=False)) is False     # only while grinding
    monkeypatch.setattr(grind_heal, "read_party_view", lambda e: SimpleNamespace(any_fainted=True))
    assert grind_heal.potion_instead(_ctx()) is False                # a fainted mon needs the nurse
    calls = []
    monkeypatch.setattr(grind_heal, "read_party_view", lambda e: SimpleNamespace(any_fainted=False))
    monkeypatch.setattr(retreat_heal.heal_walk, "start", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(retreat_heal, "read_party", lambda e: [SimpleNamespace(hp=5, max_hp=30, species=1, level=9)])
    monkeypatch.setattr(retreat_heal.RetreatHeal, "_hurt", staticmethod(lambda ctx, p: True))
    assert retreat_heal.RetreatHeal().step(_ctx()) is None and calls == []   # no retreat while the Potion is the cheaper way


def test_leaving_the_center_walks_straight_to_the_grass():
    assert after_heal.leaving(("DOWN", "goal beat_misty: leaving the Pokecenter (4 steps)"), 0x40)
    assert not after_heal.leaving(("UP", "HP 5/30: walking up to the nurse"), 0x40)
    assert not after_heal.leaving(("DOWN", "goal x: leaving the Pokecenter (4 steps)"), 0x23)   # outside a center: no
