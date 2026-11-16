"""Scratch copies and report paths for the glitch lab.

The input state is evidence: never opened for writing, never written beside. Copies land under
the caller's scratch root and reports under ``<runs_dir>/discoveries/`` - the directory every
checkpoint/curriculum reader already ignores (``is_discovery_state`` is the guard they ask).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from pokeagent.novelty.discoveries import DIR_NAME, STATE_SUFFIX, is_discovery_state

FORBIDDEN_DIRS = frozenset({"checkpoints", "leg_states", "states", "baselines"})
SCRATCH_SUFFIX = ".scratch.state"


def scratch_copy(state, scratch_root) -> Path:
    """Copy ``state`` to ``<scratch_root>/<stem>.scratch.state`` and return the copy path.

    The ORIGINAL is only read. ValueError when ``scratch_root`` is, or sits inside, a
    curriculum directory (checkpoints / leg_states / states / baselines), when the source
    sits in one (a checkpoint is never probe input), or when the source is a
    ``*.discovery.state`` evidence file - those are not starting points (no daisy chains).
    """
    src, root = Path(state), Path(scratch_root)
    bad = FORBIDDEN_DIRS & set(root.parts)
    if bad:
        raise ValueError(f"scratch_root inside {sorted(bad)}: {root}")
    bad = FORBIDDEN_DIRS & set(src.parts)
    if bad:
        raise ValueError(f"state inside {sorted(bad)}: {src}")
    if src.name.endswith(STATE_SUFFIX):
        raise ValueError(f"discovery states are evidence, not starting points: {src}")
    root.mkdir(parents=True, exist_ok=True)
    dst = root / f"{src.stem}{SCRATCH_SUFFIX}"
    shutil.copyfile(src, dst)
    return dst


def report_path(runs_dir, name) -> Path:
    """``<runs_dir>/discoveries/glitchlab-<name>.jsonl`` - inside the discoveries directory so the
    report can never be mistaken for a checkpoint or a curriculum state file."""
    p = Path(runs_dir) / DIR_NAME / f"glitchlab-{name}.jsonl"
    assert is_discovery_state(p) or (p.suffix == ".jsonl" and p.parent.name == DIR_NAME)
    return p
