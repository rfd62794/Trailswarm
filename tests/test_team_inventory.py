"""Team & Inventory v1: ball restock rule + behaviour, the catch need-list, and the SELL guard in the shop."""
from __future__ import annotations

import pytest

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.explorer import restock as rs
from pokeagent.explorer import shop
from pokeagent.explorer.behaviours import Catch, Restock
from pokeagent.explorer.behaviours.battle import BattleView
from pokeagent.explorer import catch_list
from pokeagent.explorer.catch_list import catch_wanted, upcoming_needs
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.kb import ROM_KB
from pokeagent.knowledge import hm_compat
from pokeagent.explorer.memory import MapMemory
from pokeagent.screentext import CHARMAP

MAP, PX, PY, BAG_N, MONEY = 0xD35E, 0xD362, 0xD361, 0xD31D, 0xD347
REV = {v: k for k, v in CHARMAP.items() if len(v) == 1 and v.strip()}
needs_rom = pytest.mark.skipif(ROM_KB is None, reason="kb/rom_tables.json not present")


def bcd(n: int) -> dict:
    s = f"{n:06d}"
    return {MONEY + i: int(s[2 * i]) * 16 + int(s[2 * i + 1]) for i in range(3)}


def world() -> dict:
    """Cerulean (3) with its Mart door at (23,18) leading to the Mart (67), whose door tile is (3,7)."""
    outside = {f"{x},19": 1 for x in range(20, 26)} | {"23,18": 1}
    inside = {f"3,{y}": 1 for y in (5, 6, 7)} | {"2,5": 1}
    return {"3": {"visited": outside, "blocked": [], "warps": {"23,18,UP": [67, 3, 7]}},
            "67": {"visited": inside, "blocked": [], "warps": {"3,7,DOWN": [3, 23, 19]}}}


def make_ctx(tmp_path, balls: int, money: int, m: int = 3, x: int = 23, y: int = 19, party_hp=(30, 30), potions: int = 0) -> ExplorerContext:
    mem = {MAP: m, PX: x, PY: y, **bcd(money), 0xD16C: 0, 0xD16D: party_hp[0], 0xD18D: 0, 0xD18E: party_hp[1]}
    bag = [(0x04, balls)] * bool(balls) + [(0x14, potions)] * bool(potions)
    mem[BAG_N] = len(bag)
    for i, (item, qty) in enumerate(bag):
        mem.update({0xD31E + 2 * i: item, 0xD31F + 2 * i: qty})
    ctx = ExplorerContext(emu=FakeEmulator(mem), mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=10)
    ctx.mem.data["maps"] = world()
    ctx.facing = "UP"
    ctx.refresh()
    return ctx


def test_buy_rule_by_ball_count_and_money():
    enough = rs.ball_price() * rs.BALL_BUY + rs.MONEY_RESERVE
    assert rs.ball_buy_wanted(0, enough) and rs.ball_buy_wanted(rs.BALL_MIN - 1, enough)
    assert not rs.ball_buy_wanted(rs.BALL_MIN, enough)            # enough balls
    assert not rs.ball_buy_wanted(0, enough - 1)                   # too poor (the reserve stays)
    assert not rs.ball_buy_wanted(0, enough, tries=rs.MAX_TRIES)  # the per-run cap
    assert rs.buy_quantity(enough) == rs.BALL_BUY and rs.buy_quantity(100) == 0


def test_restock_sets_intent_and_walks_to_the_mart(tmp_path):
    ctx = make_ctx(tmp_path, balls=1, money=4000)
    d = Restock().step(ctx)
    assert ctx.restock["intent"] and d.rule == "restock_walk" and d.button in ("RIGHT", "LEFT", "UP")


def test_restock_stays_quiet_with_balls_or_without_money(tmp_path):
    for balls, money in ((9, 4000), (1, 500)):  # economy: the potion floor is stocked too, so quiet means balls AND potions are fine
        ctx = make_ctx(tmp_path, balls, money, potions=3)
        assert Restock().step(ctx) is None and not ctx.restock.get("intent")


def test_restock_waits_for_the_parcel_at_viridian_and_when_no_mart_is_known(tmp_path):
    ctx = make_ctx(tmp_path, 1, 4000)
    ctx.mem.data["maps"] = {"3": world()["3"] | {"warps": {}}}  # no Mart learned
    assert Restock().step(ctx) is None
    assert 42 not in rs.candidate_marts({"deliver_parcel": False}) and 42 in rs.candidate_marts({"deliver_parcel": True})


def test_restock_heals_first_when_the_lead_is_weak(tmp_path):
    assert Restock().step(make_ctx(tmp_path, 1, 4000, party_hp=(5, 30))) is None


def test_cap_stops_loops(tmp_path):
    ctx = make_ctx(tmp_path, 1, 4000)
    ctx.restock = {"tries": rs.MAX_TRIES}
    assert Restock().step(ctx) is None and not ctx.restock.get("intent")
    ctx = make_ctx(tmp_path, 1, 4000)
    ctx.restock = {"intent": True, "steps": rs.MAX_TRIP_STEPS}  # a trip that never arrives gives up and counts as a try
    assert Restock().step(ctx) is None and not ctx.restock["intent"] and ctx.restock["tries"] == 1


def test_in_mart_walks_to_the_counter_then_buys_balls_once(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, 1, 4000, m=67, x=3, y=7)
    ctx.restock = {"intent": True}
    d = Restock().step(ctx)
    assert d.rule == "restock_walk" and d.button == "UP"
    calls = []

    class Res:
        ok, reason, bought, money_before, money_after, bag_after = True, "ok", 10, 4000, 2000, {4: 11}

    monkeypatch.setattr(shop, "buy", lambda emu, item, qty: calls.append((item, qty)) or Res)
    ctx = make_ctx(tmp_path, 1, 4000, m=67, x=2, y=5)
    ctx.restock = {"intent": True}
    assert Restock().step(ctx).button == "LEFT"  # turn to face the clerk first
    ctx.facing = "LEFT"
    d = Restock().step(ctx)
    assert calls == [(0x04, rs.BALL_BUY), (0x14, 2)]  # balls first, then potions with what the reserve leaves
    assert d.button == "" and not ctx.restock["intent"] and ctx.restock["bought"] == 20


def test_failed_purchase_marks_the_mart_and_never_loops(tmp_path, monkeypatch):
    class Res:
        ok, reason, bought, money_before, money_after, bag_after = False, "no_buy_menu", 0, 4000, 4000, {}

    monkeypatch.setattr(shop, "buy", lambda *a: Res)
    ctx = make_ctx(tmp_path, 1, 4000, m=67, x=2, y=5)
    ctx.restock, ctx.facing = {"intent": True}, "LEFT"
    Restock().step(ctx)
    assert 67 in ctx.restock["failed"] and 67 not in rs.candidate_marts({"deliver_parcel": True}, ctx.restock["failed"])


# ---- catch_wanted ----
SYNTHETIC_HM = {"cut": frozenset({"BULBASAUR", "BELLSPROUT"}), "flash": frozenset({"ABRA", "PIKACHU"})}


@pytest.fixture
def synthetic_hm(monkeypatch):
    """A tiny HM table, so these tests need neither the ROM nor kb/hm_compat.json."""
    monkeypatch.setattr(catch_list, "hm_table", lambda: SYNTHETIC_HM)


def test_catch_wanted_a_hm_learner_when_nobody_can(synthetic_hm):
    assert "CUT" in catch_wanted("BELLSPROUT", ["SQUIRTLE"], 3, ["cut"])
    assert catch_wanted("BELLSPROUT", ["BULBASAUR"], 30, ["cut"]) is None       # the party already has a Cut user
    assert catch_wanted("PIDGEY", ["SQUIRTLE"], 30, ["cut"]) is None            # not a Cut learner
    assert catch_wanted("ABRA", ["SQUIRTLE"], 30, ["flash"]) is not None  # Flash learners are ABRA, PIKACHU ...
    assert catch_wanted("BELLSPROUT", ["SQUIRTLE"], 30, []) is None            # nothing ahead needs it


@pytest.mark.skipif(not hm_compat.ROM_PATH.exists() or ROM_KB is None, reason="ROM / kb not present")
def test_real_hm_table_from_the_rom():
    t = hm_compat.load()
    assert "SQUIRTLE" not in t["cut"] and {"BULBASAUR", "BELLSPROUT", "ODDISH"} <= t["cut"] and "ABRA" in t["flash"]


def test_no_hm_data_degrades_to_dex_only(monkeypatch, caplog):
    monkeypatch.setattr(hm_compat, "load", lambda: None)
    monkeypatch.setattr(catch_list, "_warned", False)
    assert catch_list.hm_table() == {} and catch_list.hm_table() == {}
    assert sum("HM-learner catching is off" in r.message for r in caplog.records) == 1  # one-time log line
    assert catch_wanted("BELLSPROUT", ["SQUIRTLE"], 3, ["cut"]) is None                 # (a) off
    assert catch_wanted("BELLSPROUT", ["SQUIRTLE"], 3, ["cut", "dex10"]) is not None     # (b) still works


def test_catch_wanted_b_new_species_while_dex10_is_ahead():
    assert "Pokedex" in catch_wanted("PIDGEY", ["SQUIRTLE"], 3, ["dex10"])
    assert catch_wanted("PIDGEY", ["SQUIRTLE"], 10, ["dex10"]) is None
    assert catch_wanted("PIDGEY", ["SQUIRTLE"], 3, ["dex10"], owned=True) is None


def test_catch_wanted_c_otherwise_none():
    assert catch_wanted("RATTATA", ["SQUIRTLE"], 12, ["cut", "dex10"]) is None


def test_upcoming_needs_come_from_the_unmet_campaign_goals():
    from pokeagent.campaign import goal_ids
    assert "cut" in upcoming_needs({}) and "dex10" in upcoming_needs({})
    assert upcoming_needs({g: True for g in goal_ids()}) == []


# ---- catch.py consults the need-list ----
def battle_ctx(tmp_path, species: int, owned_count: int):
    ctx = make_ctx(tmp_path, balls=5, money=0)
    ctx.emu.set(0xD057, 1)
    for i in range(owned_count):
        ctx.emu.set(0xD2F7 + i // 8, ctx.emu.read(0xD2F7 + i // 8) | 1 << (i % 8))
    ctx.emu.set(0xCFE7, 3), ctx.emu.set(0xCFF5, 20)  # enemy 3/20 HP: low enough to throw
    ctx.refresh()
    ctx.view.battling = True
    ctx.bv = BattleView(kind=1, hp=3, mx=20, run_line="RUN", species=species, e_lvl=5)
    return ctx


@needs_rom
def test_catch_skips_an_unwanted_species(tmp_path):
    ctx = battle_ctx(tmp_path, 36, owned_count=10)  # PIDGEY, 10 already owned, nobody needs it
    Catch().step(ctx)
    assert ctx.catch_attempt is None and ctx.catch_mode is False


@needs_rom
def test_catch_still_catches_a_wanted_species(tmp_path, synthetic_hm):
    ctx = battle_ctx(tmp_path, 188, owned_count=10)  # BELLSPROUT: a Cut learner and the party has none
    Catch().step(ctx)
    assert ctx.catch_attempt is not None and ctx.catch_attempt["species"] == 188


# ---- the shop never picks SELL ----
def put(emu, row, col, text):
    for i, ch in enumerate(text):
        emu.set(shop.TILEMAP + row * 20 + col + i, shop.YEN if ch == "$" else 0x7F if ch == " " else REV[ch])


def test_menu_choice_reads_the_cursor_row():
    emu = FakeEmulator()
    put(emu, 1, 1, ">BUY")
    put(emu, 2, 1, " SELL")
    assert shop.menu_choice(emu) == "BUY"
    emu = FakeEmulator()
    put(emu, 2, 1, ">SELL")
    assert shop.menu_choice(emu) == "SELL"


def test_buy_refuses_when_the_cursor_is_on_sell_and_never_presses_a_there():
    emu = FakeEmulator({shop.TEXT_BOX_ID: shop.TB_MENU})
    put(emu, 1, 1, " BUY")
    put(emu, 2, 1, ">SELL")
    put(emu, 3, 1, " QUIT")
    res = shop.buy(emu, 4, 1)  # the fake never moves the cursor, so UP cannot reach BUY
    assert not res.ok and res.reason == "menu_cursor_not_on_buy"
    assert Button.A not in emu.presses  # SELL is never confirmed (only UP presses to move back toward BUY)
