"""Tabular Q-learning on a short segment (exploration lane experiment 1).

    uv run python tools/rl_train.py --segment left_house --episodes 200 --evals 40

Trains epsilon-greedy Q on (map,x,y) observations, then reports:
  - learned greedy success rate and mean steps over --evals episodes
  - the same numbers for a random-policy baseline
A run that lands the goal inside --max-steps counts as a success.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict

from rl_env import ACTIONS, GOAL_FNS, SEGMENT_STATES, SegmentEnv


def run_episode(env, policy, rng, pub_every: int = 8) -> tuple[bool, int]:
    obs = env.reset()
    for _ in range(env.max_steps):
        obs, _r, done, _ = env.step(policy(obs, rng))
        if env.steps % pub_every == 0:
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
    ap.add_argument("--publish-every", type=int, default=8,
                    help="render+publish every Nth step to the frame slot (publish-per-step saturates the CPU)")
    ap.add_argument("--save-q", default=None, help="write the Q table here every episode (gauntlet picks champions)")
    ap.add_argument("--load-q", default=None, help="seed the Q table from a saved table (offspring of a champion)")
    ap.add_argument("--eps-floor", type=float, default=0.1, help="never stop exploring below this rate")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    env = SegmentEnv(a.rom, a.state or SEGMENT_STATES[a.segment], GOAL_FNS[a.segment],
                     max_steps=a.max_steps, hold=a.hold, settle=a.settle,
                     windowed=a.window, speed=a.speed, frame_port=a.frame_port)
    Q: dict[tuple, list[float]] = defaultdict(lambda: [0.0] * len(ACTIONS))
    if a.load_q:  # offspring: start from a champion's table
        try:
            for k, v in json.load(open(a.load_q)).items():
                Q[eval(k)] = v  # keys are (map,x,y) tuples serialized as repr strings
        except Exception as e:
            print(f"load-q failed: {e}")
    alpha, gamma, eps0 = 0.2, 0.99, 1.0
    try:
        wins = first_ep = None
        wins = 0
        steps_log: list[int] = []
        total_steps = 0
        for ep in range(a.episodes):
            eps = max(a.eps_floor, eps0 * (1.0 - ep / max(1, a.episodes)))  # decay, but never stop exploring
            obs = env.reset()
            for _ in range(env.max_steps):
                act = rng.randrange(len(ACTIONS)) if rng.random() < eps else max(range(len(ACTIONS)), key=lambda i: Q[obs][i])
                nxt, rew, done, _ = env.step(act)
                if env.steps % a.publish_every == 0:
                    env.publish()  # no-op unless frame_shm is set
                q = Q[obs]
                q[act] += alpha * (rew + gamma * max(Q[nxt]) - q[act])
                obs = nxt
                if done:
                    break
            steps_log.append(env.steps)
            total_steps += env.steps
            if env.goal_fn(env.emu):  # episode ended by reaching the goal, not the step cap
                wins += 1
                if first_ep is None:
                    first_ep = ep
                print(f"  ep {ep}: SOLVED in {env.steps} steps" + (" (first success!)" if ep == first_ep else ""), flush=True)
            if a.save_q:
                json.dump({repr(k): v for k, v in Q.items()}, open(a.save_q, "w"))
            if a.frame_port is not None:
                best = min(steps_log); worst = max(steps_log)
                json.dump({"instance": a.frame_port, "generation": ep, "wins": wins,
                           "steps_total": total_steps, "steps_avg": round(total_steps / len(steps_log), 1),
                           "steps_best": best, "steps_worst": worst},
                          open(f"runs/rlstatus_{a.frame_port}.json", "w"))
            if (ep + 1) % 25 == 0:
                print(f"  ep {ep + 1}: {wins} solves so far" + (f" (first at ep {first_ep})" if first_ep is not None else ", none yet"), flush=True)
        learned = [run_episode(env, lambda o, r: max(range(len(ACTIONS)), key=lambda i: Q[o][i]), rng, a.publish_every)
                   for _ in range(a.evals)]
        rand = [run_episode(env, lambda o, r: r.randrange(len(ACTIONS)), rng, a.publish_every) for _ in range(a.evals)]
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
