"""Survival-of-the-fittest controller over parallel RL learners.

    uv run python tools/rl_gauntlet.py --agents 4 --base-port 8890 --interval 120

Spawns --agents rl_train learners on consecutive frame ports. Every --interval
seconds it reads each agent's runs/rlstatus_<port>.json, keeps the champion,
and respawns the weakest learner as its offspring (--load-q the champion's
table, fresh seed). Watch the population in tools/watch.py --ports <base>-<end>.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def status(port: int) -> dict:
    try:
        return json.loads(Path(f"runs/rlstatus_{port}.json").read_text())
    except Exception:
        return {}


def spawn(port: int, seed: int, sire: Path | None, tag: str, a) -> subprocess.Popen:
    cmd = [sys.executable, "tools/rl_train.py", "--segment", a.segment,
           "--episodes", str(a.episodes), "--evals", "0", "--max-steps", str(a.max_steps),
           "--frame-port", str(port), "--seed", str(seed), "--publish-every", str(a.publish_every),
           "--save-q", f"runs/q_table_{port}.json", "--tag", tag]
    if sire:
        cmd += ["--load-q", str(sire)]
    return subprocess.Popen(cmd, cwd=".", stdout=open(f"runs/rl-{port}.log", "a"), stderr=subprocess.STDOUT)


def child_tag(parent: str, spawn_count: int) -> str:
    """a -> a1, a1 -> a1c, a1c -> a1c4: alternate digit and letter suffixes by depth."""
    suffix = str(spawn_count) if not parent[-1].isdigit() else chr(ord("a") + spawn_count - 1)
    return parent + suffix


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=4)
    ap.add_argument("--base-port", type=int, default=8890)
    ap.add_argument("--segment", default="left_house")
    ap.add_argument("--episodes", type=int, default=400)
    ap.add_argument("--max-steps", type=int, default=400)
    ap.add_argument("--publish-every", type=int, default=16)
    ap.add_argument("--interval", type=float, default=120.0, help="seconds between culls")
    a = ap.parse_args()

    Path("runs").mkdir(exist_ok=True)
    gen = 0
    proc: dict[int, subprocess.Popen] = {}
    tags: dict[int, str] = {}
    children: dict[str, int] = {}  # tag -> how many offspring it has sired
    ports = list(range(a.base_port, a.base_port + a.agents))
    for i, p in enumerate(ports):
        tags[p] = chr(ord("a") + i)  # founders: a, b, c, d, ...
        proc[p] = spawn(p, gen * 100 + p, None, tags[p], a)
    print(f"[gauntlet] {a.agents} learners on ports {ports[0]}-{ports[-1]}, cull every {a.interval:.0f}s", flush=True)

    while True:
        time.sleep(a.interval)
        stats = {p: status(p) for p in ports}
        # fitness: wins first, then best steps (lower is fitter), then total steps as tiebreak
        def fitness(p: int):
            s = stats[p]
            return (s.get("wins", 0), -s.get("steps_best", 10**9), -s.get("steps_total", 0))
        champion = max(ports, key=fitness)
        runt = min(ports, key=fitness)
        if champion == runt:
            continue
        sire = Path(f"runs/q_table_{champion}.json")
        if not sire.exists():
            continue
        try:
            proc[runt].kill()
        except Exception:
            pass
        gen += 1
        champ_tag = tags[champion]
        children[champ_tag] = children.get(champ_tag, 0) + 1
        tags[runt] = child_tag(champ_tag, children[champ_tag])
        print(f"[gen {gen}] cull :{runt} '{tags.get(runt,'')}' dead (wins {stats[runt].get('wins',0)}), "
              f"new '{tags[runt]}' sired by '{champ_tag}' (wins {stats[champion].get('wins',0)}, "
              f"best {stats[champion].get('steps_best','-')})", flush=True)
        proc[runt] = spawn(runt, gen * 100 + runt, sire, tags[runt], a)


if __name__ == "__main__":
    raise SystemExit(main())
