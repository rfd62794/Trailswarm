"""Economy v1: shopping list sizing and priority, the reserve, a multi-item Mart visit, the whitelist-only sell flow,
potion vs walk to the Pokecenter, and the money fields in the battle record."""
from __future__ import annotations

import json

import pytest

from pokeagent.emulator import Button, FakeEmulator
from pokeagent.explorer import party_log, shop
from pokeagent.explorer.behaviours import Restock
from pokeagent.explorer.behaviours.cave_topup import CaveTopUp, wants_topup
from pokeagent.explorer.economy import atlas, budget, floor, heal_items, hp_stats, ledger, outside_use, prices, shopping
from pokeagent.explorer.economy.bundles import candidate_bundles
from pokeagent.explorer.economy.prices import ESCAPE_ROPE, NUGGET, POKE_BALL, POTION, SUPER_POTION
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
def test_priority_balls_then_potion_floor_then_rope():
    plenty = lst(20000, cave=True)
    assert [i for i, _ in plenty] == [POKE_BALL, POTION, ESCAPE_ROPE]
    assert dict(plenty) == {POKE_BALL: 10, POTION: 2, ESCAPE_ROPE: 1}  # PARTY max HP 30: the default loss caps at 30 HP = 2 Potions
    tight = lst(2500)  # reserve 300 + 625: 1575 spendable: 7 balls eat it all before any potion
    assert tight == [(POKE_BALL, 7)]
    no_need = lst(20000, needs_balls=False)
    assert POKE_BALL not in dict(no_need)


def test_potions_are_sized_by_the_expected_hp_loss_and_capped():
    stats = hp_stats.HpStats(overall=[10, 600])
    big = shopping.shopping_list({}, {POTION: 1}, 20000, [[1, 30, 0, 200, 200]], stats, needs_balls=False, cave=False)
    assert big == [(POTION, 2)]  # 5 fights x 60 HP = 300 HP = 15 Potions, capped at the floor cap of 3, minus the 1 carried
    thin = shopping.shopping_list({}, {}, 20000, [[1, 30, 0, 200, 200]], None, needs_balls=False, cave=False)
    assert thin == [(POTION, 3)]  # no data: 5 x 12 HP = 60 HP = 3 Potions
    quiet = hp_stats.HpStats(overall=[10, 30])
    assert shopping.shopping_list({}, {}, 20000, [[1, 30, 0, 200, 200]], quiet, needs_balls=False, cave=False) == [(POTION, 1)]
    assert shopping.shopping_list({}, {POTION: 1}, 20000, [[1, 30, 0, 200, 200]], quiet, needs_balls=False, cave=False) == []


# ---- the potion floor ----
def test_floor_is_one_to_three_potions():
    quiet, rough = hp_stats.HpStats(overall=[10, 10]), hp_stats.HpStats(overall=[10, 900])
    party = [[1, 30, 0, 79, 79]]
    assert floor.potion_floor(quiet, party, None) == floor.FLOOR_MIN == 1
    assert floor.potion_floor(rough, party, None) == floor.FLOOR_CAP == 3
    assert floor.potion_floor(rough, party, None, scale=0.0) == 1


def test_a_single_potion_trip_is_worth_it_only_with_an_empty_bag():
    one = [(POTION, 1)]
    assert shopping.cost(one) < shopping.MIN_TRIP_YEN
    assert shopping.trip_worth(one, {}) and not shopping.trip_worth(one, {POTION: 1})
    assert not shopping.trip_worth([(POKE_BALL, 1)], {})


STOCK = {42: [4, 11], 56: [4, 20], 67: [4, 20], 91: [4, 19, 13]}   # Lavender-ish, Pewter, Cerulean, Vermilion (Super Potion only)


def sells(i, m):
    return i in STOCK[m]


def test_heal_item_ids_match_the_rom_catalog_and_hp_table():
    assert (POTION, SUPER_POTION) == (0x14, 0x13) and heal_items.HEAL_ITEMS == (POTION, SUPER_POTION)
    assert prices.HEAL_HP == {POTION: 20, SUPER_POTION: 50} and prices.price(SUPER_POTION) == 700


def test_marts_selling_now_includes_the_vermilion_mart_for_a_heal_trip():
    marts = frozenset({42, 56, 67, 91})
    assert floor.marts_selling([(POTION, 3)], marts, sells) == {56, 67, 91}   # Super Potion stands in for Potion
    assert floor.marts_selling([(POKE_BALL, 10), (POTION, 3)], marts, sells) == marts
    assert floor.marts_selling([(POTION, 1)], frozenset({91}), sells) == frozenset({91})
    assert floor.marts_selling([(POTION, 1)], frozenset({42}), sells) == frozenset()   # a Mart with no heal item still does not count
    assert floor.marts_selling([(POKE_BALL, 10)], frozenset({42}), sells) == frozenset({42})


def test_battle_and_field_use_pick_the_smallest_item_that_covers_the_missing_hp():
    both = {POTION: 1, SUPER_POTION: 1}
    assert heal_items.pick_for_missing(both, 15) == POTION and heal_items.pick_for_missing(both, 20) == POTION
    assert heal_items.pick_for_missing(both, 35) == SUPER_POTION           # a Potion would leave 15 missing
    assert heal_items.pick_for_missing({SUPER_POTION: 1}, 15) == SUPER_POTION   # the only item
    assert heal_items.pick_for_missing({POTION: 2}, 90) == POTION            # nothing covers it: the biggest carried
    assert heal_items.pick_for_missing({}, 15) is None
    assert heal_items.pick_for_missing(both, 15, blocked={POTION}) == SUPER_POTION   # "won't have any effect" is per item


def test_floor_counts_a_super_potion_as_two_and_a_half_potions():
    assert heal_items.potion_equivalents({SUPER_POTION: 1}) == 2.5 and heal_items.potion_equivalents({POTION: 1, SUPER_POTION: 1}) == 3.5
    assert floor.floor_hp(1) == 20 and floor.floor_hp(3) == 60
    rough = hp_stats.HpStats(overall=[10, 900])   # floor 3 = 60 HP
    party = [[1, 30, 0, 79, 79]]
    kw = dict(needs_balls=False, cave=False, mart=67, stock=sells)
    assert shopping.shopping_list({}, {SUPER_POTION: 1}, 20000, party, rough, **kw) == [(POTION, 1)]   # 50 HP carried: 10 HP short = 1 Potion
    assert shopping.shopping_list({}, {SUPER_POTION: 2}, 20000, party, rough, **kw) == []              # 100 HP: floor met
    assert shopping.shopping_list({}, {POTION: 1, SUPER_POTION: 1}, 20000, party, rough, **kw) == []   # 70 HP
    assert floor.trip_is_floor([(POTION, 1)], {SUPER_POTION: 1}) is False and floor.trip_is_floor([(POTION, 1)], {}) is True
    assert floor.trip_is_floor([(SUPER_POTION, 1)], {POTION: 1}) is False


def test_shopping_at_vermilion_with_an_empty_bag_lists_one_super_potion_and_cerulean_lists_potions():
    quiet = hp_stats.HpStats(overall=[10, 30])   # floor 1 = 20 HP
    party = [[1, 30, 0, 200, 200]]
    kw = dict(needs_balls=False, cave=False, stock=sells)
    assert shopping.shopping_list({}, {}, 20000, party, quiet, mart=91, **kw) == [(SUPER_POTION, 1)]
    assert shopping.shopping_list({}, {}, 20000, party, quiet, mart=67, **kw) == [(POTION, 1)]
    rough = hp_stats.HpStats(overall=[10, 900])  # floor 3 = 60 HP
    assert shopping.shopping_list({}, {}, 20000, party, rough, mart=91, **kw) == [(SUPER_POTION, 2)]   # 100 HP covers 60
    assert shopping.shopping_list({}, {}, 20000, party, rough, mart=67, **kw) == [(POTION, 3)]
    assert shopping.shopping_list({}, {}, 20000, party, quiet, **dict(kw, mart=None)) == [(POTION, 1)]   # planning: Potions
    assert shopping.shopping_list({}, {}, 800, party, quiet, mart=91, **kw) == []   # reserve 300 leaves 500: a 700 yen Super Potion is out of reach


def test_buy_choice_takes_the_cheapest_total_that_fills_the_gap():
    both = lambda i: True  # noqa: E731
    assert heal_items.buy_choice(20, both, 5000) == (POTION, 1)
    assert heal_items.buy_choice(60, both, 5000) == (POTION, 3)
    assert heal_items.buy_choice(45, lambda i: i == SUPER_POTION, 5000) == (SUPER_POTION, 1)
    assert heal_items.buy_choice(40, both, 500) == (POTION, 1)   # cannot fill 40 HP for 500: what the money allows
    assert heal_items.buy_choice(0, both, 500) is None and heal_items.buy_choice(20, lambda i: False, 5000) is None


def test_restock_walks_to_a_mart_that_sells_only_super_potion_but_not_one_with_no_heal_item(tmp_path, monkeypatch):
    stock = {91: [4, 19]}
    monkeypatch.setattr(prices, "stocked", lambda i, m: i in stock.get(m, [i]))
    monkeypatch.setattr(floor, "stocked", prices.stocked)
    monkeypatch.setattr(shopping, "ball_need", lambda goals: False)
    monkeypatch.setattr(shopping, "cave_ahead", lambda goals: False)

    def go():
        ctx = make_ctx(tmp_path, 1, 11258, m=91, x=3, y=7)
        ctx.restock["stats_path"] = str(tmp_path / "none.jsonl")
        ctx.goals = lambda: {"beat_brock": True, "beat_misty": True, "deliver_parcel": True}
        return ctx, Restock().step(ctx)

    ctx, d = go()
    assert d is not None and ctx.restock.get("intent")   # empty bag, Vermilion sells Super Potion: worth the trip
    stock[91] = [4, 11]
    ctx, d = go()
    assert d is None and not ctx.restock.get("intent") and ctx.shop_intent is None   # no Potion or Super Potion at all


def test_mart_visit_at_vermilion_buys_a_super_potion(tmp_path, monkeypatch):
    calls = []

    def fake_buy(emu, item, qty):
        before = shop.read_money(emu)
        after = before - qty * prices.price(item)
        for k, v in bcd(after).items():
            emu.set(k, v)
        calls.append((item, qty))
        return type("R", (), dict(ok=True, reason="ok", bought=qty, money_before=before, money_after=after, bag_after={}))

    monkeypatch.setattr(shop, "buy", fake_buy)
    monkeypatch.setattr(prices, "stocked", lambda i, m: i in STOCK.get(m, [i]))
    from pokeagent.explorer.behaviours import restock as restock_mod
    monkeypatch.setattr(restock_mod, "stocked", prices.stocked)
    monkeypatch.setattr(shopping, "stocked", prices.stocked)
    monkeypatch.setattr(shopping, "ball_need", lambda goals: False)
    monkeypatch.setattr(shopping, "cave_ahead", lambda goals: False)
    ctx = make_ctx(tmp_path, 1, 6000, m=91, x=2, y=5)
    ctx.restock, ctx.facing = {"intent": True, "stats_path": str(tmp_path / "none.jsonl")}, "LEFT"
    Restock().step(ctx)
    assert calls == [(SUPER_POTION, 2)]   # no battle data: floor 3 = 60 HP, and two Super Potions (100 HP) is the least that reaches it
    assert shop.read_money(ctx.emu) >= budget.reserve({}, 6000)


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
    assert st.by_map[12] == [2, 18] and hp_stats.expected_battle_loss(st, 12) == hp_stats.DEFAULT_LOSS  # < MIN_SAMPLES: default


# ---- the ROM catalog (gated: needs kb/rom_tables.json and the ROM) ----
from pokeagent.knowledge import items_catalog as ic  # noqa: E402

needs_rom = pytest.mark.skipif(ic.load() is None, reason="no ROM / kb/rom_tables.json")


@needs_rom
def test_catalog_known_values_and_categories():
    cat = ic.load()
    it = lambda i: ic.item(cat, i)  # noqa: E731
    assert (it(0x14)["price"], it(0x04)["price"], it(0x31)["sell"]) == (300, 200, 5000)
    assert ic.category_of(0x14) == "healing" and ic.category_of(0x28) == "rare_candy" and ic.category_of(0x0A) == "stone"
    assert ic.category_of(0x3F) == "key" and it(0x3F)["key_item"] and ic.category_of(0xC4) == "tm_hm" and ic.category_of(0x1D) == "escape_rope"
    assert ic.category_of(0x31) == "valuable" and not it(0x31)["key_item"] and it(0x14)["battle"] and it(0x1D)["overworld"]
    assert ic.category_of(0x23) == "vitamin" and ic.category_of(0x04) == "ball" and ic.category_of(0x0B) == "status_cure"


@needs_rom
def test_catalog_marts_and_prize_money():
    cat = ic.load()
    assert ic.stock_for_map(cat, 56)[:2] == [0x04, 0x14] and POTION not in ic.stock_for_map(cat, 42)  # Pewter sells Potions, Viridian does not
    assert not prices.stocked(POTION, 42) and prices.stocked(POTION, 67) and prices.stocked(POTION, 3)  # 3 is not a Mart: unknown = try
    assert ic.trainer_prize(cat, "BROCK", 1) == 99 * 14 == 1386 and ic.trainer_prize(cat, "YOUNGSTER", 1) == 15 * 11
    assert ic.map_income(cat, 54) > 1386 and ic.trainer_prize(cat, "BROCK", 9) is None


# ---- item-use log and the cross-run ledger ----
def test_item_use_is_logged_with_hp_before_and_after(tmp_path):
    ctx = _field_ctx(tmp_path)
    ledger.of(ctx).use(ctx, POTION, "battle potion timing", "battle", 8, 28, True)
    ledger.of(ctx).use(ctx, POTION, "field potion instead of a Pokecenter walk", "cave_topup", 5, 25, False)
    u = ledger.of(ctx).summary()["uses"]
    assert [(r["item"], r["hp_before"], r["hp_after"], r["battle"]) for r in u] == [(POTION, 8, 28, True), (POTION, 5, 25, False)]


def test_battle_record_carries_potions_before(tmp_path):
    ctx = xp_ctx(tmp_path, {**party((1, 10, 0, 30, 30)), **bcd(1000), 0xD31D: 1, 0xD31E: POTION, 0xD31F: 2})
    log = party_log.of(ctx)
    log.start_battle(ctx)
    assert log.end_battle(ctx, True, False)["potions_before"] == 2


def test_economy_refresh_folds_battles_by_cursor_and_finished_runs(tmp_path):
    runs = tmp_path
    rec = lambda **k: json.dumps({"map": 12, "kind": 2, "won": True, "party_before": [[1, 5, 0, 30, 30]],  # noqa: E731
                                  "party_after": [[1, 5, 0, 20, 30]], "money_before": 1000, "money_after": 1165, **k}) + chr(10)
    (runs / "battles.jsonl").write_text(rec() + rec(kind=1, money_after=1000) + rec(won=False, fled=False, money_after=500, potions_before=0))
    run = runs / "explore-x"
    run.mkdir()
    econ = {"purchases": [{"item": POTION, "qty": 3, "cost": 900}], "sales": [{"gained": 5000}], "stock_seen": {"67": [4, 20]},
            "uses": [{"item": POTION, "why": "field potion instead of a Pokecenter walk", "hp_before": 5, "hp_after": 25, "battle": False},
                     {"item": POTION, "why": "battle potion timing", "hp_before": 8, "hp_after": 28, "battle": True}]}
    (run / "meta.json").write_text(json.dumps({"econ_summary": econ}))
    (runs / "explore-unfinished").mkdir()
    (runs / "explore-unfinished" / "meta.json").write_text("{}")
    assert atlas.refresh(runs) == {"battles": 3, "runs": 1, "offset": (runs / "battles.jsonl").stat().st_size}
    d = json.loads((runs / "economy.json").read_text())
    assert d["income"]["trainer"] == 165 and d["income"]["sales"] == 5000 and d["income"]["by_map"]["12"] == 165
    assert d["blackouts"] == {"n": 1, "yen": 500, "no_potion": 1, "by_map": {"12": 1}} and d["hp"]["overall"] == [3, 10 + 10 + 30]
    assert d["spend"][str(POTION)] == {"qty": 3, "yen": 900} and d["uses"][str(POTION)]["hp_restored"] == 40 and d["heal_trips_avoided"] == 1
    assert atlas.refresh(runs)["battles"] == 0 and atlas.refresh(runs)["runs"] == 0  # nothing is folded twice
    with (runs / "battles.jsonl").open("a") as fh:
        fh.write(rec())
    assert atlas.refresh(runs)["battles"] == 1
    assert hp_stats.from_atlas(json.loads((runs / "economy.json").read_text())).overall == [4, 60]
