import io
from pathlib import Path

from pokeagent.agent import RunResult
from pokeagent.console import print_step, print_summary
from pokeagent.decision import Decision
from pokeagent.ram import GameState


def _state():
    return GameState(
        map_id=0x26, x=3, y=6, party_count=0, badges=0,
        badge_count=0, in_battle=False, money=3000,
    )


def test_print_step_with_note():
    out = io.StringIO()
    decision = Decision(
        "DOWN",
        thinking="I'm in the bedroom facing the stairs; going down should lead outside.",
        note="stairs are at the top-right of the bedroom",
    )
    print_step(12, 50, _state(), decision, out=out)
    assert out.getvalue() == (
        "--- step 12/50  map=0x26 pos=(3,6) party=0 badges=0 battle=no money=3000\n"
        "thinking: I'm in the bedroom facing the stairs; going down should lead outside.\n"
        "button:   DOWN       note: stairs are at the top-right of the bedroom\n"
    )


def test_print_step_without_note():
    out = io.StringIO()
    print_step(12, 50, _state(), Decision("UP", thinking="north"), out=out)
    assert out.getvalue() == (
        "--- step 12/50  map=0x26 pos=(3,6) party=0 badges=0 battle=no money=3000\n"
        "thinking: north\n"
        "button:   UP\n"
    )


def test_print_step_with_error():
    out = io.StringIO()
    decision = Decision("NONE", thinking="hmm", error="no json object")
    print_step(12, 50, _state(), decision, out=out)
    assert out.getvalue() == (
        "--- step 12/50  map=0x26 pos=(3,6) party=0 badges=0 battle=no money=3000\n"
        "thinking: hmm\n"
        "button:   NONE\n"
        "error:   no json object\n"
    )


def test_print_step_error_with_timing():
    out = io.StringIO()
    decision = Decision("NONE", error="timeout after 120s")
    print_step(12, 50, _state(), decision, error_ms=120050, out=out)
    assert "error:   timeout after 120s (120050ms)\n" in out.getvalue()


def test_print_summary():
    out = io.StringIO()
    result = RunResult(
        steps=5, stop_reason="max_steps", run_dir=Path("runs/20261102-223000"), failures=1
    )
    print_summary(result, out)
    text = out.getvalue()
    assert "5" in text
    assert "max_steps" in text
    assert "1" in text
    assert str(result.run_dir) in text
