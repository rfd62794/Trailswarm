"""Query the drained game knowledge (a stand-in for `pokeagent brain lessons moves` until Brain Tools is merged).

    uv run python tools/knowledge.py moves [NAME...]      every move (or the named ones) with describe() and what the agent observed
    uv run python tools/knowledge.py catch PIDGEY          where can I catch X
    uv run python tools/knowledge.py train 12              species and levels on map 12 (0x0C = Route 1)
    uv run python tools/knowledge.py trainer BROCK         what a trainer class uses; `map 59` lists a map's trainers
    uv run python tools/knowledge.py ready beat_brock STATE   headless: party readiness at STATE (a .state) vs a boss goal

`moves` reads observations from the explorer memory (--memory FILE, default none): learned damage per (species:move).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pokeagent.knowledge import encounters, trainers  # noqa: E402
from pokeagent.knowledge.kb import ROM_KB  # noqa: E402
from pokeagent.knowledge.moves import describe  # noqa: E402


def observed(memory_file: str | None) -> dict:
    if not memory_file or not Path(memory_file).exists():
        return {}
    data = json.loads(Path(memory_file).read_text(encoding="utf-8"))
    return data.get("move_damage", {})


def cmd_moves(args: list[str], memory: str | None) -> None:
    obs = observed(memory)
    want = {a.upper() for a in args}
    for mv in ROM_KB["moves"].values():
        if want and mv["name"] not in want:
            continue
        seen = [f"{k.split(':')[0]}:{sum(v) / len(v):.0f}dmg" for k, v in obs.items() if k.endswith(":" + mv["name"]) and v]
        print(describe(mv) + (f"  [observed {', '.join(seen)}]" if seen else ""))


def cmd_ready(goal: str, state: str) -> None:
    from pokeagent.emulator import PyBoyEmulator
    from pokeagent.knowledge.party import our_party
    from pokeagent.knowledge.readiness import assess
    boss = trainers.boss_party(goal) or trainers.strongest_on_mt_moon()
    emu = PyBoyEmulator(Path("roms/Pokemon Red.gb"), headless=True)
    try:
        emu.load_state(Path(state))
        party = our_party(emu)
        print("party:", [(c.name, c.level, c.hp, c.stats, c.moves) for c in party])
        print("boss:", boss)
        r = assess(party, boss, goal.replace("beat_", "").upper())
        print(r)
    finally:
        emu.close()


def main(argv: list[str]) -> int:
    memory = None
    if "--memory" in argv:
        i = argv.index("--memory"); memory = argv[i + 1]; del argv[i:i + 2]
    cmd, rest = (argv[0] if argv else "moves"), argv[1:]
    if ROM_KB is None:
        print("kb/rom_tables.json missing: run tools/rom_tables.py first"); return 1
    if cmd == "moves":
        cmd_moves(rest, memory)
    elif cmd == "catch":
        print("\n".join(encounters.train_vs(" ".join(rest))) or "not found in the wild")
    elif cmd == "train":
        for sp, (lo, hi, p) in encounters.species_on(int(rest[0], 0)).items():
            print(f"{sp}: L{lo}-{hi} ({p * 100:.0f}%)")
    elif cmd == "trainer":
        print(trainers.what_does_use(" ".join(rest)))
    elif cmd == "map":
        for t in trainers.trainers_on(int(rest[0], 0)):
            print(t["class"], "party", t["party"], t["mons"], "at", (t["x"], t["y"]))
    elif cmd == "ready":
        cmd_ready(rest[0], rest[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
