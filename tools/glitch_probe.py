"""Glitch probe CLI: run the trainer-escape recipe or a trainer sight survey, headless only.

    uv run python tools/glitch_probe.py repro --state S [--script j] [--allow-placeholder] [--name N]
    uv run python tools/glitch_probe.py survey --state S --map ID [--name N]

The input state is copied to scratch first (never opened for writing); the JSONL report and any
kept save state land under the runs dir's discoveries directory. Prints one JSON summary line (the verdict or
the survey summary) plus the report path. Exit 0 clean, 2 on usage error (missing state, bad
script, placeholder steps), 1 on an aborted run. Importing this module never starts an emulator.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pokeagent.emulator import PyBoyEmulator  # noqa: E402
from pokeagent.glitchlab import scratch, survey, trainer_escape  # noqa: E402
from pokeagent.glitchlab.script import load_script  # noqa: E402
from pokeagent.novelty.discoveries import DIR_NAME, STATE_SUFFIX  # noqa: E402


def pyboy_factory(rom):
    """emu_factory for real runs: boot headless, tick, load the scratch state copy, settle."""
    def make(state_path):
        emu = PyBoyEmulator(Path(rom), headless=True)
        emu.tick(60)
        emu.load_state(Path(state_path))
        emu.tick(30)
        return emu
    return make


def _repro(a, make_emu) -> int:
    state = Path(a.state)
    if not state.is_file():
        print(f"missing state: {state}", file=sys.stderr)
        return 2
    try:
        work_state = scratch.scratch_copy(state, Path(a.runs_dir) / DIR_NAME)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    steps = None
    if a.script:
        try:
            steps = load_script(json.loads(Path(a.script).read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"bad script {a.script}: {e}", file=sys.stderr)
            return 2
    report = scratch.report_path(a.runs_dir, a.name)
    report.parent.mkdir(parents=True, exist_ok=True)
    emu = make_emu(work_state)
    try:
        with report.open("w", encoding="utf-8") as fh:
            rows = trainer_escape.run_recipe(emu, steps, allow_placeholder=a.allow_placeholder,
                                             record=lambda row: fh.write(json.dumps(row) + "\n"))
        v = trainer_escape.verdict(rows)
        if v["instant_encounter"] is not None:   # the only state worth keeping: the instant battle
            emu.save_state(report.parent / f"{report.stem}-on_return{STATE_SUFFIX}")
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    finally:
        emu.close()
    print(json.dumps(v))
    print(f"report: {report}")
    return 1 if rows and rows[-1].get("aborted") else 0


def _survey(a, make_emu) -> int:
    state = Path(a.state)
    if not state.is_file():
        print(f"missing state: {state}", file=sys.stderr)
        return 2
    try:
        out = survey.survey_map(make_emu, state, a.map, None, out_dir=Path(a.runs_dir), name=a.name)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps(out))
    print(f"report: {out['report']}")
    return 1 if out.get("aborted") else 0


def main(argv=None, *, emu_factory=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("repro")
    r.add_argument("--state", required=True)
    r.add_argument("--script", help="JSON step list replacing the default RECIPE")
    r.add_argument("--allow-placeholder", action="store_true",
                   help="run even while placeholder steps remain (they are no-ops)")
    s = sub.add_parser("survey")
    s.add_argument("--state", required=True)
    s.add_argument("--map", type=lambda v: int(v, 0), required=True)
    for p in (r, s):
        p.add_argument("--rom", default=os.environ.get("POKEAGENT_ROM", "roms/Pokemon Red.gb"))
        p.add_argument("--runs-dir", default="runs")
        p.add_argument("--name", default=None, help="report name inside the discoveries dir")
    a = ap.parse_args(argv)
    make_emu = emu_factory or pyboy_factory(a.rom)
    if a.cmd == "repro":
        a.name = a.name or "repro"
        return _repro(a, make_emu)
    return _survey(a, make_emu)


if __name__ == "__main__":
    raise SystemExit(main())
