"""Wiring for explore_demo.py / explore_headless.py: ``plan`` resolves a drill's start state and step budget before the emulator
loads; ``attach`` hangs the leg-state saver and the drill monitor on the context. Both scripts share it."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pokeagent.legs import drill as D
from pokeagent.legs import states as S


@dataclass
class Plan:
    kind: str                      # "leg" | "grind"
    state: Path
    steps: int
    spec: D.DrillSpec | None = None
    par: float | None = None
    grind_map: int | None = None

    def meta(self) -> dict:
        return {"kind": self.kind, "leg": self.spec.text if self.spec else None, "map": self.grind_map or (self.spec.map if self.spec else None),
                "state": str(self.state), "par_frames": self.par, "budget_steps": self.steps}


def refuse_discovery(path: Path) -> None:
    from pokeagent.novelty.discoveries import is_discovery_state
    if is_discovery_state(path):
        raise SystemExit(f"refusing to start a drill from a discovery state: {path}")


def plan(drill_leg: str | None, drill_grind: int | None, drill_steps: int, states_dir: str | Path, rom: str | Path | None,
         explicit_state: str | Path | None = None) -> Plan | None:
    """None when no drill was asked for. Raises SystemExit with the reason when the drill cannot start."""
    if not drill_leg and drill_grind is None:
        return None
    sd = Path(states_dir)
    if drill_leg:
        spec = D.parse(drill_leg)
        state = Path(explicit_state) if explicit_state else S.newest(sd, spec.map, *spec.entry)
        if state is None or not Path(state).is_file():
            raise SystemExit(f"no entry state for {spec.text} in {sd} (run with --save-leg-states first)")
        refuse_discovery(state)
        par = D.par_frames_for(spec, rom)
        if par is None:
            raise SystemExit(f"no par for {spec.text} (ROM missing or the exit is unreachable from the entry)")
        return Plan("leg", Path(state), D.budget_steps(par), spec, par)
    state = Path(explicit_state) if explicit_state else S.newest_on_map(sd, drill_grind)
    if state is None or not Path(state).is_file():
        raise SystemExit(f"no saved state on map {drill_grind} in {sd} (run with --save-leg-states first)")
    refuse_discovery(state)
    return Plan("grind", Path(state), drill_steps, grind_map=drill_grind)


def attach(ctx, pl: Plan | None, save_states: bool, states_dir: str | Path, start_state: str | Path | None = None,
           runs_dir: str | Path = "runs", drills_log: str | Path | None = None, grind_log: str | Path | None = None) -> None:
    """Hang the hooks on ``ctx``. The saver is refused for runs that started from a discovery state."""
    if save_states and not (start_state and _is_discovery(start_state)):
        ctx.leg_saver = S.LegStateSaver(states_dir, S.route_maps(runs_dir))
    if pl is None:
        return
    D.write_meta(ctx.run_dir, {"drill": pl.meta()})
    ctx.opts.steps = pl.steps + 2   # the monitor ends the run at pl.steps; the plain step cap must not preempt its record
    if pl.kind == "leg":
        ctx.drill = D.DrillMonitor(pl.spec, pl.par, pl.steps, ctx.run_dir, Path(drills_log) if drills_log else D.DRILLS_LOG)
    else:
        from pokeagent.grind.drill import GRIND_LOG, GrindDrillMonitor
        ctx.opts.drill_grind = pl.grind_map
        ctx.drill = GrindDrillMonitor(pl.grind_map, pl.steps, ctx.run_dir, Path(grind_log) if grind_log else GRIND_LOG)


def _is_discovery(path) -> bool:
    from pokeagent.novelty.discoveries import is_discovery_state
    return is_discovery_state(path)


def add_args(ap) -> None:
    """The CLI flags both explore scripts take."""
    ap.add_argument("--save-leg-states", action="store_true", help="save a state on each calm map entry on the curriculum route (runs/legs/states)")
    ap.add_argument("--leg-states-dir", default=str(S.STATES_DIR), help="where leg entry states live")
    ap.add_argument("--drill-leg", default=None, metavar="MAP:X,Y->X,Y", help="drill ONE leg from its saved entry state; stops at the exit tile / map change")
    ap.add_argument("--drill-grind", type=lambda v: int(v, 0), default=None, metavar="MAP", help="grind drill: start from a saved state on this map, grind its grass")
    ap.add_argument("--drill-steps", type=int, default=600, help="grind drill length in steps (leg drills use 3 x par)")
    ap.add_argument("--drills-log", default=None, help="leg drill result log (default runs/legs/drills.jsonl)")
    ap.add_argument("--grind-drills-log", default=None, help="grind drill result log (default runs/legs/grind_drills.jsonl)")
