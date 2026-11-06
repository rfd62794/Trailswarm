"""The Magikarp plan: the buy_magikarp goal, the salesman YES rule, reorder_party, the turn-one switch."""
from __future__ import annotations

import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.explorer.behaviours import PartyOrder, SwitchOut, default_behaviours
from pokeagent.explorer.behaviours.switch_out import run_press, switch_press
from pokeagent.explorer.context import ExplorerContext, ExplorerOptions
from pokeagent.explorer.dialog import magikarp_offer, yesno_answer
from pokeagent.explorer.memory import MapMemory
from pokeagent.explorer.party_menu import reorder_press
from pokeagent.explorer.planner import plan_step
from pokeagent.goals import GOALS, SIDE_GOALS, check_goals
from pokeagent.magikarp import GYARADOS, MAGIKARP, fighter, switch_candidate
from pokeagent.screentext import CHARMAP

TM, MAP, MONEY = 0xC3A0, 0xD35E, 0xD347
INVERSE = {v: k for k, v in CHARMAP.items() if len(v) == 1}
OFFER = "MAN Hello, there! Have I got a deal just for you! I will let you have a swell MAGIKARP for just 500! What do you say?"
STARTER = 0xB1


def party_mem(mons: list[tuple[int, int, int, int]]) -> dict[int, int]:
    """FakeEmulator memory for a party of (species, level, hp, max_hp)."""
    mem = {0xD163: len(mons)}
    for i, (sp, lvl, hp, mx) in enumerate(mons):
        base = 0xD16B + 44 * i
        mem[0xD164 + i] = sp
        mem.update({base: sp, base + 1: hp >> 8, base + 2: hp & 255, base + 33: lvl, base + 34: mx >> 8, base + 35: mx & 255})
    return mem


def bcd(n: int) -> dict[int, int]:
    d = f"{n:06d}"
    return {MONEY + i: (int(d[2 * i]) << 4) | int(d[2 * i + 1]) for i in range(3)}


def draw(emu: FakeEmulator, rows: list[str]) -> None:
    """Write text rows onto the tile map from row 0 (cursor '>' -> 0xED); blank everything else."""
    for i in range(360):
        emu.set(TM + i, 0x7F)
    for r, text in enumerate(rows):
        for c, ch in enumerate(text[:20]):
            emu.set(TM + 20 * r + c, INVERSE.get(ch, 0x7F))


def draw_framed(emu: FakeEmulator, rows: list[str]) -> None:
    """A bordered box (top edge 0x79 0x7A, rows between 0x7C edges) at tile row 12: the battle menu / START menu look."""
    draw(emu, [])
    emu.set(TM + 20 * 12, 0x79); emu.set(TM + 20 * 12 + 1, 0x7A)
    for r, text in enumerate(rows, start=13):
        emu.set(TM + 20 * r, 0x7C); emu.set(TM + 20 * r + 19, 0x7C)
        for c, ch in enumerate(text[:17]):
            emu.set(TM + 20 * r + 1 + c, INVERSE.get(ch, 0x7F))


# --- goals -------------------------------------------------------------------------------------------------------

def test_buy_magikarp_sits_before_mt_moon_and_gyarados_is_a_side_goal():
    assert GOALS.index("to_route4") < GOALS.index("buy_magikarp") < GOALS.index("to_mt_moon")
    assert SIDE_GOALS == ["gyarados"] and "gyarados" not in GOALS


def test_buy_magikarp_detector():
    rich = {**party_mem([(STARTER, 14, 30, 30)]), **bcd(3000), MAP: 0x0F}
    emu = FakeEmulator(rich)
    assert not check_goals(emu, {})["buy_magikarp"]  # affordable, room in the party, not owned: the goal is open
    emu.memory.update(bcd(499))
    assert check_goals(emu, {})["buy_magikarp"]  # cannot afford it: not a live option
    emu = FakeEmulator({**party_mem([(STARTER, 14, 30, 30)] * 6), **bcd(3000), MAP: 0x0F})
    assert check_goals(emu, {})["buy_magikarp"]  # no free slot
    emu = FakeEmulator({**rich, **party_mem([(STARTER, 14, 30, 30), (MAGIKARP, 5, 18, 18)])})
    st: dict = {}
    assert check_goals(emu, st)["buy_magikarp"]
    emu.memory.update(party_mem([(STARTER, 14, 30, 30), (GYARADOS, 20, 60, 60)]))
    g = check_goals(emu, st)
    assert g["buy_magikarp"] and g["gyarados"]  # evolved: still bought, side goal met
    assert check_goals(FakeEmulator({**rich, MAP: 0x3B}), {})["buy_magikarp"]  # Mt Moon 1F entered: the chance is gone


def test_gyarados_never_blocks_the_ladder():
    g = check_goals(FakeEmulator({**party_mem([(STARTER, 14, 30, 30)]), **bcd(3000)}), {})
    assert not g["gyarados"]
    assert next((k for k in GOALS if not g[k]), None) not in SIDE_GOALS


# --- the salesman's YES / the nickname NO ------------------------------------------------------------------------

def test_yes_only_for_the_magikarp_offer_at_500_while_wanted():
    assert magikarp_offer(OFFER)
    assert yesno_answer("for just 500! What do you say?", buy_magikarp=True, offer_text=OFFER)[0] == "YES"
    assert yesno_answer(OFFER, buy_magikarp=True)[0] == "YES"
    assert yesno_answer(OFFER, buy_magikarp=False)[0] == "NO"  # already own one / not wanted: never pay twice
    assert yesno_answer(OFFER.replace("500", "5000"), buy_magikarp=True)[0] == "NO"  # a different price is not the 500 offer


def test_nickname_prompt_is_no_and_not_an_offer():
    nick = "BCN got MAGIKARP! Do you want to give a nickname to MAGIKARP?"
    assert not magikarp_offer(nick)
    assert yesno_answer(nick, buy_magikarp=True, offer_text=OFFER + " " + nick)[0] == "NO"


def test_starter_offers_unchanged():
    assert yesno_answer("So! You want the fire POKeMON, CHARMANDER?", "charmander")[0] == "YES"
    assert yesno_answer("So! You want the fire POKeMON, CHARMANDER?", "squirtle")[0] == "NO"


# --- the planner: walk to the salesman, stay inside while buying ----------------------------------------------------

def center_maps(tmp_path):
    mem = MapMemory(tmp_path / "maps.json")
    for x in range(1, 12):
        mem.m(0x44)["visited"][f"{x},5"] = 1
    mem.m(0x44)["visited"]["3,7"] = mem.m(0x44)["visited"]["3,6"] = 1
    mem.m(0x44).setdefault("npcs", {})["slot4:pic10"] = {"pic": 10, "positions": {"9,6": 3, "10,6": 3}, "moves": True, "last": [10, 6],
                                           "text": "MAN H", "results": {"text": "a swell MAGIKARP for just 500!"}}
    return mem.data["maps"]


def buying_goals(**extra) -> dict:
    goals = {g: True for g in GOALS[:GOALS.index("to_route4") + 1]}
    goals.update({"buy_magikarp": False, "_hp": (40, 40), "_level": 20, "_train_level": 8, "_sprites": [(10, 10, 6), (41, 3, 1)],
                  "_center_intent": "buy_magikarp", **extra})
    return goals


def test_planner_routes_to_the_salesman_and_talks(tmp_path):
    maps = center_maps(tmp_path)
    step = plan_step(buying_goals(), maps, (0x44, 5, 5), "RIGHT")
    assert step[0] == "RIGHT" and "salesman" in step[1]
    assert plan_step(buying_goals(), maps, (0x44, 10, 5), "RIGHT") == ("DOWN", "goal buy_magikarp: at the salesman (10,6), facing him")
    assert plan_step(buying_goals(), maps, (0x44, 10, 5), "DOWN")[1].endswith("talking")


def test_planner_will_not_leave_the_center_while_buying(tmp_path):
    maps = center_maps(tmp_path)
    assert plan_step(buying_goals(_sprites=[]), maps, (0x44, 5, 5), "UP") is None  # salesman not in view: exploration, not the door
    done = buying_goals(buy_magikarp=True, _center_intent=None)
    assert plan_step(done, maps, (0x44, 3, 5), "UP")[1].startswith("goal to_mt_moon: walking out")  # bought: leave


# --- reorder_party on a fake menu --------------------------------------------------------------------------------

def test_reorder_party_walks_start_member_switch_target():
    start = ["POKéDEX", "POKéMON", "ITEM", "BCN", "SAVE", "OPTION", "EXIT"]
    assert reorder_press(["hello"], [], 0, 1, 0) is None  # overworld: the caller presses START
    assert reorder_press(start, start, 0, 1, 0) == "DOWN"  # cursor on POKeDEX, POKeMON is the next row
    assert reorder_press(start, start, 1, 1, 0) == "A"
    lst = ["WARTORTLE 18", "51/ 51", "MAGIKARP 5", "17/ 17", "Choose a POKéMON."]
    assert reorder_press(lst, [], 0, 1, 0) == "DOWN" and reorder_press(lst, [], 1, 1, 0) == "A"
    sub_menu = lst[:-1] + [">STATS", "Choose a P SWITCH", "CANCEL"]  # SWITCH is item 1 of STATS / SWITCH / CANCEL
    assert reorder_press(sub_menu, [], 0, 1, 0) == "DOWN" and reorder_press(sub_menu, [], 1, 1, 0) == "A"
    where = lst[:-1] + ["Move POKéMON", "where?"]  # the cursor sits on the Magikarp (1); the target is slot 0
    assert reorder_press(where, [], 1, 1, 0) == "UP" and reorder_press(where, [], 0, 1, 0) == "A"


def party_ctx(tmp_path, mons) -> ExplorerContext:
    emu = FakeEmulator({MAP: 0x44, 0xD362: 5, 0xD361: 5, **party_mem(mons)})
    ctx = ExplorerContext(emu=emu, mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path, stable_frames=20)
    ctx.refresh()
    return ctx


def test_party_order_triggers_only_when_the_magikarp_is_not_first(tmp_path):
    ctx = party_ctx(tmp_path, [(STARTER, 18, 51, 51), (MAGIKARP, 5, 17, 17)])
    assert PartyOrder().applies(ctx)
    assert not PartyOrder().applies(party_ctx(tmp_path, [(MAGIKARP, 5, 17, 17), (STARTER, 18, 51, 51)]))
    assert not PartyOrder().applies(party_ctx(tmp_path, [(STARTER, 18, 51, 51)]))
    ctx.order_retry_at = 999
    assert not PartyOrder().applies(ctx)  # an abandoned attempt waits


def test_party_order_presses_start_then_follows_the_screens(tmp_path):
    ctx = party_ctx(tmp_path, [(STARTER, 18, 51, 51), (MAGIKARP, 5, 17, 17)])
    po = PartyOrder()
    d = po.step(ctx)
    assert d.button == "START" and d.rule.startswith("reorder_party: ['MAGIKARP'")
    ctx.party_order["wait"] = 0
    draw(ctx.emu, ["WARTORTLE 18", "51/ 51", "MAGIKARP 5", "17/ 17", "Choose a POKéMON."])
    ctx.emu.set(0xCC26, 0)
    assert po.step(ctx).button == "DOWN"
    ctx.party_order["wait"] = 0
    ctx.emu.set(0xCC26, 1)
    assert po.step(ctx).button == "A"


def test_party_order_gives_up_after_too_many_presses(tmp_path):
    ctx = party_ctx(tmp_path, [(STARTER, 18, 51, 51), (MAGIKARP, 5, 17, 17)])
    ctx.party_order = {"src": 1, "presses": 40, "wait": 0}
    d = PartyOrder().step(ctx)
    assert d.rule == "reorder_party_failed" and ctx.party_order is None and ctx.order_retry_at > ctx.step


def test_party_order_stops_once_first(tmp_path):
    ctx = party_ctx(tmp_path, [(MAGIKARP, 5, 17, 17), (STARTER, 18, 51, 51)])
    ctx.party_order = {"src": 1, "presses": 9, "wait": 0}
    draw(ctx.emu, ["MAGIKARP 5", "17/ 17", "WARTORTLE 18", "51/ 51", "Choose a POKéMON."])
    assert PartyOrder().step(ctx).button == "B"  # still on the party screen: close it
    draw(ctx.emu, [])
    ctx.party_order["wait"] = 0
    assert PartyOrder().step(ctx).button == "" and ctx.party_order is None


# --- the turn-one switch ----------------------------------------------------------------------------------------

def test_switch_candidate_excludes_fainted_low_hp_and_the_trainee():
    emu = FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (0x99, 12, 0, 40), (0x54, 9, 9, 40), (STARTER, 14, 30, 40)]))
    assert switch_candidate(emu) == 3  # fainted (slot 1) and 22% HP (slot 2) are out; the Magikarp never is
    assert switch_candidate(FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (0x99, 12, 0, 40), (0x54, 9, 9, 40)]))) is None
    assert switch_candidate(FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (0x99, 12, 10, 40), (0x54, 9, 40, 40)]))) == 1  # 25% allowed; higher level wins


def test_fighter_is_the_active_mon_not_the_magikarp_lead():
    emu = FakeEmulator(party_mem([(MAGIKARP, 5, 17, 17), (STARTER, 18, 30, 51)]))
    assert fighter(emu) == (STARTER, 18, 30, 51)  # out of battle: the strongest non-Magikarp
    plain = FakeEmulator(party_mem([(STARTER, 18, 30, 51), (0x54, 9, 9, 40)]))
    assert fighter(plain) == (STARTER, 18, 30, 51)  # no Magikarp: the old lead rule, unchanged


def test_switch_press_battle_menu_party_list_and_switch_item():
    assert switch_press([">FIGHT PKMN", "ITEM RUN"], [">FIGHT PKMN", "ITEM RUN"], 0, 1) == "RIGHT"
    assert switch_press(["FIGHT>PKMN", "ITEM RUN"], ["FIGHT>PKMN", "ITEM RUN"], 0, 1) == "A"
    assert switch_press(["FIGHT PKMN", ">ITEM RUN"], ["FIGHT PKMN", ">ITEM RUN"], 0, 1) == "UP"
    lst = ["MAGIKARP 5", "17/ 17", "WARTORTLE 18", "51/ 51", "Choose a POKéMON."]
    assert switch_press([], lst, 0, 1) == "DOWN" and switch_press([], lst, 1, 1) == "A"
    sub_menu = [">SWITCH", "STATS", "CANCEL"]  # in a fight SWITCH is the first item
    assert switch_press(sub_menu, ["Choose a P " + ln for ln in sub_menu], 0, 1) == "A"
    assert switch_press([], ["Wild ZUBAT", "appeared!"], 0, 1) is None  # text scrolling: not ours


def battle_ctx(tmp_path, mons, battle_species=MAGIKARP, kind=1, bv=True) -> ExplorerContext:
    mem = {**party_mem(mons), 0xD057: kind, 0xD014: battle_species, 0xD016: 17, 0xD022: 5, 0xD024: 17}
    ctx = ExplorerContext(emu=FakeEmulator(mem), mem=MapMemory(tmp_path / "maps.json"), opts=ExplorerOptions(), run_dir=tmp_path,
                          stable_frames=20, battles=1)
    ctx.refresh()
    ctx.bv = object() if bv else None
    return ctx


@pytest.mark.parametrize("kind", [1, 2])  # wild and trainer
def test_switch_out_applies_for_the_magikarp_in_both_fight_kinds(tmp_path, kind):
    assert SwitchOut().applies(battle_ctx(tmp_path, [(MAGIKARP, 5, 17, 17), (STARTER, 18, 51, 51)], kind=kind))


def test_switch_out_not_for_other_leads_gave_up_or_flee(tmp_path):
    assert not SwitchOut().applies(battle_ctx(tmp_path, [(STARTER, 18, 51, 51), (MAGIKARP, 5, 17, 17)], battle_species=STARTER))
    gave_up = battle_ctx(tmp_path, [(MAGIKARP, 5, 17, 17), (STARTER, 18, 51, 51)])
    gave_up.switch_gave_up = 1
    assert not SwitchOut().applies(gave_up)
    fled = battle_ctx(tmp_path, [(MAGIKARP, 5, 17, 17), (STARTER, 18, 51, 51)], bv=False)
    assert not SwitchOut().applies(fled)  # the battle behaviour answered (flee) and left no BattleView: no switch
    names = [b.name for b in default_behaviours()]
    assert names.index("battle") < names.index("switch_out") < names.index("catch")  # flee decisions are made first


def test_run_press_walks_the_cursor_to_run():
    assert run_press([">FIGHT PKMN", "ITEM RUN"]) == "DOWN" and run_press(["FIGHT PKMN", ">ITEM RUN"]) == "RIGHT"
    assert run_press(["FIGHT>PKMN", "ITEM RUN"]) == "DOWN" and run_press(["FIGHT PKMN", "ITEM>RUN"]) == "A"
    assert run_press(["Wild ZUBAT"]) is None


def test_switch_out_nobody_fit_runs_from_wild_and_fights_on_in_trainer_battles(tmp_path):
    mons = [(MAGIKARP, 5, 17, 17), (STARTER, 18, 0, 51)]
    wild = battle_ctx(tmp_path, mons, kind=1)
    draw_framed(wild.emu, [">FIGHT PKMN", "ITEM RUN"])
    d = SwitchOut().step(wild)
    assert d.button == "DOWN" and d.rule == "switch_train_run"
    draw_framed(wild.emu, ["FIGHT PKMN", "ITEM>RUN"])
    assert SwitchOut().step(wild).button == "A"
    trainer = battle_ctx(tmp_path, mons, kind=2)
    draw_framed(trainer.emu, [">FIGHT PKMN", "ITEM RUN"])
    assert SwitchOut().step(trainer) is None and trainer.switch_gave_up == 1


def test_switch_out_names_the_swap_and_counts_it(tmp_path):
    ctx = battle_ctx(tmp_path, [(MAGIKARP, 5, 17, 17), (STARTER, 18, 51, 51)])
    draw_framed(ctx.emu, [">FIGHT PKMN", "ITEM RUN"])
    d = SwitchOut().step(ctx)
    assert d.button == "RIGHT" and d.rule.startswith("switch_train: MAGIKARP L5 -> out, ")
    ctx.emu.set(0xD014, STARTER)  # the swap landed: the battle mon is no longer the Magikarp
    assert SwitchOut().step(ctx) is None and ctx.magikarp_shared == 1 and ctx.switch_train is None
