"""press_value: per-context learning of which A/B presses do anything, and the gate that stops useless ones."""
from __future__ import annotations

import sys
from pathlib import Path

from pokeagent.explorer.behaviours import Readiness
from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer.mash_skill import MashSkill, signature as mash_signature
from pokeagent.explorer.press_frame import PressFrame
from pokeagent.explorer.press_value import (
    MAX_SIGS, WAIT_BOUND, PressValue, context_sigs, gate, get_pv, trim, had_effect, merge_press_value, observe, screen_kind,
)
from pokeagent.explorer.selector import Selector
from test_explorer_behaviours import TM, make_ctx, put_box

ARROW = 0xEE


def poor(pv, sig, button="A", n=40, effect=3):
    pv.table[sig] = {button: {"n": n, "effect": effect, "progress": 0}}


def test_screen_kinds(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.refresh()
    assert screen_kind(ctx.view, False) == "overworld"
    put_box(ctx)
    ctx.refresh()
    assert screen_kind(ctx.view, False) == "text_waiting" and screen_kind(ctx.view, True) == "text_printing"
    put_box(ctx, menu=True)
    ctx.refresh()
    assert screen_kind(ctx.view, False) == "menu"
    put_box(ctx, menu=True, text_rows=("YES", "NO"))
    ctx.refresh()
    assert screen_kind(ctx.view, False) == "yes_no"
    ctx.emu.set(0xD057, 1)
    put_box(ctx)
    ctx.refresh()
    assert screen_kind(ctx.view, False) == "battle_text" and screen_kind(ctx.view, True) == "battle_text_printing"
    put_box(ctx, menu=True, text_rows=("FIGHT", "ITEM"))
    ctx.refresh()
    assert screen_kind(ctx.view, False) == "battle_menu"


def test_signature_carries_map_behaviour_joypad_and_text(tmp_path):
    ctx = make_ctx(tmp_path, memory={0xCD6B: 1})
    put_box(ctx, text_rows=("OAK SAYS HI",))
    ctx.refresh()
    fine, coarse = context_sigs(ctx, "advance_dialog")
    assert "m40" in fine and "advance_dialog" in fine and "j1" in fine and "OAK SAYS HI" in fine
    assert "OAK" not in coarse and "advance_dialog" in coarse and "text_waiting" in coarse


def test_record_counts_effect_and_progress_and_caps_signatures():
    pv = PressValue({})
    pv.record("s", "c", "A", True)
    pv.record("s", "c", "A", False)
    pv.mark_progress()
    assert pv.table["s"]["A"] == {"n": 2, "effect": 1, "progress": 2}  # each of the two presses is credited
    assert pv.table["c"]["A"]["progress"] == 2
    for i in range(MAX_SIGS + 80):
        pv.record(f"sig{i}", f"co{i}", "B", False)
        pv.record("s", "c", "A", True)  # the heavily used one survives the trim
    trim(pv.table)  # what MapMemory.save does
    assert len(pv.table) == MAX_SIGS and "s" in pv.table


def test_gate_waits_in_a_poor_context_and_presses_after_the_bound(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.refresh()
    pv = get_pv(ctx)
    fine, coarse = context_sigs(ctx, "readiness")
    poor(pv, fine)
    first = gate(ctx, Decision("A", "mash A/4", behaviour="readiness"))
    assert first.button == "" and "press_gate: wait (A had effect 3/40 here)" in first.why
    ctx.frame += WAIT_BOUND - 1
    assert gate(ctx, Decision("A", "mash A/4", behaviour="readiness")).button == ""
    ctx.frame += 1
    assert gate(ctx, Decision("A", "mash A/4", behaviour="readiness")).button == "A"  # bounded: no deadlock
    assert gate(ctx, Decision("A", "mash A/4", behaviour="readiness")).button == ""  # the next press waits again


def test_gate_lets_good_young_and_exempt_contexts_press(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.refresh()
    pv = get_pv(ctx)
    fine, _ = context_sigs(ctx, "readiness")
    poor(pv, fine, n=7, effect=0)  # not enough evidence yet
    assert gate(ctx, Decision("A", "r", behaviour="readiness")).button == "A"
    poor(pv, fine, n=40, effect=20)  # good results
    assert gate(ctx, Decision("A", "r", behaviour="readiness")).button == "A"
    poor(pv, fine, n=40, effect=0)
    assert gate(ctx, Decision("A", "r", behaviour="goto")).button == "A"  # only the four behaviours are gated
    assert gate(ctx, Decision("UP", "r", behaviour="readiness")).button == "UP"  # only A and B
    pv.table[fine]["A"]["progress"] = 10  # useless looking but it advances things
    assert gate(ctx, Decision("A", "r", behaviour="readiness")).button == "A"


def test_gate_falls_back_to_the_coarse_context_for_unseen_text(tmp_path):
    ctx = make_ctx(tmp_path)
    put_box(ctx, text_rows=("NEW TEXT",))
    ctx.refresh()
    pv = get_pv(ctx)
    _, coarse = context_sigs(ctx, "advance_dialog")
    poor(pv, coarse, n=30, effect=1)
    assert gate(ctx, Decision("A", "advance_a", behaviour="advance_dialog")).button == ""


def test_battle_text_needs_more_proof_and_printing_alone_never_holds(tmp_path):
    ctx = make_ctx(tmp_path, memory={0xD057: 1})
    put_box(ctx, text_rows=("WILD PIDGEY",))
    ctx.refresh()
    pv = get_pv(ctx)
    pv.watch(ctx)  # text just changed: printing
    d = Decision("A", "fight", behaviour="battle_moves")
    assert gate(ctx, d).button == "A"  # no history: pressing is never held for printing alone
    fine, coarse = context_sigs(ctx, "battle_moves")
    poor(pv, fine, n=19, effect=0)
    assert gate(ctx, d).button == "A"  # under 20 presses
    poor(pv, fine, n=40, effect=5)  # 12.5% is not under 10%
    assert gate(ctx, d).button == "A"
    poor(pv, fine, n=40, effect=3)
    assert gate(ctx, d).button == ""


def test_prompt_arrow_means_waiting_at_once(tmp_path):
    ctx = make_ctx(tmp_path, memory={0xD057: 1})
    put_box(ctx, text_rows=("WILD PIDGEY",))
    ctx.emu.set(TM + 20 * 16 + 18, ARROW)
    ctx.refresh()
    pv = get_pv(ctx)
    pv.watch(ctx)
    assert not pv.printing(ctx)


def frame_for(ctx, name="A", before=(0x28, 5, 6), after=(0x28, 5, 6), box_before=False, box_after=False):
    ctx.refresh()
    fr = PressFrame(name, "agent", "t", before=before, after=after, tm=ctx.view.tm, tm2=ctx.view.tm,
                    box_before=box_before, box_after=box_after)
    fr.fp_pre = None
    return fr


def test_had_effect_sees_movement_boxes_text_and_ram(tmp_path):
    ctx = make_ctx(tmp_path)
    fp = lambda: __import__("pokeagent.explorer.press_value", fromlist=["x"]).fingerprint(ctx.emu)
    fr = frame_for(ctx)
    fr.fp_pre = fp()
    assert not had_effect(ctx, fr, fp())
    assert had_effect(ctx, frame_for(ctx, after=(0x28, 5, 5)), fp())
    assert had_effect(ctx, frame_for(ctx, box_after=True), fp())
    put_box(ctx, text_rows=("HELLO",))
    ctx.refresh()
    fr = PressFrame("A", "agent", "t", tm=ctx.view.tm, box_before=True, box_after=True)
    fr.fp_pre = fp()
    put_box(ctx, text_rows=("GOODBYE",))
    fr.tm2 = ctx.emu.read_range(TM, 360)
    assert had_effect(ctx, fr, fp())
    fr.tm2 = fr.tm
    assert not had_effect(ctx, fr, fp())
    ctx.emu.set(0xD31E, 9)  # the bag changed
    assert had_effect(ctx, fr, fp())


def test_observe_records_the_pending_press(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.refresh()
    sel = Selector([])
    pv = get_pv(ctx)
    ctx.pv_pending = ("f", "c", "A")
    fr = frame_for(ctx)
    from pokeagent.explorer.press_value import fingerprint
    fr.fp_pre = fingerprint(ctx.emu)
    observe(ctx, fr)
    assert pv.table["f"]["A"] == {"n": 1, "effect": 0, "progress": 0} and ctx.pv_last_effect is False
    assert ctx.pv_pending is None and sel is not None


def test_merge_takes_the_larger_n_per_entry_and_caps():
    dst = {"press_value": {"a": {"A": {"n": 10, "effect": 2, "progress": 0}}}}
    src = {"press_value": {"a": {"A": {"n": 30, "effect": 5, "progress": 1}, "B": {"n": 4, "effect": 4, "progress": 0}},
                           "b": {"A": {"n": 1, "effect": 0, "progress": 0}}}}
    merge_press_value(dst, src)
    assert dst["press_value"]["a"]["A"]["n"] == 30 and dst["press_value"]["a"]["B"]["n"] == 4
    merge_press_value(dst, {"press_value": {"a": {"A": {"n": 12, "effect": 9, "progress": 0}}}})
    assert dst["press_value"]["a"]["A"]["n"] == 30  # the smaller observation never wins
    big = {"press_value": {f"s{i}": {"A": {"n": i + 1, "effect": 0, "progress": 0}} for i in range(MAX_SIGS + 50)}}
    merge_press_value(dst, big)
    assert len(dst["press_value"]) == MAX_SIGS


def test_swarm_merge_memory_calls_it():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import swarm
    dst = swarm.merge_memory({"maps": {}}, {"maps": {}, "press_value": {"a": {"A": {"n": 5, "effect": 1, "progress": 0}}}})
    assert dst["press_value"]["a"]["A"]["n"] == 5


def test_selector_gates_a_readiness_press_and_undoes_its_count(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.stable_frames = 0
    ctx.refresh()
    ctx.skill = type("F", (MashSkill,), {"choose": lambda self, sig: "A/4"})(ctx.mem.data)
    pv = get_pv(ctx)
    fine, _ = context_sigs(ctx, "readiness")
    poor(pv, fine)
    d = Selector([Readiness()]).choose(ctx)
    assert d.button == "" and d.behaviour == "readiness" and ctx.busy_presses == 0
    assert (tmp_path / "press_gate.jsonl").exists()


def test_selector_marks_an_unwaited_press_pending(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.stable_frames = 0
    ctx.skill = type("F", (MashSkill,), {"choose": lambda self, sig: "A/4"})(ctx.mem.data)
    d = Selector([Readiness()]).choose(ctx)
    assert d.button == "A" and ctx.pv_pending[2] == "A"


def test_mash_grade_charges_frames_for_presses_without_effect(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.stable_frames = 0
    ctx.refresh()
    ctx.skill = type("F", (MashSkill,), {"choose": lambda self, sig: "A/4"})(ctx.mem.data)
    d = Readiness().step(ctx)
    ctx.pv_last_effect = False
    d.after(ctx)
    ctx.frame += 40
    ctx.stable_frames = 10
    ctx.refresh()
    Readiness().step(ctx)
    e = ctx.mem.data["mash_skill"][mash_signature(0x28, False, False)]["A/4"]
    assert e["mean_frames"] == 40 + 2 and e["mean_presses"] == 1  # WAIT now beats A on a tie
