"""Macros over scripted fake screens: the happy path, the verification before each press, and 'unexpected screen -> stop'."""
import pytest

from pokeagent.emulator import FakeEmulator
from pokeagent.intervene import macros_battle
from pokeagent.intervene.macros import macro_names, run_macro
from pokeagent.intervene.screen import ScreenRead, main_cursor, main_menu, toward_main
from pokeagent.ramstructs import BAG_COUNT, PARTY_COUNT

MENU_ITEM, PLAYER_MON = 0xCC26, 0xCC2F
RUN, ITEM, FIGHT = 0xD057, 0, 0


def scr(frames=(), *, battle=True, menu=False, cur=0, screen=None, box=None):
    frames = list(frames)
    return ScreenRead(in_battle=battle, box=bool(frames) if box is None else box, menu=menu, frames=frames,
                      screen=list(screen if screen is not None else frames), cur=cur)


def battle_menu(at: str) -> ScreenRead:
    row1 = [">FIGHT" if at == "FIGHT" else "FIGHT", ">PKMN" if at == "PKMN" else "PKMN"]
    row2 = [">ITEM" if at == "ITEM" else "ITEM", ">RUN" if at == "RUN" else "RUN"]
    return scr([" ".join(row1), " ".join(row2)], menu=True)


class Rig:
    """Scripted rig: `screens` is the sequence of screens; every press moves to the next one. `after` mutates RAM at a press count."""

    def __init__(self, screens, emu=None, after=None):
        self.screens, self.i, self.emu = list(screens), 0, emu or FakeEmulator()
        self.pressed, self.ticks, self.after = [], [], after or {}
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.screens[min(self.i, len(self.screens) - 1)]

    def press(self, button, why):
        self.pressed.append(button)
        self.i += 1
        if len(self.pressed) in self.after:
            self.after[len(self.pressed)](self.emu)

    def tick(self, frames):
        self.ticks.append(frames)

    def goto_decision(self, target):
        return ("press", "UP") if len(self.pressed) < 3 else ("arrived", "")


def test_screen_helpers():
    assert main_menu(battle_menu("RUN").frames) and not main_menu(["TACKLE", "GROWL"])
    assert main_cursor(battle_menu("ITEM").frames) == "ITEM" and main_cursor(["FIGHT PKMN", "ITEM RUN"]) is None
    assert toward_main("FIGHT", "RUN") == "RIGHT" and toward_main("PKMN", "RUN") == "DOWN"
    assert toward_main("RUN", "FIGHT") == "LEFT" and toward_main("ITEM", "FIGHT") == "UP" and toward_main("RUN", "RUN") == "A"


def test_registry_names():
    assert macro_names() == ["back_out", "battle_fight", "battle_run", "goto", "switch", "use_item", "wait"]


# --- back_out ------------------------------------------------------------------

def test_back_out_to_overworld():
    rig = Rig([scr(["THE WORLD"], battle=False, menu=True), scr(["Hello"], battle=False), scr([], battle=False, screen=[])])
    out = run_macro(rig, "back_out")
    assert out["ok"] and out["result"] == "overworld" and rig.pressed == ["B", "B"] and out["presses"] == 2
    assert out["final_screen"]["mode"] == "overworld"


def test_back_out_stops_in_the_battle_menu_and_does_not_leave_the_fight():
    rig = Rig([scr(["TACKLE", ">GROWL"], menu=True), battle_menu("FIGHT")])
    out = run_macro(rig, "back_out")
    assert out["ok"] and out["result"] == "battle_menu" and rig.pressed == ["B"]


def test_back_out_noop_when_already_clear_and_stops_on_a_screen_that_will_not_change():
    assert run_macro(Rig([scr([], battle=False, screen=[])]), "back_out")["presses"] == 0
    rig = Rig([scr(["Stuck text"], battle=False)])  # B changes nothing
    out = run_macro(rig, "back_out")
    assert not out["ok"] and out["result"] == "screen_unchanged" and len(rig.pressed) <= 5
    assert rig.ticks, "it lets an animation finish before it gives up"


# --- battle_run ----------------------------------------------------------------

def test_battle_run_walks_the_menu_to_run_then_clears_the_text():
    rig = Rig([battle_menu("FIGHT"), battle_menu("PKMN"), battle_menu("RUN"), scr(["Got away safely!"], battle=False),
               scr([], battle=False, screen=[])])
    out = run_macro(rig, "battle_run")
    assert out["ok"] and out["result"] == "escaped" and rig.pressed == ["DOWN", "DOWN", "A", "B"]


def test_battle_run_outside_a_battle_and_trainer_battle_stop():
    out = run_macro(Rig([scr([], battle=False, screen=[])]), "battle_run")
    assert not out["ok"] and out["result"] == "not_in_battle" and out["presses"] == 0
    out = run_macro(Rig([scr(["No! There's no running from a trainer battle!"])]), "battle_run")
    assert not out["ok"] and out["result"] == "trainer_battle" and out["presses"] == 0


def test_battle_run_gives_up_after_failed_attempts_and_backs_out_of_submenus():
    menus = [battle_menu("RUN"), scr(["Can't escape!"]), battle_menu("RUN"), scr(["Can't escape!"]), battle_menu("RUN"),
             scr(["Can't escape!"]), battle_menu("RUN"), scr(["Can't escape!"]), battle_menu("RUN")]
    out = run_macro(Rig(menus), "battle_run")
    assert not out["ok"] and out["result"] == "run_failed"
    rig = Rig([scr(["POTION", "x 2"], menu=True), battle_menu("RUN"), scr([], battle=False, screen=[])])
    out = run_macro(rig, "battle_run")
    assert rig.pressed[0] == "B"  # a bag list is not the battle menu: leave it, never confirm


# --- battle_fight --------------------------------------------------------------

def test_battle_fight_picks_the_named_move(monkeypatch):
    monkeypatch.setattr(macros_battle, "battle_moves", lambda emu: ["TACKLE", "GROWL", "BITE"])
    emu = FakeEmulator()
    screens = [battle_menu("FIGHT"), scr(["TACKLE", "GROWL", "BITE"], menu=True, cur=0), scr(["TACKLE", "GROWL", "BITE"], menu=True, cur=1),
               scr(["TACKLE", "GROWL", "BITE"], menu=True, cur=2), scr(["WARTORTLE used BITE!"]), battle_menu("FIGHT")]
    rig = Rig(screens, emu)
    out = run_macro(rig, "battle_fight", {"move": "Bite"})
    assert out["ok"] and out["result"] == "attacked" and rig.pressed == ["A", "DOWN", "DOWN", "A", "A"]


def test_battle_fight_navigates_from_another_menu_cell_and_stops_on_unknown_move(monkeypatch):
    monkeypatch.setattr(macros_battle, "battle_moves", lambda emu: ["TACKLE"])
    rig = Rig([battle_menu("RUN"), battle_menu("ITEM"), battle_menu("FIGHT")])
    run_macro(rig, "battle_fight", {"move": "TACKLE"})
    assert rig.pressed[:2] == ["LEFT", "UP"]
    out = run_macro(Rig([battle_menu("FIGHT")]), "battle_fight", {"move": "EMBER"})
    assert not out["ok"] and out["result"].startswith("move_unknown") and out["presses"] == 0
    assert run_macro(Rig([scr([], battle=False, screen=[])]), "battle_fight", {"move": "TACKLE"})["result"] == "not_in_battle"
    assert run_macro(Rig([]), "battle_fight", {})["result"].startswith("bad_args")


# --- use_item ------------------------------------------------------------------

POTION = 0x14


def bag_emu(items):
    emu = FakeEmulator({BAG_COUNT: len(items)})
    for i, (iid, q) in enumerate(items):
        emu.memory[BAG_COUNT + 1 + 2 * i], emu.memory[BAG_COUNT + 2 + 2 * i] = iid, q
    emu.memory[BAG_COUNT + 1 + 2 * len(items)] = 0xFF
    return emu


def bag_list(cur):
    return scr(["POTION", "x 2"], menu=True, cur=cur)


def party_prompt(cur):
    return scr(["Use item on which POKeMON?"], menu=True, cur=cur)


@pytest.fixture
def potion(monkeypatch):
    monkeypatch.setattr(macros_battle, "item_id", lambda name: POTION if name.upper() == "POTION" else None)
    monkeypatch.setattr(macros_battle, "party_slot", lambda emu, on: {"WARTORTLE": 0, "PIDGEY": 1}.get(str(on).upper(), int(on) - 1 if str(on).isdigit() else None))
    monkeypatch.setattr(macros_battle, "party_names", lambda emu: ["WARTORTLE", "PIDGEY"])


def test_use_item_success_is_verified_by_the_bag_count(potion):
    emu = bag_emu([(POTION, 2)])
    screens = [battle_menu("FIGHT"), battle_menu("ITEM"), bag_list(0), party_prompt(0), party_prompt(1),
               scr(["PIDGEY recovered by 20!"]), battle_menu("FIGHT")]
    use = lambda e: e.memory.__setitem__(BAG_COUNT + 2, 1)  # the 5th press (A on the target) spends one POTION
    rig = Rig(screens, emu, after={5: use})
    emu.memory[PLAYER_MON] = 0
    out = run_macro(rig, "use_item", {"item": "POTION", "on": "PIDGEY"})
    assert out["ok"] and out["result"] == "used"
    assert rig.pressed == ["DOWN", "A", "A", "DOWN", "A", "A"]  # to ITEM, open, pick row 0, cursor to slot 2, confirm, read result


def test_use_item_no_effect_backs_out_and_never_reopens_the_bag(potion):
    emu = bag_emu([(POTION, 2)])
    screens = [battle_menu("ITEM"), bag_list(0), party_prompt(0), scr(["It won't have any effect."]),
               scr(["POTION", "x 2"], menu=True), battle_menu("ITEM")]
    rig = Rig(screens, emu)
    out = run_macro(rig, "use_item", {"item": "POTION"})
    assert not out["ok"] and out["result"] == "no_effect"
    assert rig.pressed[-2:] == ["B", "B"] and rig.pressed.count("A") == 3 and len(rig.pressed) <= 6


def test_use_item_stops_for_a_missing_item_unknown_item_target_and_outside_battle(potion):
    assert run_macro(Rig([battle_menu("FIGHT")], bag_emu([])), "use_item", {"item": "POTION"})["result"] == "item_not_in_bag"
    assert run_macro(Rig([battle_menu("FIGHT")]), "use_item", {"item": "WARP WHISTLE"})["result"].startswith("bad_args")
    emu = bag_emu([(POTION, 2)])
    assert run_macro(Rig([scr([], battle=False, screen=[])], emu), "use_item", {"item": "POTION"})["result"] == "not_in_battle"
    out = run_macro(Rig([party_prompt(0)], emu), "use_item", {"item": "POTION", "on": "MEW"})
    assert not out["ok"] and out["result"].startswith("target_not_in_party")


def test_use_item_caps_attempts(potion):
    emu = bag_emu([(POTION, 2)])
    screens = [bag_list(0)] * 10
    out = run_macro(Rig(screens, emu), "use_item", {"item": "POTION"})
    assert not out["ok"] and out["result"] in ("attempt_cap", "press_cap")


# --- switch --------------------------------------------------------------------

def test_switch_to_slot_two():
    emu = FakeEmulator({PARTY_COUNT: 3, PLAYER_MON: 0})
    sub = lambda cur: scr(["STATS", "SWITCH", "CANCEL"], menu=True, cur=cur, screen=["STATS SWITCH CANCEL"])
    screens = [battle_menu("FIGHT"), battle_menu("PKMN"), scr([], screen=["Choose a POKeMON."], menu=True, cur=0),
               scr([], screen=["Choose a POKeMON."], menu=True, cur=1), sub(0), sub(1), scr(["Go! PIDGEY!"]), battle_menu("FIGHT")]
    rig = Rig(screens, emu, after={6: lambda e: e.memory.__setitem__(PLAYER_MON, 1)})
    out = run_macro(rig, "switch", {"slot": 2})
    assert out["ok"] and out["result"] == "switched", out
    assert rig.pressed == ["RIGHT", "A", "DOWN", "A", "DOWN", "A", "A"]


def test_switch_stops_on_bad_slot_already_active_and_fainted_target():
    emu = FakeEmulator({PARTY_COUNT: 2, PLAYER_MON: 0})
    assert run_macro(Rig([battle_menu("FIGHT")], emu), "switch", {"slot": 5})["result"] == "slot_not_in_party"
    assert run_macro(Rig([battle_menu("FIGHT")], emu), "switch", {"slot": 1})["result"] == "already_active"
    out = run_macro(Rig([scr(["There's no will to fight!"])], emu), "switch", {"slot": 2})
    assert not out["ok"] and out["result"] == "target_fainted"
    assert run_macro(Rig([]), "switch", {"slot": 9})["result"].startswith("bad_args")


# --- goto / wait / runner ----------------------------------------------------------

def test_goto_walks_then_arrives_and_stops_on_a_fight_or_dialog():
    overworld = scr([], battle=False, screen=[])
    rig = Rig([overworld])
    out = run_macro(rig, "goto", {"map": "Pallet Town", "x": 5, "y": 6})
    assert out["ok"] and out["result"] == "arrived" and rig.pressed == ["UP"] * 3
    assert run_macro(Rig([battle_menu("FIGHT")]), "goto", {"map": 0, "x": 1, "y": 1})["result"] == "interrupted_battle"
    out = run_macro(Rig([scr(["Hello there"], battle=False)]), "goto", {"map": 0, "x": 1, "y": 1})
    assert not out["ok"] and out["result"] == "interrupted_dialog" and out["presses"] == 0
    assert run_macro(Rig([overworld]), "goto", {"map": "Atlantis", "x": 1, "y": 1})["result"].startswith("bad_args")


def test_wait_ticks_and_validates():
    rig = Rig([scr([], battle=False, screen=[])])
    out = run_macro(rig, "wait", {"frames": 90})
    assert out["ok"] and out["result"] == "waited" and rig.ticks == [90] and out["presses"] == 0
    assert run_macro(Rig([]), "wait", {"frames": 99999})["result"].startswith("bad_args")


def test_unknown_macro_and_press_cap_and_never_ready():
    out = run_macro(Rig([]), "dance")
    assert not out["ok"] and out["result"].startswith("unknown_macro")
    changing = [scr([f"line {i}"], battle=False) for i in range(40)]
    out = run_macro(Rig(changing), "back_out")
    assert not out["ok"] and out["result"] == "press_cap" and out["presses"] == 20
    out = run_macro(Rig([scr([], battle=True, screen=[])]), "battle_run")  # a blank battle screen that never gets a menu
    assert not out["ok"] and out["result"] == "screen_not_ready"
