"""Item-use policies by category (explorer/item_policies): each decision and each shield, the HM teach flow's YES/NO guard, key items
never sold or tossed, use_items a no-op in battle and in menus, and the bicycle toggle. Screens in TEACH_* are what the ROM printed in a
probe on a scratch state (rows as screen_lines reads them)."""
from __future__ import annotations

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer import shop
from pokeagent.explorer.behaviours import UseItems, default_behaviours
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.economy import ledger, prices
from pokeagent.explorer.item_policies import hm_teach, ids, key_items, policy, rare_candy, repel, stones, vitamins, xitems
from pokeagent.explorer.item_policies.moves_shield import choose_overwrite, protected_moves
from pokeagent.explorer.item_policies.teach_flow import teach_press
from pokeagent.explorer.item_policies.view import Mon, fighter_slot_of
from pokeagent.explorer.kb import ROM_KB
from pokeagent.explorer.toss_guard import toss_veto
from test_explorer_behaviours import TM, make_ctx, put_box

needs_rom = pytest.mark.skipif(ROM_KB is None, reason="kb/rom_tables.json not present")
BATTLE = 0xD057

# a tiny move table: name -> (type, power, accuracy)
MOVES = {"TACKLE": ("NORMAL", 35, 0.95), "TAIL WHIP": ("NORMAL", 0, 1.0), "WATER GUN": ("WATER", 40, 1.0), "BUBBLE": ("WATER", 20, 1.0),
         "CUT": ("NORMAL", 50, 0.95), "VINE WHIP": ("GRASS", 35, 1.0), "GROWL": ("NORMAL", 0, 1.0), "EMBER": ("FIRE", 40, 1.0),
         "FLASH": ("NORMAL", 0, 1.0), "SURF": ("WATER", 95, 1.0), "SWORDS DANCE": ("NORMAL", 0, 1.0)}
CHART = {("WATER", "ROCK"): 2.0, ("GRASS", "ROCK"): 2.0, ("FIRE", "GRASS"): 2.0}


def info(name):
    t = MOVES.get(name)
    return None if t is None else {"type": t[0], "power": t[1], "accuracy": t[2]}


def mon(slot, species="IVYSAUR", level=22, moves=("TACKLE", "TAIL WHIP", "VINE WHIP", "GROWL"), hp=60, stat_exp=(0, 0, 0, 0, 0)):
    return Mon(slot, species, level, moves, hp, 60, stat_exp)


# --- 1. key items ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("item", sorted(key_items.KEY_IDS | {ids.HM01, ids.HM01 + 4}))
@pytest.mark.parametrize("action", key_items.DISPOSALS)
def test_key_items_are_never_disposed(item, action):
    assert not key_items.may_dispose(item, action, cat={"items": {}})   # even with no catalog at all


def test_ordinary_items_are_not_key_items():
    assert key_items.may_dispose(0x14, "sell", cat={"items": {}}) and key_items.may_dispose(ids.RARE_CANDY, "toss", cat={"items": {}})


def test_the_sell_whitelist_cannot_sell_a_key_item(monkeypatch):
    """Whitelisting a BICYCLE (one edit away) must still be refused before any press. Fails on code that only checks the whitelist."""
    monkeypatch.setattr(prices, "SELL_WHITELIST", frozenset({prices.NUGGET, ids.BICYCLE}))
    assert not prices.sell_allowed(ids.BICYCLE) and prices.sell_allowed(prices.NUGGET)
    emu = FakeEmulator({0xD31D: 1, 0xD31E: ids.BICYCLE, 0xD31F: 1, 0xD320: 0xFF})
    res = shop.sell(emu, ids.BICYCLE)
    assert not res.ok and res.reason == "not_whitelisted" and emu.presses == []


KEY_NAMES = ["BICYCLE", "S.S.TICKET", "CARD KEY", "SILPH SCOPE", "HM01"]


@pytest.mark.parametrize("name", KEY_NAMES)
@pytest.mark.parametrize("button", ["A", "DOWN", "START"])
def test_a_toss_prompt_over_a_key_item_never_advances(name, button):
    for rows in (["USE", ">TOSS"], [f"{name} x01", "TOSS"], [f"{name} >YES", "NO", "Is it OK to toss", f"{name}?"]):
        assert toss_veto(rows, Decision(button, "x")) is not None, (rows, button)


def test_bicycle_toggle_decision():
    mount = lambda **kw: key_items.bicycle_decision(**{"owned": True, "state": key_items.WALK, "outdoor": True, "battle": False, "leg_tiles": 30, **kw})
    assert mount()[0] == ids.BICYCLE
    assert mount(leg_tiles=None) is not None                      # unknown leg length: ride
    assert mount(owned=False) is None and mount(battle=True) is None
    assert mount(state=key_items.BIKE) is None                    # selecting the bike again would DISMOUNT: never when already riding
    assert mount(state=key_items.SURF) is None and mount(outdoor=False) is None
    assert mount(leg_tiles=key_items.BIKE_MIN_LEG - 1) is None and mount(on_cooldown=True) is None


def test_campaign_hooks_decide_only():
    assert key_items.flute_decision(owned=True, snorlax_ahead=True, battle=False)[0] == ids.POKE_FLUTE
    assert key_items.flute_decision(owned=True, snorlax_ahead=False, battle=False) is None
    assert key_items.silph_scope_decision(owned=True, map_id=0x90, battle=False)[0] == ids.SILPH_SCOPE
    assert key_items.silph_scope_decision(owned=True, map_id=0x01, battle=False) is None
    assert key_items.card_key_decision(owned=True, map_id=0xB5, facing_locked_door=True, battle=False)[0] == ids.CARD_KEY
    assert key_items.card_key_decision(owned=False, map_id=0xB5, facing_locked_door=True, battle=False) is None


# --- 2. rare candy -----------------------------------------------------------------------------------------------------------
def candy(party, gap, boss_next=True, grind=None, n=2):
    return rare_candy.should_use(candies=n, party=party, gap=gap, boss_next=boss_next, grind_minutes=grind)


def test_candy_closes_a_gap_within_the_candies_held_when_a_boss_is_next():
    hit = candy([mon(0)], (24, 22, 2))
    assert hit and hit[0] == ids.RARE_CANDY and hit[1] == 0
    assert candy([mon(0)], (26, 22, 4)) is None                   # gap 4 > 2 candies, no long grind: hold
    assert candy([mon(0)], (24, 22, 2), boss_next=False) is None  # not the boss segment: hold
    assert candy([mon(0)], None) is None                          # already ready


def test_candy_for_a_long_grind_and_never_a_magikarp():
    assert candy([mon(0)], (30, 20, 10), boss_next=False, grind=rare_candy.GRIND_MINUTES_MAX + 1)
    assert candy([mon(0)], (30, 20, 10), boss_next=False, grind=rare_candy.GRIND_MINUTES_MAX - 1) is None
    magikarp_only = [mon(0, "MAGIKARP", 9, ("SPLASH",))]
    assert candy(magikarp_only, (24, 9, 15)) is None
    with_trainee = [mon(0, "MAGIKARP", 9, ("SPLASH",)), mon(1, level=20)]
    assert candy(with_trainee, (24, 20, 4), grind=99)[1] == 1     # the real fighter, not the trainee in slot 0
    assert candy([mon(0, level=100)], (101, 100, 1)) is None


def test_steps_per_minute_matches_the_grind_atlas():
    from pokeagent.grind.atlas import STEPS_PER_MIN
    assert rare_candy.STEPS_PER_MIN == STEPS_PER_MIN


def test_atlas_minutes_picks_the_nearest_bucket_at_or_below():
    atlas = {"BULBASAUR": {"beat_brock": {"6": [{"steps_to_goal": 3600.0}], "9": [{"steps_to_goal": 1800.0}, {"steps_to_goal": 900.0}]}}}
    assert rare_candy.atlas_minutes(atlas, "BULBASAUR", "beat_brock", 10, 225.0) == 4.0   # bucket 9, best spot 900 steps / 225 per min
    assert rare_candy.atlas_minutes(atlas, "BULBASAUR", "beat_brock", 5, 225.0) is None
    assert rare_candy.atlas_minutes(atlas, "CHARMANDER", "beat_brock", 9, 225.0) is None


# --- 3. vitamins -------------------------------------------------------------------------------------------------------------
def test_vitamin_goes_to_the_fighter_at_once():
    assert vitamins.should_use(bag={ids.HP_UP: 1}, party=[mon(0)])[:2] == (ids.HP_UP, 0)
    party = [mon(0, "MAGIKARP", 9, ("SPLASH",)), mon(1, level=18)]
    assert vitamins.should_use(bag={ids.PROTEIN: 1}, party=party)[:2] == (ids.PROTEIN, 1)


def test_vitamin_shields():
    assert vitamins.should_use(bag={}, party=[mon(0)]) is None
    capped = mon(0, stat_exp=(vitamins.STAT_EXP_CAP, 0, 0, 0, 0))
    assert vitamins.should_use(bag={ids.HP_UP: 1}, party=[capped]) is None
    assert vitamins.should_use(bag={ids.HP_UP: 1, ids.IRON: 1}, party=[capped])[0] == ids.IRON   # HP is capped, DEFENSE is not
    assert vitamins.should_use(bag={ids.HP_UP: 1}, party=[mon(0, "MAGIKARP", 9, ("SPLASH",))]) is None


# --- 4. stones ---------------------------------------------------------------------------------------------------------------
EVO = {"PIKACHU": [("THUNDERSTONE", "RAICHU")], "EEVEE": [("FIRE STONE", "FLAREON"), ("WATER STONE", "VAPOREON")]}


def stone(party, bag, compare=lambda m, i: True, learns=lambda s, lv: [], needed=None):
    return stones.should_use(bag=bag, party=party, evolutions=EVO, needed=needed or {}, compare=compare, learns_at=learns)


def test_stone_evolves_when_not_worse():
    hit = stone([mon(0, "PIKACHU", moves=("THUNDERSHOCK",))], {ids.THUNDERSTONE: 1})
    assert hit and hit[:2] == (ids.THUNDERSTONE, 0)
    assert stone([mon(0, "PIKACHU")], {ids.FIRE_STONE: 1}) is None          # wrong stone
    assert stone([mon(0, "PIKACHU")], {}) is None


def test_stone_waits_when_the_evolved_form_is_worse_or_the_comparison_picks_another():
    assert stone([mon(0, "PIKACHU")], {ids.THUNDERSTONE: 1}, compare=lambda m, i: False) is None
    pick = stone([mon(0, "EEVEE")], {ids.FIRE_STONE: 1, ids.WATER_STONE: 1}, compare=lambda m, i: i == "VAPOREON")
    assert pick[0] == ids.WATER_STONE
    assert stone([mon(0, "PIKACHU")], {ids.THUNDERSTONE: 1}, compare=lambda m, i: None) is None   # cannot tell: wait


def test_stone_never_risks_a_needed_move_to_a_forget_prompt():
    party = [mon(0, "PIKACHU", moves=("THUNDER WAVE", "CUT", "GROWL", "TACKLE"))]
    assert stone(party, {ids.THUNDERSTONE: 1}, learns=lambda s, lv: ["THUNDERBOLT"], needed={0: {"CUT"}}) is None
    assert stone(party, {ids.THUNDERSTONE: 1}, learns=lambda s, lv: [], needed={0: {"CUT"}})              # nothing new to learn: safe
    short = [mon(0, "PIKACHU", moves=("CUT", "GROWL"))]
    assert stone(short, {ids.THUNDERSTONE: 1}, learns=lambda s, lv: ["THUNDERBOLT"], needed={0: {"CUT"}})   # a free slot: no prompt
    assert stone([mon(0, "MAGIKARP", 9, ("SPLASH",))], {ids.THUNDERSTONE: 1}) is None


# --- 5. HMs / TMs ------------------------------------------------------------------------------------------------------------
LEARNERS = {"cut": frozenset({"IVYSAUR", "BULBASAUR"}), "flash": frozenset({"IVYSAUR"}), "surf": frozenset({"SQUIRTLE"})}


def plan(party, bag=None, needs=("cut",), boss_types=(("ROCK", "GROUND"),)):
    return hm_teach.plan_hm(bag=bag or {ids.HM01: 1}, party=party, needs=list(needs), learners=LEARNERS, boss_types=list(boss_types), info=info, chart=CHART)


def test_hm_taught_when_needed_learnable_and_nobody_knows_it():
    p = plan([mon(0, "SQUIRTLE", moves=("TACKLE",)), mon(1, moves=("TACKLE", "TAIL WHIP", "VINE WHIP", "GROWL"))])
    assert p and p.item == ids.HM01 and p.learner == 1 and p.move == "CUT"
    assert p.forget_move in ("TAIL WHIP", "GROWL") and p.forget_slot in (1, 3)    # a status move goes first, never VINE WHIP
    assert hm_teach.should_use(bag={ids.HM01: 1}, party=[mon(0)], needs=["cut"], learners=LEARNERS, boss_types=[], info=info, chart=CHART)[:2] == (ids.HM01, 0)


def test_hm_not_taught_without_need_item_learner_or_when_known():
    two = [mon(0)]
    assert plan(two, needs=("surf",)) is None                                    # IVYSAUR cannot learn SURF
    assert plan(two, needs=("flash",), bag={ids.HM01: 1}) is None                # no HM05 in the bag
    assert plan(two, needs=()) is None                                            # the campaign does not need it
    assert plan([mon(0, moves=("CUT", "GROWL", "TACKLE", "VINE WHIP"))]) is None  # somebody already knows CUT
    assert plan([mon(0, "SQUIRTLE")]) is None                                      # nobody can learn it


def test_hm_learner_prefers_a_free_slot_then_a_non_fighter():
    free = mon(1, "BULBASAUR", moves=("TACKLE", "GROWL"))
    full = mon(0, "IVYSAUR", moves=("TACKLE", "TAIL WHIP", "VINE WHIP", "GROWL"))
    p = plan([full, free])
    assert p.learner == 1 and p.forget_slot is None and p.forget_move is None   # the free slot wins
    p = plan([full, mon(1, "BULBASAUR", moves=("TACKLE", "TAIL WHIP", "VINE WHIP", "GROWL"))])
    assert p.learner == 1                                                        # same cost: not the fighter (slot 0)


def test_overwrite_shield_keeps_needed_hms_and_the_only_damaging_move_of_the_best_type():
    moves = ("CUT", "FLASH", "VINE WHIP", "GROWL")
    prot = protected_moves(moves, {"CUT", "FLASH"}, [("ROCK", "GROUND")], info, CHART)
    assert prot == {"CUT", "FLASH", "VINE WHIP"}                                # VINE WHIP: GRASS hits ROCK hard and it is the only grass move
    assert choose_overwrite(moves, prot, info) == 3                              # GROWL
    assert choose_overwrite(moves, set(moves), info) is None                     # everything protected: no overwrite
    # two damaging moves of the best type: neither is 'the only' one
    water = ("WATER GUN", "BUBBLE", "TACKLE", "TAIL WHIP")
    assert "WATER GUN" not in protected_moves(water, set(), [("ROCK",)], info, CHART)
    assert choose_overwrite(water, protected_moves(water, set(), [("ROCK",)], info, CHART), info) == 3   # the status move first


def test_hm_skips_a_learner_whose_every_move_is_protected():
    locked = mon(0, moves=("CUT", "FLASH", "SURF", "VINE WHIP"))                  # a needed HM x3 + the only grass move
    assert hm_teach.plan_hm(bag={ids.HM01 + 4: 1}, party=[locked], needs=["flash", "cut", "surf"], learners={"flash": frozenset({"IVYSAUR"})},
                            boss_types=[("ROCK",)], info=info, chart=CHART) is None   # FLASH is known by this very mon


def test_tms_are_off_unless_flagged_and_need_compatibility():
    party = [mon(0, moves=("TACKLE", "TAIL WHIP", "GROWL", "VINE WHIP"))]
    kw = dict(bag={ids.TM01 + 11: 1}, party=party, needed_hm_moves=set(), boss_types=[], info=info, chart=CHART)   # TM12 = WATER GUN
    assert hm_teach.plan_tm(enabled=False, can_learn=lambda n, s: True, **kw) is None
    assert hm_teach.plan_tm(enabled=True, can_learn=lambda n, s: False, **kw) is None
    p = hm_teach.plan_tm(enabled=True, can_learn=lambda n, s: True, **kw)
    assert p and p.move == "WATER GUN" and p.forget_move in ("TAIL WHIP", "GROWL")
    assert policy.tm_can_learn(12, "IVYSAUR") is False                           # no compatibility table yet: the policy never teaches a TM


# --- 5b. the teach screens (as the ROM printed them) --------------------------------------------------------------------------
PLAN = hm_teach.HmPlan(ids.HM01, "cut", "CUT", learner=1, forget_slot=1, forget_move="TAIL WHIP", reason="x")
MOVES_NOW = ("TACKLE", "TAIL WHIP", "BUBBLE", "WATER GUN")
PARTY = ["MAGIKARP 9", "NOT ABLE", "WARTORTLE 22", "ABLE"]
LIST = ["TACKLE", "TAIL WHIP", "BUBBLE", "WATER GUN", "Which move should", "be forgotten?"]


def press(lines, cursor=0, state=None):
    return teach_press(lines, cursor, PLAN, MOVES_NOW, state if state is not None else {})


def test_teach_yes_on_teach_and_delete_prompts():
    assert press(["HM01 >YES", "CANCEL NO", "Teach CUT", "to a POKeMON?"])[0] == "A"
    assert press(["HM01 YES", "CANCEL >NO", "Teach CUT", "to a POKeMON?"])[0] == "UP"
    assert press(PARTY + [">YES", "NO", "move to make room", "for CUT?"])[0] == "A"
    assert press(PARTY + ["YES", ">NO", "move to make room", "for CUT?"])[0] == "UP"


def test_abandon_is_answered_no_unless_the_flow_was_aborted():
    yes_on = PARTY + [">YES", "NO", "Abandon learning", "CUT?"]
    assert press(yes_on)[:2] == ("DOWN", "teach_yesno_cursor")                   # YES would cancel into 'didn't learn'
    assert press(PARTY + ["YES", ">NO", "Abandon learning", "CUT?"])[0] == "A"   # NO, then A: back to the move list
    assert press(yes_on, state={"abort": True})[0] == "A"                        # a deliberate abort may abandon


def test_forget_slot_is_confirmed_only_on_the_planned_row_and_cursor():
    assert press([">TACKLE", *LIST[1:]], cursor=0)[:2] == ("DOWN", "teach_forget_cursor")
    assert press(["TACKLE", ">TAIL WHIP", *LIST[2:]], cursor=1)[:2] == ("A", "teach_forget_confirm")
    wrong_row = press(["TACKLE", "TAIL WHIP", ">BUBBLE", *LIST[3:]], cursor=2)
    assert wrong_row[0] in ("UP", "DOWN") and wrong_row[1] == "teach_forget_cursor"   # never A on the wrong row
    assert press(["TACKLE", "TAIL WHIP", "BUBBLE", ">WATER GUN", *LIST[4:]], cursor=3)[0] == "UP"


def test_a_forget_list_that_does_not_match_aborts_instead_of_forgetting():
    state: dict = {}
    other = ("TACKLE", "GROWL", "BUBBLE", "WATER GUN")      # the planned TAIL WHIP is not there
    out = teach_press(["TACKLE", ">GROWL", "BUBBLE", "WATER GUN"], 1, PLAN, other, state)
    assert out[0] == "B" and state["abort"]
    state = {}
    out = teach_press(["TACKLE", ">TAIL WHIP", "BUBBLE", "WATER GUN"], 1, PLAN, MOVES_NOW, state)
    assert out[0] == "A"                                      # cursor row and RAM slot both say TAIL WHIP
    out = teach_press(["TACKLE", "TAIL WHIP", ">BUBBLE", "WATER GUN"], 1, PLAN, MOVES_NOW, state={})   # RAM says slot 1, the row says BUBBLE
    assert out[0] == "B"


def test_not_able_learner_aborts_before_anything_is_confirmed():
    state: dict = {}
    plan0 = hm_teach.HmPlan(ids.HM01, "cut", "CUT", 0, None, None, "x")
    out = teach_press(["MAGIKARP 9", "> NOT ABLE", "WARTORTLE 22", "ABLE", "Use TM on which", "POKeMON?"], 0, plan0, (), state)
    assert out[0] == "B" and state["abort"]
    assert press(["MAGIKARP 9", "NOT ABLE", "WARTORTLE 22", "> ABLE", "Use TM on which", "POKeMON?"], cursor=1)[:2] == ("A", "teach_pick_learner")
    assert press(["MAGIKARP 9", "> NOT ABLE", "WARTORTLE 22", "ABLE", "Use TM on which", "POKeMON?"], cursor=0)[:2] == ("DOWN", "teach_pick_learner")


def test_teach_dialog_advances_and_other_screens_are_not_ours():
    assert press(["MOON STONE", "x 1", "HM01", "CANCEL", "USE", "Booted up an HM!"])[0] == "A"
    assert press(PARTY + ["WARTORTLE forgot", "TACKLE!"])[0] == "A"
    assert press(["HP UP", "x 1", "ESCAPE ROPE", "x 1", ">RARE CANDY", "x 1", "EXIT"]) is None


# --- 6. repel ---------------------------------------------------------------------------------------------------------------
def repel_pick(**kw):
    base = dict(bag={ids.REPEL: 2}, trip="goal", ready=True, training=False, active_steps=0, has_trainee=False, battle=False)
    return repel.should_use(**{**base, **kw})


def test_repel_on_a_ready_travel_leg_only():
    assert repel_pick()[0] == ids.REPEL
    assert repel_pick(bag={ids.REPEL: 1, ids.MAX_REPEL: 1})[0] == ids.REPEL      # the cheapest first
    assert repel_pick(trip="heal") is None and repel_pick(trip=None) is None and repel_pick(trip="mart") is None
    assert repel_pick(ready=False) is None
    assert repel_pick(training=True) is None                                     # never while grinding
    assert repel_pick(has_trainee=True) is None and repel_pick(active_steps=40) is None and repel_pick(battle=True) is None
    assert repel_pick(bag={}) is None


# --- 7. X items -------------------------------------------------------------------------------------------------------------
def x_pick(**kw):
    base = dict(kind=2, bag={ids.X_ATTACK: 1, ids.X_SPECIAL: 1}, score=0.2, used_this_battle=0, magikarp_out=False, physical=True)
    return xitems.should_use(**{**base, **kw})


def test_x_item_only_in_trainer_battles_with_a_thin_margin_once():
    assert x_pick()[0] == ids.X_ATTACK and x_pick(physical=False)[0] == ids.X_SPECIAL
    assert x_pick(kind=1) is None                                                # wild
    assert x_pick(score=0.9) is None and x_pick(score=-0.8) is None and x_pick(score=None) is None
    assert x_pick(used_this_battle=1) is None                                    # one per battle
    assert x_pick(magikarp_out=True) is None and x_pick(physical=None) is None
    assert x_pick(bag={ids.X_SPECIAL: 1}) is None                                # the wanted one is not held


# --- 8. use_items is a no-op in battle and in menus -------------------------------------------------------------------------
def ctx_with_vitamin(tmp_path, battle=False):
    mem = {0xD31D: 1, 0xD31E: ids.HP_UP, 0xD31F: 2, 0xD320: 0xFF, 0xD163: 1, 0xD164: 0x99, 0xD16B: 0x99, 0xD16C: 0, 0xD16D: 40,
           0xD18C: 12, 0xD18D: 0, 0xD18E: 40}
    if battle:
        mem[BATTLE] = 1
    ctx = make_ctx(tmp_path, memory=mem)
    ctx.refresh()
    return ctx


def test_use_items_is_in_the_default_behaviours_after_heal_and_restock():
    names = [(b.name, getattr(b, "active_only", None)) for b in default_behaviours()]
    assert ("use_items", True) in names and ("use_items", False) in names
    order = [n for n, _ in names]
    assert order.index("restock") < len(order) - 1 - order[::-1].index("use_items") < order.index("explore_burst")
    assert order.index("cave_topup") < order.index("use_items") < order.index("menu")   # the active_only slot owns the screen before Menu


def test_use_items_does_nothing_in_battle(tmp_path):
    ctx = ctx_with_vitamin(tmp_path, battle=True)
    assert ctx.view.battling
    ctx.item_seq = {"stale": True}
    for b in (UseItems(), UseItems(active_only=True)):
        assert not b.applies(ctx)
    assert ctx.item_seq is None                                               # a leftover sequence is dropped when a fight starts


def test_use_items_does_nothing_inside_a_menu_or_dialog(tmp_path):
    ctx = ctx_with_vitamin(tmp_path)
    put_box(ctx, menu=True)
    ctx.refresh()
    assert ctx.view.box
    assert not UseItems().applies(ctx) and not UseItems(active_only=True).applies(ctx)


def test_use_items_idle_start_needs_a_calm_overworld_and_a_candidate(tmp_path):
    ctx = ctx_with_vitamin(tmp_path)
    assert UseItems().applies(ctx) and not UseItems(active_only=True).applies(ctx)   # only the plain slot may start a sequence
    ctx.stable_frames = 2
    assert not UseItems().applies(ctx)                                        # the screen has not settled
    ctx.stable_frames = 10
    ctx.emu.set(0xD31E, 0x14)                                                  # a POTION: not an item-policy item
    assert not UseItems().applies(ctx)
    ctx.emu.set(0xD31E, ids.HP_UP)
    ctx.item_next_check = ctx.step + 5
    assert not UseItems().applies(ctx)                                        # throttled


# --- 9. the ledger ----------------------------------------------------------------------------------------------------------
def test_ledger_records_category_reason_and_before_after(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.refresh()
    ledger.of(ctx).item_use(ctx, ids.RARE_CANDY, "rare_candy", "gap 2", "use_items", {"level": 22, "hp": 60}, {"level": 23, "hp": 64})
    use = ledger.of(ctx).summary()["uses"][-1]
    assert (use["item"], use["category"], use["why"]) == (ids.RARE_CANDY, "rare_candy", "gap 2")
    assert use["before"]["level"] == 22 and use["after"]["level"] == 23 and use["hp_after"] == 64


def test_fighter_slot_follows_the_trainee_rule():
    assert fighter_slot_of([mon(0), mon(1)]) == 0
    assert fighter_slot_of([mon(0, "MAGIKARP", 9, ()), mon(1, level=5), mon(2, level=15)]) == 2
    assert fighter_slot_of([mon(0, "MAGIKARP", 9, ())]) is None
    assert fighter_slot_of([]) is None


# --- 10. end-to-end UseItems.step: the teach cap and the stone settle -----------------------------------------------------------
from pokeagent.explorer.behaviours import use_items as ui   # noqa: E402
from pokeagent.explorer.dialog import learn_decision   # noqa: E402
from test_toss_guard import draw, new_ctx   # noqa: E402

TEACH_MONS = [Mon(0, "MAGIKARP", 9, ("SPLASH",), 24, 24), Mon(1, "IVYSAUR", 22, MOVES_NOW, 60, 60)]
TEACH_PICK = policy.Pick(ids.HM01, "hm", 1, "x", "teach", PLAN)


def teach_ctx(tmp_path, monkeypatch, rows, cursor=0, presses=0, mons=TEACH_MONS):
    ctx = new_ctx(tmp_path)
    monkeypatch.setattr(ui, "read_mons", lambda emu: mons)
    monkeypatch.setattr("pokeagent.explorer.item_policies.uselog.read_mons", lambda emu: mons)
    draw(ctx, rows)
    ctx.emu.set(0xCC26, cursor)
    ctx.refresh()
    ctx.item_seq = {"pick": TEACH_PICK, "presses": presses, "phase": "use", "state": {"inside": True}, "closing": 0, "ok": None,
                    "before": {"bag": 1, "species": "IVYSAUR"}, "dec_at": None}
    return ctx


def test_the_press_cap_on_the_delete_prompt_answers_it_here_and_never_hands_it_to_menu(tmp_path, monkeypatch):
    delete = [*PARTY, ">YES", "NO", "move to make room", "for CUT?"]
    ctx = teach_ctx(tmp_path, monkeypatch, delete, presses=ui.MAX_PRESSES["teach"] + 1)
    b = UseItems(active_only=True)
    d = b.step(ctx)
    assert (d.button, d.rule) == ("DOWN", "teach_yesno_cursor")           # NO on 'Delete an older move', never YES
    assert ctx.item_seq is not None and ctx.item_seq["state"]["abort"]    # still ours: Menu / learn_decision never sees the prompt
    assert ctx.item_cooldown[ids.HM01] > ctx.step
    draw(ctx, [*PARTY, "YES", ">NO", "move to make room", "for CUT?"]); ctx.refresh()
    assert b.step(ctx).button == "A"
    draw(ctx, [*PARTY, ">YES", "NO", "Abandon learning", "CUT?"]); ctx.refresh()
    d = b.step(ctx)
    assert d.button == "A" and ctx.item_seq is not None                    # a deliberate abort may abandon
    for i in range(360):
        ctx.emu.set(TM + i, 0x7F)
    ctx.refresh()
    assert b.step(ctx) is None and ctx.item_seq is None                    # screen clear: released


def test_the_wait_cap_aborts_the_same_way(tmp_path, monkeypatch):
    ctx = teach_ctx(tmp_path, monkeypatch, [*PARTY, ">YES", "NO", "move to make room", "for CUT?"])
    ctx.item_seq["state"]["waits"] = ui.TEACH_MAX_WAITS
    draw(ctx, ["MAGIKARP 9", "WARTORTLE 22", "ABLE"]); ctx.refresh()          # an unrecognised screen
    UseItems(active_only=True).step(ctx)
    assert ctx.item_seq["state"]["abort"]


def test_abort_answers_no_to_teach_and_never_confirms_the_move_list():
    st = {"abort": True}
    assert teach_press(["HM01 >YES", "CANCEL NO", "Teach CUT", "to a POKeMON?"], 0, PLAN, MOVES_NOW, st)[:2] == ("DOWN", "teach_yesno_cursor")
    assert teach_press(["TACKLE", ">TAIL WHIP", "BUBBLE", "WATER GUN"], 1, PLAN, MOVES_NOW, st)[0] == "B"


STONE_MONS = [Mon(0, "PIKACHU", 22, ("THUNDERSHOCK",), 50, 50)]


def test_stone_settle_presses_nothing_until_the_species_changes(tmp_path, monkeypatch):
    ctx = teach_ctx(tmp_path, monkeypatch, ["What? PIKACHU", "is evolving!"], mons=STONE_MONS)   # bag memory is empty: the stone is gone
    ctx.item_seq = {"pick": policy.Pick(ids.THUNDERSTONE, "stone", 0, "x", "party"), "presses": 3, "phase": "use", "state": {}, "closing": 0,
                    "ok": None, "before": {"bag": 1, "species": "PIKACHU"}, "dec_at": None}
    b = UseItems(active_only=True)
    for _ in range(5):
        d = b.step(ctx)
        assert d.button == "" and d.rule == "stone_settle"                 # no START / B from the rope driver
    evolved = [Mon(0, "RAICHU", 22, ("THUNDERSHOCK",), 50, 50)]
    monkeypatch.setattr(ui, "read_mons", lambda emu: evolved)
    monkeypatch.setattr("pokeagent.explorer.item_policies.uselog.read_mons", lambda emu: evolved)
    b.step(ctx)
    assert ctx.item_seq["ok"] is True and ledger.of(ctx).uses[-1]["category"] == "stone"


def test_stone_settle_gives_up_after_the_settle_window(tmp_path, monkeypatch):
    ctx = teach_ctx(tmp_path, monkeypatch, [], mons=STONE_MONS)
    ctx.item_seq = {"pick": policy.Pick(ids.THUNDERSTONE, "stone", 0, "x", "party"), "presses": 3, "phase": "use", "state": {}, "closing": 0,
                    "ok": None, "before": {"bag": 1, "species": "PIKACHU"}, "dec_at": None}
    b = UseItems(active_only=True)
    for _ in range(ui.STONE_SETTLE + 3):
        b.step(ctx)
    assert ctx.item_seq["ok"] is False and ids.THUNDERSTONE in ctx.item_cooldown


def test_bicycle_gets_a_cooldown_after_mounting(tmp_path, monkeypatch):
    ctx = teach_ctx(tmp_path, monkeypatch, [], mons=STONE_MONS)
    ctx.emu.set(key_items.WALK_BIKE_SURF_STATE, key_items.BIKE)
    ctx.item_seq = {"pick": policy.Pick(ids.BICYCLE, "key_item", None, "x", "self"), "presses": 2, "phase": "use", "state": {}, "closing": 0,
                    "ok": None, "before": {"bag": 1}, "dec_at": None}
    UseItems(active_only=True).step(ctx)
    assert ctx.item_cooldown[ids.BICYCLE] >= ctx.step + ui.BIKE_COOLDOWN


# --- 11. level-up move prompts never forget a needed move ---------------------------------------------------------------------
def test_learn_decision_never_forgets_a_protected_move(monkeypatch):
    values = {"CUT": 30.0, "TACKLE": 35.0, "GROWL": 0.0, "THUNDERBOLT": 90.0, "SURF": 95.0}
    monkeypatch.setattr("pokeagent.explorer.dialog.move_value", lambda n: values[n])
    q = "X is trying to LEARN THUNDERBOLT! Delete a move to make room"
    assert learn_decision(q, ["CUT", "TACKLE"])[2] == "CUT"                                      # unshielded: CUT is the weakest
    assert learn_decision(q, ["CUT", "TACKLE"], {"CUT"})[2] == "TACKLE"                          # shielded: the next weakest
    assert learn_decision(q, ["CUT", "SURF"], {"CUT", "SURF"})[:2][0] == "NO"                    # everything needed: decline
