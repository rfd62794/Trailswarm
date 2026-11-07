"""The A-pacing learner: shrinks while presses work, grows on a dropped press, stays in bounds."""
from pokeagent.explorer import text_pace as tp
from pokeagent.explorer.text_pace import PaceLearner, prompt_waiting, screen_kind


def test_prompt_tile_position():
    tm = bytearray(360)
    assert not prompt_waiting(bytes(tm))
    tm[16 * 20 + 18] = 0xEE
    assert prompt_waiting(bytes(tm)) and not prompt_waiting(b"")


def test_screen_kinds():
    assert screen_kind(b"", True, False) == "battle"
    assert screen_kind(b"", False, True) == "menu" and screen_kind(b"", False, True, yesno=True) == "yesno"
    assert screen_kind(b"", False, False) == "box"


def test_learner_shrinks_after_clean_presses_and_never_below_min():
    pl = PaceLearner({})
    start = pl.settle("box")
    for _ in range(tp.SHRINK_AFTER):
        pl.record("box", False)
    assert pl.settle("box") == start - tp.SHRINK_STEP
    for _ in range(200):
        pl.record("box", False)
    assert pl.settle("box") == tp.MIN_SETTLE


def test_learner_grows_on_a_drop_and_never_above_max():
    pl = PaceLearner({})
    for _ in range(100):
        pl.record("box", False)
    low = pl.settle("box")
    assert pl.record("box", True) == low * tp.GROW_FACTOR
    for _ in range(20):
        pl.record("box", True)
    assert pl.settle("box") == tp.MAX_SETTLE
    assert pl.table["box"]["drops"] == 21


def test_kinds_are_learned_separately_and_persist_in_the_data_dict():
    data = {}
    pl = PaceLearner(data)
    pl.record("menu", True)
    assert pl.settle("box") == tp.START_SETTLE and data["text_pace"]["menu"]["drops"] == 1
    assert PaceLearner(data).settle("menu") == pl.settle("menu")
