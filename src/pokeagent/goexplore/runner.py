"""Go-Explore slice 4 (plan D6): the return-and-explore driver.

``pick`` chooses one archived cell (``select.choose``, seeded ``base_seed + index`` so a cell is not
replayed identically), bumps its ``n_seen`` and saves the archive BEFORE any run launches - the
Harvester owns ``archive.json`` while a run is in flight, so ``drive`` never saves afterwards. An
empty archive returns the start state instead (cid None: no ``--cell-from``). ``command`` builds the
``tools/explore_demo.py`` argv; ``drive`` takes ``driver.lock`` (one driver per archive root) and
runs returns strictly in sequence, stopping at the first non-zero exit. Plan D8: a return or start
state whose ``statefp.lineage`` is not organic/promoted is refused; no state is ever edited here.
"""
from __future__ import annotations

import os
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from pokeagent import statefp
from pokeagent.goexplore import select, store

DEFAULT_STEPS = 600          # plan D6: steps per return (a flag on the tool)
LINEAGES_OK = ("organic", "promoted")   # plan D8: the driver refuses to start from anything else
REPO_ROOT = Path(__file__).resolve().parents[3]   # the checkout root (same idiom as grind/measure.py)


@dataclass(frozen=True)
class Return:
    index: int
    cid: str | None          # the archived cell returned to; None for the first run from the start state
    state: Path              # the state file handed to explore_demo --state
    steps_offset: int        # Entry.steps of the cell (0 for the start state)
    seed: int                # base_seed + index (plan D1 mitigation: a cell is not replayed identically)


def pick(root: Path, start_state: Path, index: int, base_seed: int, commit: bool = True) -> Return:
    """Choose the cell this return goes back to; ``commit`` marks it seen and saves (pre-launch only)."""
    archive = store.load(root)
    cid = None
    if archive.entries:
        cid = select.choose(archive, random.Random(base_seed + index))   # no on_route: no planner here
        e = archive.entries[cid]     # the return cell MUST be archived: a KeyError here is a bug
        state, offset = Path(root) / e.state, e.steps
    else:
        state, offset = Path(start_state), 0
    if not state.is_file():
        raise FileNotFoundError(state)
    lin = statefp.lineage(state)
    if lin not in LINEAGES_OK:
        raise ValueError(f"return state {state} has lineage {lin!r}, not one of {LINEAGES_OK}")
    if cid is not None and commit:
        archive.mark_seen(cid)
        store.save(archive, root)
    return Return(index, cid, state, offset, base_seed + index)


def command(r: Return, root: Path, steps: int = DEFAULT_STEPS, stop_goal: str | None = None,
            python: str = sys.executable) -> list[str]:
    """The explore_demo argv for one return; ``--cell-from``/``--cell-steps`` only for an archived cell."""
    argv = [python, "tools/explore_demo.py", "--headless", "--state", str(r.state),
            "--steps", str(steps), "--seed", str(r.seed), "--cell-dump", str(root)]
    if stop_goal:
        argv += ["--stop-at-goal", stop_goal]
    if r.cid is not None:
        argv += ["--cell-from", r.cid, "--cell-steps", str(r.steps_offset)]
    return argv


def drive(root: Path, start_state: Path, returns: int, steps: int = DEFAULT_STEPS, base_seed: int = 0,
          stop_goal: str | None = None, run=subprocess.run) -> list[int]:
    """Serial returns on one archive root; stops at the first non-zero exit. Never saves the archive."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "driver.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(f"another driver holds {lock}; if no driver is running, remove that file")
    try:
        os.write(fd, str(os.getpid()).encode())
        codes: list[int] = []
        for i in range(returns):
            r = pick(root, start_state, i, base_seed)
            code = run(command(r, root, steps, stop_goal), cwd=REPO_ROOT).returncode
            # the reload also proves the Harvester's archive is still readable: ValueError stops us
            print(f"return {i} cid={r.cid} offset={r.steps_offset} seed={r.seed} "
                  f"exit={code} cells={len(store.load(root))}")
            codes.append(code)
            if code != 0:
                break
        return codes
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)
