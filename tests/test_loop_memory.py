"""The loop ledger and the shared 'loops' table (pure: no emulator)."""
import hashlib
from pathlib import Path
from types import SimpleNamespace as NS

from pokeagent.explorer.behaviours.base import Decision
from pokeagent.explorer import loop_veto
from pokeagent.explorer.loop_memory import (
    LEDGER_MAX, LOOP_NO_PROGRESS_N, LOOP_VETO_STEPS, NEVER_VETO, LoopLedger, Situation,
    clean_table, text_hash,
)

SIT = Situation(35, 5, 20, "UP", 123, False)


def rec(ledger, n=1, sit=SIT, button="A", step0=1, progressed=False):
    return [ledger.record(sit, button, progressed, step0 + i) for i in range(n)]


def test_text_hash_is_stable_across_calls_and_insensitive_to_case_and_whitespace():
    h = text_hash(["Hello  there"])
    assert h == text_hash(["  hello there "]) == text_hash(["HELLO THERE"])
    assert h == int.from_bytes(hashlib.sha256("hello there".encode()).digest()[:8], "big")  # same in any process
    assert text_hash(["a", "b"]) != text_hash(["a b"])


def test_the_ledger_vetoes_at_exactly_n_consecutive_fruitless_repeats():
    l = LoopLedger()
    for i in range(1, LOOP_NO_PROGRESS_N):
        assert l.record(SIT, "A", False, i) is None
        assert not l.vetoed(SIT, "A", i)
    ev = l.record(SIT, "A", False, LOOP_NO_PROGRESS_N)
    assert ev is not None and ev.no_progress == LOOP_NO_PROGRESS_N and ev.veto_until == LOOP_NO_PROGRESS_N + LOOP_VETO_STEPS
    assert l.vetoed(SIT, "A", LOOP_NO_PROGRESS_N + 1)
    assert not l.vetoed(SIT, "B", LOOP_NO_PROGRESS_N + 1)  # a different button is not vetoed


def test_a_progress_press_resets_the_count_and_the_veto():
    l = LoopLedger()
    rec(l, LOOP_NO_PROGRESS_N)
    assert l.vetoed(SIT, "A", 10)
    l.record(SIT, "A", True, 10)
    assert not l.vetoed(SIT, "A", 11) and l.count(SIT, "A") == 0


def test_a_different_text_facing_or_tile_is_a_different_situation():
    l = LoopLedger()
    rec(l, LOOP_NO_PROGRESS_N)
    for sit in (Situation(35, 5, 20, "UP", 999, False), Situation(35, 5, 20, "DOWN", 123, False),
                Situation(35, 5, 21, "UP", 123, False), Situation(36, 5, 20, "UP", 123, False)):
        assert not l.vetoed(sit, "A", 10)


def test_a_press_between_repeats_of_another_key_does_not_reset_it():
    l = LoopLedger()
    other = Situation(1, 1, 1, "UP", 0, False)
    l.record(SIT, "A", False, 1)
    l.record(other, "A", False, 2)
    l.record(other, "A", False, 3)
    l.record(SIT, "A", False, 4)
    ev = l.record(SIT, "A", False, 5)
    assert ev is not None and ev.no_progress == LOOP_NO_PROGRESS_N


def test_the_veto_expires_and_re_arms_on_the_next_fruitless_press():
    l = LoopLedger()
    rec(l, LOOP_NO_PROGRESS_N, step0=1)                        # armed at step 3: vetoed through step 3 + 60 - 1
    assert l.vetoed(SIT, "A", 3 + LOOP_VETO_STEPS - 1)
    assert not l.vetoed(SIT, "A", 3 + LOOP_VETO_STEPS)         # one retry is allowed
    ev = l.record(SIT, "A", False, 4 + LOOP_VETO_STEPS)
    assert ev is not None and l.vetoed(SIT, "A", 5 + LOOP_VETO_STEPS)


def test_a_printing_box_never_vetoes():
    l = LoopLedger()
    for i in range(LOOP_NO_PROGRESS_N + 5):  # text still printing: a different situation every press
        ev = l.record(Situation(35, 5, 20, "UP", text_hash([f"page {i}"]), False), "A", False, i)
        assert ev is None
    assert l.top() == []


def test_top_ranks_two_vetoed_entries_without_comparing_entries():
    l = LoopLedger()
    rec(l, LOOP_NO_PROGRESS_N, button="A")
    rec(l, LOOP_NO_PROGRESS_N, button="B", step0=50)  # two unequal vetoed entries: a plain sorted() compared _Entry objects and raised
    assert {r["button"] for r in l.top()} == {"A", "B"}


def test_the_ledger_is_bounded():
    l = LoopLedger()
    for i in range(LEDGER_MAX + 10):
        l.record(Situation(1, i % 100, i // 100, "UP", i, False), "A", False, 1)
    assert len(l.e) <= LEDGER_MAX


def ns_ctx(tmp_path):
    return NS(view=NS(m=1, x=1, y=1, lines=[], battling=False), facing="UP", mem=NS(data={}),
              step=0, run_dir=Path(tmp_path), log=lambda *a, **k: None, loops=None)


class Alt:
    name = "alt"

    def applies(self, ctx):
        return True

    def step(self, ctx):
        return Decision("DOWN", "alt")


class OnePick:
    def __init__(self, behaviour):
        self.b = behaviour

    def choose(self, ctx, skip=frozenset()):
        return self.b.step(ctx)


def test_never_veto_behaviours_are_never_vetoed_or_recorded(tmp_path):
    for name in NEVER_VETO:
        ctx = ns_ctx(tmp_path)
        d = loop_veto.check(ctx, OnePick(Alt()), Decision("A", "some_rule", behaviour=name))
        assert d.button == "A"  # returned as proposed: the seam does not touch it
        loop_veto.record(ctx, Decision("A", "some_rule", behaviour=name), [])
        assert loop_veto.of(ctx).ledger.e == {}


def test_malformed_shared_loops_values_are_ignored():
    assert clean_table("not a dict") == {}
    assert clean_table([1, 2]) == {}
    assert clean_table({"k": "junk"}) == {}
    assert clean_table({"k": {"runs": "no", "last": 1, "clear": 0}}) == {}
    assert clean_table({"k": {"runs": ["a"], "last": "?", "clear": 0}}) == {}
    assert clean_table({"k": {"runs": ["a"], "last": 1, "clear": True}}) == {}   # a bool is not a timestamp
    good = {"k": {"runs": ["a"], "last": 1, "clear": 0}}
    assert clean_table(good) == good
