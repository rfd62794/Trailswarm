"""Run every check over a runs/ directory and render the results. Read-only."""
from __future__ import annotations

from pathlib import Path

from pokeagent.invariants.findings import ERROR, INFO, WARN, Finding

CHECKS = ("warps", "milestones", "states", "segments", "tables")


def find_rom(runs_dir: Path) -> Path | None:
    from pokeagent.legs.grid import rom_path
    return rom_path(runs_dir.parent / "roms" / "Pokemon Red.gb")


def run_all(runs_dir: Path, load_states: bool = False, rom: Path | None = None) -> list[Finding]:
    from pokeagent.invariants.milestones import check_milestones
    from pokeagent.invariants.segments import check_segments
    from pokeagent.invariants.states import check_states
    from pokeagent.invariants.tables import check_tables
    from pokeagent.invariants.warps import check_warps
    runs_dir = Path(runs_dir)
    rom = rom or find_rom(runs_dir)
    valid = None
    if rom:
        from pokeagent.atlas import rom_maps
        valid = rom_maps.valid_map_ids(rom)
    return (check_warps(runs_dir / "maps.json", rom) + check_milestones(runs_dir)
            + check_states(runs_dir, rom, load_states) + check_segments(runs_dir, valid) + check_tables(runs_dir))


def has_errors(findings: list[Finding]) -> bool:
    return any(f.level == ERROR for f in findings)


def summary_table(findings: list[Finding], top: int = 2) -> str:
    rows = [f"{'check':11s} {'status':6s} {'count':>5s}  top examples"]
    for c in CHECKS:
        fs = [f for f in findings if f.check == c and f.level != INFO]
        status = ERROR if any(f.level == ERROR for f in fs) else WARN if fs else "OK"
        ex = "; ".join(f.message for f in fs[:top])
        rows.append(f"{c:11s} {status:6s} {len(fs):5d}  {ex}")
    infos = [f for f in findings if f.level == INFO]
    if infos:
        rows.append("info: " + "; ".join(f.message for f in infos[:5]))
    return "\n".join(rows)
