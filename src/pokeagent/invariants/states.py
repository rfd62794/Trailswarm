"""Check 3: checkpoints (runs/checkpoints) and segment states (runs/segments/states).

Static: respawn-behind ship states (checkpoint_goals.respawn_behind) and discovery states sitting where segment code
reads them. ``--load-states`` additionally loads each state in ONE headless PyBoy and compares RAM with the sidecar.
"""
from __future__ import annotations

import re
from pathlib import Path

from pokeagent.checkpoint_goals import BEHIND_VERMILION, SHIP_GOALS, read_respawn, respawn_behind, sidecar
from pokeagent.invariants.findings import ERROR, INFO, Finding, fmt_map
from pokeagent.novelty.discoveries import is_discovery_state

MAP_ADDR, RESPAWN_ADDR = 0xD35E, 0xD719   # wCurMap, wLastBlackoutMap


def state_files(runs_dir: Path) -> list[Path]:
    out: list[Path] = []
    for d in (runs_dir / "checkpoints", runs_dir / "segments" / "states"):
        if d.is_dir():
            out += sorted(p for p in d.iterdir() if p.is_file() and p.name.endswith(".state"))
    return out


def label(path: Path) -> str:
    """Checkpoint name without extension tags: 'g@3c.best.state' -> 'g@3c'."""
    return re.sub(r"(\.best|\.cand)*\.state$", "", path.name)


def expected_maps(name: str) -> set[int] | None:
    """Map(s) a state called ``name`` should stand in: '<goal>@<hex>' = that map; a goal with a map detector = its maps."""
    if "@" in name:
        tail = name.split("@", 1)[1]
        return {int(tail, 16)} if re.fullmatch(r"[0-9a-fA-F]{1,2}", tail) else None
    from pokeagent import campaign
    spec = campaign.goal_spec(name)
    det = spec.get("detector") if spec else None
    return set(det["map"]) if isinstance(det, dict) and isinstance(det.get("map"), list) else None


def check_states(runs_dir: Path, rom: Path | None = None, load: bool = False) -> list[Finding]:
    files = state_files(runs_dir)
    out: list[Finding] = []
    for p in files:
        rel = p.relative_to(runs_dir).as_posix()
        if is_discovery_state(p):
            out.append(Finding("states", ERROR, "discovery_as_checkpoint",
                               f"{rel}: a discovery (possibly glitch-corrupted) state is where checkpoints are read",
                               {"file": rel}))
        if respawn_behind(label(p), p):
            r = read_respawn(p)
            out.append(Finding("states", ERROR, "respawn_behind",
                               f"{rel}: ship segment but respawn map is {fmt_map(r)}, behind Vermilion (5)",
                               {"file": rel, "respawn": r}))
    if load and rom and files:
        out += _check_loaded(runs_dir, files, rom)
    elif load:
        out.append(Finding("states", INFO, "no_rom", "--load-states: ROM not found or no states, skipped"))
    return out


def _check_loaded(runs_dir: Path, files: list[Path], rom: Path) -> list[Finding]:
    from pokeagent.emulator import PyBoyEmulator
    out: list[Finding] = []
    emu = PyBoyEmulator(rom, headless=True)   # ONE emulator, states loaded one at a time
    try:
        for p in files:
            ship = label(p).split("@", 1)[0] in SHIP_GOALS
            if is_discovery_state(p) or not (sidecar(p).exists() or ship):
                continue   # ship states are loaded even without a sidecar: the RAM is the only record
            rel = p.relative_to(runs_dir).as_posix()
            try:
                emu.load_state(p)
                cur, resp = emu.read(MAP_ADDR), emu.read(RESPAWN_ADDR)
            except Exception as e:  # a corrupt state is itself a finding
                out.append(Finding("states", ERROR, "state_unloadable", f"{rel}: {type(e).__name__}: {e}", {"file": rel}))
                continue
            want = expected_maps(label(p))
            if want is not None and cur not in want:
                out.append(Finding("states", ERROR, "label_map_mismatch",
                                   f"{rel}: label says map {'/'.join(fmt_map(m) for m in sorted(want))}, RAM 0xD35E says {fmt_map(cur)}",
                                   {"file": rel, "ram_map": cur, "expected": sorted(want)}))
            if ship and resp in BEHIND_VERMILION and read_respawn(p) not in BEHIND_VERMILION:
                out.append(Finding("states", ERROR, "respawn_behind",
                                   f"{rel}: ship segment; RAM 0xD719 says respawn is {fmt_map(resp)}, behind Vermilion (5)"
                                   + ("" if sidecar(p).exists() else " (no sidecar)"), {"file": rel, "respawn": resp, "source": "ram"}))
            rec = read_respawn(p)
            if rec is not None and rec != resp:
                out.append(Finding("states", ERROR, "sidecar_respawn_mismatch",
                                   f"{rel}: sidecar respawn {fmt_map(rec)} but RAM 0xD719 says {fmt_map(resp)}",
                                   {"file": rel, "sidecar": rec, "ram": resp}))
    finally:
        emu.close()
    return out
