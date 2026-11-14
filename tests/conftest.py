"""Shared synthetic-map helpers for the atlas tests (no ROM)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pokeagent.atlas.rom_maps import MapHeader
from pokeagent.atlas.world import Place, WorldLayout


def hdr(mid, w, h, warps=()):
    return MapHeader(mid, 0, h, w, 0, 0, [], list(warps))


def world():
    """Outdoor 0 (10x10 cells at 4,4). House 10 (4x4 cells, exit mat (1,3)), 2F 11 (stairs (3,0)), cave 12 + 13 by learned warp, 14 unreachable."""
    H = {0: hdr(0, 5, 5, [(5, 5, 0, 10), (8, 2, 0, 12)]),
         10: hdr(10, 2, 2, [(1, 3, 0, 255), (3, 0, 0, 11)]),
         11: hdr(11, 2, 2, [(3, 0, 1, 10)]),
         12: hdr(12, 3, 3, [(2, 5, 0, 255)]),
         13: hdr(13, 2, 2, [(0, 0, 0, 255)]),
         14: hdr(14, 2, 2, [(0, 0, 0, 255)])}
    pl = {0: Place(4, 4, 10, 10, False)}
    y = 30
    for m in (10, 11, 12, 13, 14):
        pl[m] = Place(2, y, H[m].w * 2, H[m].h * 2, True)
        y += 10
    return H, WorldLayout(pl, 40, 90, 20)


def walkgrid(w=20, h=20):
    return np.ones((h, w), bool)


@pytest.fixture(autouse=True)
def _clear_blackout_tax():
    """training._tax is module-global; no test may leak a learned blackout margin into another."""
    from pokeagent.explorer import training
    training.set_blackout_tax({})
    yield
    training.set_blackout_tax({})


@pytest.fixture(autouse=True)
def _clear_magikarp_floor():
    """budget._magikarp_floor is module-global; no test may leak the Magikarp reserve into another."""
    from pokeagent.explorer.economy import budget
    budget.set_magikarp_floor(0)
    yield
    budget.set_magikarp_floor(0)


def _pin_run_records_at_collection():
    """Some test modules do ``from pokeagent.grind.atlas import STEPS_PER_MIN`` at import (collection) time, before
    any fixture runs; conftest imports first, so pin the runs root to an empty dir here too."""
    import tempfile
    from pokeagent.grind import atlas, measure
    measure.RUNS_ROOT = Path(tempfile.mkdtemp(prefix="pa_no_runs_"))
    atlas.frames_per_step.cache_clear()


_pin_run_records_at_collection()


@pytest.fixture(autouse=True)
def _hermetic_run_records(tmp_path_factory, monkeypatch):
    """grind.atlas.FRAMES_PER_STEP / STEPS_PER_MIN calibrate lazily from the checkout's runs/ (measure.RUNS_ROOT)
    and cache the answer; a real game run's explore-* dirs must not change what the tests see. Point the root at
    an empty dir (the no-records default of 16 frames/step) and drop the cache before and after each test."""
    from pokeagent.grind import atlas, measure
    monkeypatch.setattr(measure, "RUNS_ROOT", tmp_path_factory.mktemp("no_runs"))
    atlas.frames_per_step.cache_clear()
    yield
    atlas.frames_per_step.cache_clear()
