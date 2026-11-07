from pokeagent.explorer.behaviours.already_out import AlreadyOutGuard, already_out_decision
from pokeagent.explorer.behaviours.battle_yesno import BattleYesNo
from test_explorer_behaviours import BATTLE, TM, make_ctx, put_box


def _battle_ctx(tmp_path, rows):
    ctx = make_ctx(tmp_path, memory={BATTLE: 2, 0xD015: 0, 0xD016: 20})
    put_box(ctx, text_rows=rows)
    return ctx


def test_trainer_change_prompt_in_battle_is_declined_with_b(tmp_path):
    ctx = _battle_ctx(tmp_path, ("Will BCN", "change POKEMON?", ">YES", " NO"))
    ctx.emu.set(TM + 20 * 13 + 1, 0xED)  # cursor on YES: the old path pressed A here
    ctx.refresh()
    b = BattleYesNo()
    assert b.applies(ctx)
    d = b.step(ctx)
    assert (d.button, d.rule) == ("B", "decline_switch")


def test_other_battle_yesno_uses_dialog_rules(tmp_path):
    ctx = _battle_ctx(tmp_path, ("Do you want", "to continue?", " YES", " NO"))
    ctx.emu.set(TM + 20 * 13 + 1, 0xED)
    ctx.refresh()
    d = BattleYesNo().step(ctx)
    assert d.button == "A"


def test_already_out_decision_is_pure():
    assert already_out_decision("WARTORTLE is already out!", 100, 0) == (True, 140)
    assert already_out_decision("Bring out which POKeMON?", 110, 140) == (True, 140)
    assert already_out_decision("Bring out which POKeMON?", 141, 140) == (False, 140)
    assert already_out_decision("FIGHT PKMN", 110, 140) == (False, 140)


def test_guard_backs_out_and_holds(tmp_path):
    ctx = _battle_ctx(tmp_path, ("WARTORTLE is", "already out!"))
    ctx.refresh()
    g = AlreadyOutGuard()
    assert g.applies(ctx) and g.step(ctx).button == "B"
    assert ctx.already_out_until > ctx.step
