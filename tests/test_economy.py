"""Economy v1: shopping list sizing and priority, the reserve, a multi-item Mart visit, the whitelist-only sell flow,
potion vs walk to the Pokecenter, and the money fields in the battle record."""
from __future__ import annotations

import json

import pytest

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.explorer import party_log, shop
from pokeagent.explorer.behaviours import Restock
from pokeagent.explorer.behaviours.cave_topup import CaveTopUp, wants_topup
from pokeagent.explorer.economy import budget, hp_stats, ledger, outside_use, prices, shopping
from pokeagent.explorer.economy.bundles import candidate_bundles
from pokeagent.explorer.economy.prices import ESCAPE_ROPE, NUGGET, POKE_BALL, POTION
from pokeagent.legs import grid as G
from pokeagent.screentext import CHARMAP
from test_team_inventory import MONEY, bcd, make_ctx
from test_xp_logging import make_ctx as xp_ctx
from test_xp_logging import party

REV = {v: k for k, v in CHARMAP.items() if len(v) == 1 and v.strip()}
PARTY = [[1, 10, 0, 30, 30]]


def lst(money, bag=None, **kw):
    return shopping.shopping_list(kw.pop("goals", {}), bag or {}, money, PARTY, None, needs_balls=kw.pop("needs_balls", True),
                                  cave=kw.pop("cave", False), **kw)


# ---- shopping list ----
def test_priority_balls_then_potion_floor_then_rope_then_more_potions():
    plenty = lst(20000, cave=True)
    assert [i for i, _ in plenty] == [POKE_BALL, POTION, ESCAPE_ROPE]
    assert dict(plenty) == {POKE_BALL: 10, POTION: 3, ESCAPE_ROPE: 1}
    tight = lst(2500)  # reserve 300 + 625: 1575 spendable: 7 balls eat it all before any potion
    assert tight == [(POKE_BALL, 7)]
    no_need = lst(20000, needs_balls=False)
    assert POKE_BALL not in dict(no_need)


def test_potions_are_sized_by_the_expected_hp_loss():
    stats = hp_stats.HpStats(overall=[60] * 10)
    big = shopping.shopping_list({}, {POTION: 3}, 20000, [[1, 30, 0, 200, 200]], stats, needs_balls=False, cave=False)
    assert big == [(POTION, 7)]  # 5 fights x 60 HP = 300 HP = 15 potions, capped at 10, minus the 3 carried
    thin = shopping.shopping_list({}, {}, 20000, [[1, 30, 0, 200, 200]], None, needs_balls=False, cave=False)
    assert thin == [(POTION, 3)]  # no data: the default loss gives the floor


def test_reserve_is_never_breached():
    goals = {"beat_brock": True}
    for money in range(0, 30001, 137):
        items = lst(money, goals=goals, cave=True)
        assert money - shopping.cost(items) >= min(money, budget.reserve(goals, money)), money
    assert budget.reserve({}, 4000) == 300 + 1000 and budget.reserve(goals, 4000) == 1400
    assert lst(budget.reserve({}, 900)) == []  # at the reserve: nothing


def test_bundles_are_a_seam_not_wired():
    out = candidate_bundles({}, {}, 20000, PARTY, None, needs_balls=True, cave=True)
    assert [b.name for b in out][0] == "lean" and len({b.items for b in out}) == len(out)
    assert dict(out[0].items).get(ESCAPE_ROPE) is None


def test_prices_from_rom_or_fallback():
    assert prices.price(POTION) == 300 and prices.sell_price(NUGGET) == 5000 and prices.price(ESCAPE_ROPE) == 550


# ---- a multi-item visit ----
def test_mart_visit_buys_the_whole_list_and_logs_it(tmp_path, monkeypatch):
    calls = []

    def fake_buy(emu, item, qty):
        before = shop.read_money(emu)
        after = before - qty * prices.price(item)
        for k, v in bcd(after).items():
            emu.set(k, v)
        calls.append((item, qty))
        return type("R", (), dict(ok=True, reason="ok", bought=qty, money_before=before, money_after=after, bag_after={}))

    monkeypatch.setattr(shop, "buy", fake_buy)
    ctx = make_ctx(tmp_path, 1, 6000, m=67, x=2, y=5)
    ctx.restock, ctx.facing = {"intent": True, "stats_path": str(tmp_path / "none.jsonl")}, "LEFT"
    Restock().step(ctx)
    assert [i for i, _ in calls] == [POKE_BALL, POTION] and calls[0][1] == 10
    money = shop.read_money(ctx.emu)
    assert money >= budget.reserve({}, 6000)  # never below the reserve
    led = ledger.of(ctx)
    assert [p["item"] for p in led.purchases] == [POKE_BALL, POTION] and led.spend == 6000 - money
    assert led.purchases[0]["money_before"] == 6000 and led.purchases[-1]["money_after"] == money
    assert ctx.shop_intent is None and not ctx.restock["intent"]


def test_restock_sets_the_shop_intent_hook_while_walking(tmp_path):
    ctx = make_ctx(tmp_path, 1, 4000)
    ctx.restock["stats_path"] = str(tmp_path / "none.jsonl")
    assert Restock().step(ctx).rule == "restock_walk" and ctx.shop_intent == ("mart", None)


# ---- the sell flow ----
class MartSim(FakeEmulator):
    """A scripted clerk: talk -> BUY/SELL/QUIT -> sell list -> 'I can pay you $N for that.' YES/NO."""

    def __init__(self, bag, money, prompt_price, prompt_item=NUGGET):
        mem = {0xD31D: len(bag), **bcd(money)}
        for i, (item, qty) in enumerate(bag):
            mem[0xD31E + 2 * i], mem[0xD31F + 2 * i] = item, qty
        super().__init__(mem)
        self.state, self.cur, self.prompt_price, self.prompt_item, self.yes_pressed = "talk", 0, prompt_price, prompt_item, False
        self.draw()

    def text(self, rows):
        for r in range(18):
            for c in range(20):
                self.set(shop.TILEMAP + r * 20 + c, 0x7F)
        for r, line in enumerate(rows):
            for c, ch in enumerate(line):
                self.set(shop.TILEMAP + r * 20 + c, shop.YEN if ch == "$" else 0x7F if ch == " " else REV[ch])

    def draw(self):
        tb = {"talk": 0, "menu": 14, "list": 13, "prompt": 13}[self.state]
        self.set(shop.TEXT_BOX_ID, tb)
        self.set(shop.MENU_ITEM, self.cur if self.state != "list" else self.cur)
        if self.state == "talk":
            self.text(["Hi there"])
        elif self.state == "menu":
            self.text([(">" if i == self.cur else " ") + n for i, n in enumerate(("BUY", "SELL", "QUIT"))])
        elif self.state == "list":
            self.text([(">" if i == self.cur else " ") + f"item{i}" for i in range(prices.price(0) or 3)])
        else:
            self.text(["I can pay you", f"${self.prompt_price} for that.", ">YES", " NO"])

    def press(self, button, hold_frames=8, settle_frames=16):
        super().press(button, hold_frames, settle_frames)
        s = self.state
        if s == "talk" and button is Button.A:
            self.state, self.cur = "menu", 0
        elif s == "menu" and button is Button.DOWN:
            self.cur = min(2, self.cur + 1)
        elif s == "menu" and button is Button.A and self.cur == 1:
            self.state, self.cur = "list", 0
        elif s == "list" and button is Button.DOWN:
            self.cur = min(2, self.cur + 1)
        elif s == "list" and button is Button.A:
            self.state, self.cur = "prompt", 0
        elif s == "prompt" and button is Button.A:
            self.yes_pressed = True
            gain = self.prompt_price
            for k, v in bcd(shop.read_money(self) + gain).items():
                self.set(k, v)
            bag = shop.bag_contents(self)
            bag[self.prompt_item] = bag.get(self.prompt_item, 1) - 1
            self.set(0xD31D, 0)  # the single stack is gone
            self.state = "list"
        elif button is Button.B:
            self.state, self.cur = {"prompt": ("list", 0), "list": ("menu", 1), "menu": ("talk", 0)}.get(s, (s, self.cur))
            if s == "menu":
                self.set(shop.TEXT_BOX_ID, 0)
        self.draw()
        if self.state == "talk":
            self.text([])


def test_sell_refuses_a_non_whitelisted_item_without_pressing_anything():
    emu = MartSim([(POTION, 2), (NUGGET, 1)], 1000, 5000)
    res = shop.sell(emu, POTION)
    assert not res.ok and res.reason == "not_whitelisted" and emu.presses == [] and shop.read_money(emu) == 1000
    assert shop.sell(MartSim([(POTION, 1)], 10, 5000), NUGGET).reason == "not_in_bag"


def test_sell_never_confirms_the_wrong_prompt():
    emu = MartSim([(NUGGET, 1)], 1000, 2500)  # the prompt offers 2500 where a Nugget is worth 5000
    res = shop.sell(emu, NUGGET)
    assert not res.ok and res.reason == "sell_confirm_mismatch" and not emu.yes_pressed and shop.read_money(emu) == 1000
    assert not shop.sell_confirm_shown(FakeEmulator(), 5000)  # nothing on screen is never a confirm


def test_sell_nugget_confirms_only_the_matching_prompt():
    emu = MartSim([(NUGGET, 1)], 1000, 5000)
    res = shop.sell(emu, NUGGET)
    assert res.ok, res.reason
    assert emu.yes_pressed and (res.money_before, res.money_after, res.gained) == (1000, 6000, 5000)
    # A was only pressed on the menu's SELL row, never on BUY or QUIT: the first menu A came after the DOWN
    menu_a = emu.presses.index(Button.DOWN)
    assert Button.A not in emu.presses[1:menu_a]


# ---- potion vs walk ----
def test_potion_beats_a_long_walk_but_not_a_short_one_or_a_healthy_party():
    far = G.FRAME_WALK * 120
    assert outside_use.potion_beats_walk(far, 0, 10, 80)             # 120 tiles away, and back
    assert not outside_use.potion_beats_walk(G.FRAME_WALK * 10, 0, 10, 80)   # next door: just walk
    assert not outside_use.potion_beats_walk(far, 0, 60, 80)         # over half HP
    assert not outside_use.potion_beats_walk(far, 0, 70, 80)
    assert not outside_use.potion_beats_walk(far, 0, 25, 30)         # 5 HP missing: a potion is wasted
    short_grass = G.FRAME_WALK * 30 + 8 * G.GRASS_PENALTY
    assert outside_use.potion_beats_walk(short_grass, 8, 5, 80) and not outside_use.potion_beats_walk(short_grass, 8, 40, 80)  # grass at low HP tips it


def _field_ctx(tmp_path, m=0x40 + 5):
    ctx = make_ctx(tmp_path, 0, 500, m=m, party_hp=(10, 80), potions=2)
    return ctx


def test_field_potion_waits_for_a_new_towns_pokecenter_and_drinks_when_far(tmp_path, monkeypatch):
    ctx = _field_ctx(tmp_path)
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (G.FRAME_WALK * 120, 0, 0x40))
    assert not wants_topup(ctx) and not CaveTopUp().applies(ctx)       # Cerulean's Pokecenter not visited: walk there and heal
    ledger.of(ctx).visited_centers.add(0x40)
    ledger.of(ctx).field_check_at = 0
    assert wants_topup(ctx) and CaveTopUp().applies(ctx)               # visited and far: a potion is cheaper
    ledger.of(ctx).field_check_at = 0
    monkeypatch.setattr(outside_use, "walk_to_center", lambda ctx, get=None: (G.FRAME_WALK * 8, 0, 0x40))
    assert not wants_topup(ctx)                                         # close: just walk


# ---- the money fields in the battle record ----
def test_battle_record_has_money_before_and_after_and_the_ledger_books_it(tmp_path):
    ctx = xp_ctx(tmp_path, {**party((1, 10, 0, 30, 30)), **bcd(1000)})
    log = party_log.of(ctx)
    log.start_battle(ctx)
    for k, v in bcd(1150).items():
        ctx.emu.set(k, v)
    rec = log.end_battle(ctx, True, False)
    assert (rec["money_before"], rec["money_after"]) == (1000, 1150) and ledger.of(ctx).income == 150
    log.start_battle(ctx)
    for k, v in bcd(575).items():
        ctx.emu.set(k, v)
    rec = log.end_battle(ctx, False, False)  # lost and warped: the blackout halves the money
    assert (rec["money_before"], rec["money_after"]) == (1150, 575) and ledger.of(ctx).blackout_loss == 575
    s = ledger.of(ctx).summary()
    assert (s["income"], s["blackout_loss"], s["net"]) == (150, 575, -425)


def test_hp_stats_from_battle_records(tmp_path):
    p = tmp_path / "b.jsonl"
    recs = [{"map": 12, "won": True, "party_before": [[1, 5, 0, 30, 30]], "party_after": [[1, 5, 0, 20, 30]]},
            {"map": 12, "won": False, "fled": False, "party_before": [[1, 5, 0, 8, 30]], "party_after": [[1, 5, 0, 30, 30]]}, {"map": 1}]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\nnot json\n")
    st = hp_stats.load_hp_loss(p)
    assert st.by_map[12] == [10, 8] and hp_stats.expected_battle_loss(st, 12) == hp_stats.DEFAULT_LOSS  # < MIN_SAMPLES: default
