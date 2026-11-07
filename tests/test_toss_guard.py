"""Never toss: every toss screen (USE/TOSS, quantity, 'OK to toss' YES/NO) is answered with a back-out press by any behaviour,
and an item that does leave the bag outside a USE is logged as an item_tossed anomaly and a decisions.jsonl event."""
from __future__ import annotations

import json

import pytest

from pokeagent.explorer import anomaly_detectors as ad
from pokeagent.explorer.anomalies import AnomalyMonitor
from pokeagent.explorer.behaviours import default_behaviours
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.behaviours.cave_escape import rope_press
from pokeagent.explorer.decisions import DecisionLog
from pokeagent.explorer.engine import Engine
from pokeagent.explorer.selector import Selector
from pokeagent.explorer.toss_guard import CONFIRM, QUANTITY, USE_TOSS, toss_screen, toss_veto
from pokeagent.screentext import CHARMAP
from test_explorer_behaviours import TM, make_ctx

INV = {ch: b for b, ch in CHARMAP.items() if ch}

# What the screen reads in a real run (runs/explore-20261106-203703-14908, steps 178-181).
BAG = ["ANTIDOTE", "x 1", "TM34", "x 1", "TM12", "x 1"]
SCREENS = {
    "use_toss_on_use": BAG + [">USE", "TOSS"],
    "use_toss_on_toss": BAG + ["USE", ">TOSS"],
    "quantity": BAG + ["HP UP x01", "TOSS"],
    "confirm_text": BAG + ["HP UP x01", "Is it OK to toss", "ANTIDOTE?"],
    "confirm_yes": ["TM12 >YES", "HP UP NO", "Is it OK to toss", "ANTIDOTE?"],
    "confirm_no": ["TM12 YES", "HP UP >NO", "Is it OK to toss", "ANTIDOTE?"],
}


def new_ctx(tmp_path, **kw):
    ctx = make_ctx(tmp_path, **kw)
    ctx.trans = (tmp_path / "transitions.jsonl").open("a", encoding="utf-8")
    return ctx


def draw(ctx, rows):
    """Paint a frame whose inner rows are `rows` (a '>' becomes the menu cursor tile)."""
    emu = ctx.emu
    for i in range(360):
        emu.set(TM + i, 0x7F)
    emu.set(TM, 0x79); emu.set(TM + 1, 0x7A)
    for r, text in enumerate(rows, start=1):
        emu.set(TM + 20 * r, 0x7C); emu.set(TM + 20 * r + 19, 0x7C)
        for i, ch in enumerate(text[:18]):
            emu.set(TM + 20 * r + 1 + i, 0xED if ch == ">" else INV.get(ch, 0x7F))


class Press:
    """A behaviour that insists on one button, standing in for any of menu / advance_dialog / readiness / guards."""
    name = "stub"

    def __init__(self, button): self.button = button
    def applies(self, ctx): return True
    def step(self, ctx): return Decision(self.button, "stub_rule", "insists")
    def done(self, ctx): return False
    def failed(self, ctx): return False


def names(ctx):
    return [getattr(p, "name", p) for p in ctx.emu.presses]


def pressed(tmp_path, screen, button):
    ctx = new_ctx(tmp_path)
    draw(ctx, SCREENS[screen])
    ctx.refresh()
    Engine(ctx, selector=Selector([Press(button)])).step()
    return names(ctx)[-1]


def test_screens_are_recognised():
    assert toss_screen(SCREENS["use_toss_on_toss"]) == USE_TOSS
    assert toss_screen(SCREENS["quantity"]) == QUANTITY
    assert toss_screen(SCREENS["confirm_yes"]) == CONFIRM and toss_screen(SCREENS["confirm_text"]) == CONFIRM
    assert toss_screen(BAG + ["CANCEL", "EXIT"]) is None and toss_screen(["Use item on which", "POKeMON?"]) is None


@pytest.mark.parametrize("screen", ["use_toss_on_toss", "quantity", "confirm_text", "confirm_yes"])
@pytest.mark.parametrize("button", ["A", "DOWN", "START", "RIGHT"])
def test_every_toss_screen_is_backed_out_of_whatever_the_behaviour_presses(tmp_path, screen, button):
    assert pressed(tmp_path, screen, button) == "B"


def test_use_toss_box_with_cursor_on_use_cannot_move_toward_toss(tmp_path):
    assert pressed(tmp_path, "use_toss_on_use", "DOWN") == "B"
    assert pressed(tmp_path, "use_toss_on_use", "A") == "A"  # USE itself stays reachable


def test_declining_is_allowed(tmp_path):
    assert pressed(tmp_path, "confirm_no", "A") == "A"  # cursor on NO: A is the decline
    assert pressed(tmp_path, "confirm_no", "B") == "B"
    assert pressed(tmp_path, "confirm_yes", "A") == "B"  # cursor on YES: A would toss


def test_the_menu_explorer_cannot_pick_toss_as_an_untried_option(tmp_path):
    """Before the guard: Menu saw '>TOSS' as a new option and pressed A (menu_new_option); advance_dialog then stepped the rest."""
    ctx = new_ctx(tmp_path)
    draw(ctx, SCREENS["use_toss_on_toss"])
    engine = Engine(ctx, selector=Selector(default_behaviours()))
    for _ in range(3):
        engine.step()
    assert set(names(ctx)) <= {"B", "UP"}


def test_cave_escape_and_procedures_still_reach_use_but_never_toss(tmp_path):
    ctx = make_ctx(tmp_path)
    on_use = toss_veto(SCREENS["use_toss_on_use"], rope_press(ctx, SCREENS["use_toss_on_use"]))
    assert rope_press(ctx, SCREENS["use_toss_on_use"]).button == "A" and on_use is None
    from_toss = rope_press(ctx, SCREENS["use_toss_on_toss"])
    assert from_toss.button == "UP" and toss_veto(SCREENS["use_toss_on_toss"], from_toss) is None  # UP leaves TOSS
    assert toss_veto(SCREENS["use_toss_on_toss"], Decision("A", "procedure_step")) is not None  # a procedure's A on TOSS is refused


def obs(**kw):
    return ad.Obs(step=1, frame=10, map=5, x=3, y=4, button="A", prev=(5, 3, 4), **kw)


def test_threw_away_text_fires_item_tossed_once():
    d = ad.Detectors()
    d.update(obs(bag_total=3))
    out = d.update(obs(bag_total=2, threw_away=True))
    assert [f.type for f in out] == ["item_tossed"] and out[0].details["reason"] == "text"
    assert d.update(obs(bag_total=2, threw_away=True)) == []  # the text stays up for several presses: one finding


def test_bag_drop_after_the_toss_screens_fires_but_a_use_does_not():
    d = ad.Detectors()
    d.update(obs(bag_total=3, toss_screen="confirm"))
    out = d.update(obs(bag_total=2))
    assert [f.details["reason"] for f in out] == ["bag_drop"]
    d = ad.Detectors()  # a potion used: the bag shrinks with only the USE/TOSS box seen
    d.update(obs(bag_total=3, toss_screen="use_toss"))
    assert d.update(obs(bag_total=2)) == []
    d = ad.Detectors()  # a drop in battle (a thrown ball) or with no toss screen is not a toss
    d.update(obs(bag_total=3, toss_screen="quantity"))
    assert d.update(obs(bag_total=2, battle=True)) == []


def test_engine_logs_the_anomaly_and_a_decisions_event(tmp_path):
    ctx = new_ctx(tmp_path, memory={0xD31D: 1, 0xD31E: 20, 0xD31F: 1})
    ctx.run_dir = tmp_path / "run1"
    ctx.run_dir.mkdir()
    ctx.anomalies = AnomalyMonitor.for_ctx(ctx)
    log = DecisionLog(tmp_path / "run1" / "decisions.jsonl")
    draw(ctx, BAG + ["Threw away", "ANTIDOTE."])
    Engine(ctx, selector=Selector([Press("A")]), decision_log=log).step()
    log.close()
    recs = [json.loads(ln) for ln in (tmp_path / "run1" / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in recs if "event" in r] == ["item_tossed"]
    assert [f["type"] for f in ctx.anomalies.findings] == ["item_tossed"]
