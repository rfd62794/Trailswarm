"""Fresh-memory headless run 2026-11-16: the explorer hopped Cerulean's row-33 ledge into a sealed pocket and lost 2,300 steps."""
from types import SimpleNamespace

import pytest

from pokeagent.explorer import ledge_trap
from pokeagent.explorer.behaviours.base import Decision


def _ctx(pos):
    mem = SimpleNamespace(m=lambda m, _d={"blocked": []}: _d)
    return SimpleNamespace(pos=lambda: pos, mem=mem)


@pytest.mark.parametrize("x", [16, 19, 23])
def test_the_ledge_press_is_vetoed_and_learned_as_a_wall(x):
    ctx = _ctx((3, x, 32))
    assert ledge_trap.veto(ctx, Decision("DOWN", "x", "y")) and f"{x},32,DOWN" in ctx.mem.m(3)["blocked"]


@pytest.mark.parametrize("pos,button", [((3, 19, 32), "UP"), ((3, 19, 31), "DOWN"), ((3, 12, 32), "DOWN"), ((3, 24, 32), "DOWN"), ((5, 19, 32), "DOWN")])
def test_everything_else_passes(pos, button):
    ctx = _ctx(pos)
    assert ledge_trap.veto(ctx, Decision(button, "x", "y")) is None and ctx.mem.m(3)["blocked"] == []
