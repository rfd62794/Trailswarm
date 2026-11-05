"""Tabular Q-learning on a short segment (exploration lane experiment 1).

    uv run python tools/rl_train.py --segment left_house --episodes 200 --evals 40

Trains epsilon-greedy Q on (map,x,y) observations, then reports:
  - learned greedy success rate and mean steps over --evals episodes
  - the same numbers for a random-policy baseline
A run that lands the goal inside --max-steps counts as a success.
"""
from __future__ import annotations

import argparse
import random
from collections import defaultdict

from rl_env import ACTIONS, GOAL_FNS, SEGMENT_STATES, SegmentEnv


def run_episode(env, policy, rng) -> tuple[bool, int]:
    obs = env.reset()
    for _ in range(env.max_steps):
        obs, _r, done, _ = env.step(policy(obs, rng))
        env.publish()  # no-op unless frame_shm is set
        if done:
            break
    return env.goal_fn(env.emu), env.steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", required=True, choices=sorted(GOAL_FNS))
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--evals", type=int, default=40)
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", default=None, help="override segment start state")
    ap.add_argument("--window", action="store_true", help="SDL window at realtime speed: watch every frame live")
    ap.add_argument("--speed", type=int, default=1, help="emulation speed with --window (0 = unthrottled)")
    ap.add_argument("--frame-port", type=int, default=None,
                    help="publish frames to pokeagent_frames_<port> so tools/watch.py can tile this run")
    ap.add_argument("--hold", type=int, default=8)
    ap.add_argument("--settle", type=int, default=8)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    env = SegmentEnv(a.rom, a.state or SEGMENT_STATES[a.segment], GOAL_FNS[a.segment],
                     max_steps=a.max_steps, hold=a.hold, settle=a.settle,
                     windowed=a.window, speed=a.speed, frame_port=a.frame_port)
    Q: dict[tuple, list[float]] = defaultdict(lambda: [0.0] * len(ACTIONS))
    alpha, gamma, eps0 = 0.2, 0.99, 1.0
    try:
        for ep in range(a.episodes):
            eps = eps0 * (1.0 - ep / max(1, a.episodes))  # linear decay to ~0
            obs = env.reset()
            for _ in range(env.max_steps):
                act = rng.randrange(len(ACTIONS)) if rng.random() < eps else max(range(len(ACTIONS)), key=lambda i: Q[obs][i])
                nxt, rew, done, _ = env.step(act)
                env.publish()  # no-op unless frame_shm is set
                q = Q[obs]
                q[act] += alpha * (rew + gamma * max(Q[nxt]) - q[act])
                obs = nxt
                if done:
                    break
        learned = [run_episode(env, lambda o, r: max(range(len(ACTIONS)), key=lambda i: Q[o][i]), rng)
                   for _ in range(a.evals)]
        rand = [run_episode(env, lambda o, r: r.randrange(len(ACTIONS)), rng) for _ in range(a.evals)]
    finally:
        env.close()

    def rep(name, res):
        hits = [s for s, n in res if s]
        steps = [n for s, n in res if s]
        print(f"{name:8s} success {len(hits)}/{len(res)} = {len(hits)/len(res):.0%}"
              + (f"  steps mean {sum(steps)/len(steps):.0f} best {min(steps)}" if steps else ""))

    print(f"segment {a.segment}: trained {a.episodes} eps, states seen {len(Q)}")
    rep("learned", learned)
    rep("random", rand)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
