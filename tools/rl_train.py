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
import hashlib
import subprocess
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

from pokeagent.observations import SpatialObserver, schema_id
from pokeagent.qmodels import atomic_json, load_model, mean_tables, save_model
from pokeagent.learning import potential_reward

from rl_env import ACTIONS, EXTRA_OBS, GOAL_FNS, SEGMENT_STATES, SEGMENT_SUBGOALS, SegmentEnv


def run_episode(env, policy, rng, pub_fps: float = 15.0) -> tuple[bool, int]:
    obs = env.reset()
    last_pub = 0.0
    for _ in range(env.max_steps):
        obs, _r, done, _ = env.step(policy(obs, rng))
        now = time.time()
        if now - last_pub >= 1.0 / pub_fps:  # wall-clock pacing: tile fps is independent of step rate
            env.publish()
            last_pub = now
        if done:
            break
    return env.goal_reached, env.steps


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
                    help="deprecated; rendering is now wall-clock paced by --publish-fps")
    ap.add_argument("--publish-fps", type=float, default=15.0,
                    help="tile updates per second, independent of step rate (rendering quality stays fixed)")
    ap.add_argument("--save-q", default=None, help="write the Q table here every episode (gauntlet picks champions)")
    ap.add_argument("--load-q", default=None, help="seed the Q table from a saved table (offspring of a champion)")
    ap.add_argument("--eps-floor", type=float, default=0.1, help="never stop exploring below this rate")
    ap.add_argument("--tag", default="", help="lineage tag shown on the tile (gauntlet assigns e.g. a, a1, a1c)")
    ap.add_argument("--novelty", type=float, default=0.0, help="first-visit reward, capped at 0.2 total per episode")
    ap.add_argument("--publish-frames", action="store_true",
                    help="render+publish every settle frame (frame-for-frame showcase; only with frame-port)")
    ap.add_argument("--full-res", action="store_true",
                    help="publish native 160x144 frames instead of half-res 80x72 (showcase quality; ~4x transport cost)")
    ap.add_argument("--share-every", type=int, default=0,
                    help="every N episodes merge own Q into the per-segment community pool (runs/qshare/) and adopt the max-merge")
    ap.add_argument("--n-step", type=int, default=1,
                    help="n-step return horizon (1 = classic one-step); >1 propagates reward faster through sparse chains")
    ap.add_argument("--screen-context", action="store_true")
    ap.add_argument("--menu-controls", action="store_true")
    ap.add_argument("--spatial-context", action="store_true")
    ap.add_argument("--combat-context", action="store_true")
    ap.add_argument("--battle-learning", action="store_true")
    ap.add_argument("--travel-priority", action="store_true")
    ap.add_argument("--maps", default="runs/maps.json")
    ap.add_argument("--potential-shaping", action="store_true")
    ap.add_argument("--double-q", action="store_true",
                    help="Double Q-learning: two tables, select-with-one/evaluate-with-other (reduces overestimation)")
    ap.add_argument("--trace", action="store_true",
                    help="append every episode's (obs,act) path to runs/traces/<segment>_<id>.jsonl for run-level analysis")
    ap.add_argument("--throttle-ms", type=float, default=0.0,
                    help="sleep this many ms per step (resource management: unthrottled envs eat a core each)")
    a = ap.parse_args()

    if a.battle_learning:
        a.screen_context = a.combat_context = True
    if a.menu_controls or a.segment == 'menu_start':
        a.screen_context = a.menu_controls = True
    if a.n_step < 1 or a.max_steps < 1 or a.episodes < 1 or a.evals < 0 or a.publish_fps <= 0 or a.novelty < 0:
        ap.error('Invalid episode, horizon, FPS or novelty setting')
    if a.screen_context or a.spatial_context or a.combat_context or a.battle_learning:
        if a.load_q and not Path(a.load_q).exists():
            ap.error('Requested model does not exist')
    from pokeagent.emulator import Button
    actions = list(ACTIONS) + ([Button.START, Button.SELECT] if a.menu_controls else [])
    rng = random.Random(a.seed)
    if a.frame_port is not None:  # register for tools/rl_admin.py --reap (stale-learner fix)
        try:
            import atexit, os
            reg_p = Path("runs/rl_agents.json")
            reg = json.loads(reg_p.read_text()) if reg_p.exists() else {}
            reg[str(a.frame_port)] = {"pid": os.getpid(), "tag": a.tag, "segment": a.segment,
                                      "cmd": sys.argv[1:]}  # rl_cull replays this to respawn the learner
            reg_p.write_text(json.dumps(reg, indent=1))
            def _unreg(p=reg_p, port=str(a.frame_port)):
                try:
                    r = json.loads(p.read_text()); r.pop(port, None); p.write_text(json.dumps(r, indent=1))
                except Exception:
                    pass
            atexit.register(_unreg)
        except Exception:
            pass
    start = a.state or next((s for s in SEGMENT_STATES[a.segment] if Path(s).exists()),
                            SEGMENT_STATES[a.segment][-1])
    from rl_env import curriculum_subgoals
    env = SegmentEnv(a.rom, start, GOAL_FNS[a.segment], goal_name=a.segment,
                     subgoals=tuple(SEGMENT_SUBGOALS.get(a.segment, ())) + tuple(curriculum_subgoals(a.segment)),
                     max_steps=a.max_steps, hold=a.hold, settle=a.settle,
                     windowed=a.window, speed=a.speed, frame_port=a.frame_port,
                     publish_frames=a.publish_frames, half_res=not a.full_res,
                     obs_extra=EXTRA_OBS.get(a.segment), screen_context=a.screen_context)
    env.actions = actions
    env.battle_learning = a.battle_learning
    env.travel_priority = a.travel_priority
    env.combat_context = a.combat_context
    observer = SpatialObserver(a.maps) if a.spatial_context or a.potential_shaping else None
    env.spatial_observer = observer if a.spatial_context else None
    schema = schema_id(a.segment, screen=a.screen_context, spatial=a.spatial_context,
                       combat=a.combat_context, battle_learning=a.battle_learning,
                       travel_priority=a.travel_priority, potential=a.potential_shaping,
                       hold=a.hold, settle=a.settle, maps_digest=observer.digest if observer else '',
                       novelty=a.novelty, menu_controls=a.menu_controls)
    phi = None
    if a.potential_shaping:
        from navgrid import load_grids, distance_field, potential
        targets = {'to_viridian': 1, 'to_route2': 13, 'to_pewter': 2, 'to_gym': 54}
        goals = [('map', targets[a.segment])] if a.segment in targets else [('!house',)] if a.segment in ('left_house', 'exit_potion') else []
        if not goals:
            env.close()
            ap.error('Potential shaping requires a supported navigation goal')
        phi = potential(distance_field(load_grids(a.maps), goals), default=0.0)
    Q: dict[tuple, list[float]] = defaultdict(lambda: [0.0] * len(actions))
    if a.load_q:  # offspring: start from a champion's table
        try:
            for k, v in load_model(a.load_q, schema, len(actions)).items():
                Q[k] = v  # keys are (map,x,y) tuples serialized as repr strings
        except (ValueError, OSError, TypeError) as e:
            env.close()
            ap.error(str(e))
    QB = defaultdict(lambda: [0.0] * len(actions)) if a.double_q else None
    if QB is not None:  # warm-start both estimators from the same inherited table
        for k, v in Q.items():
            QB[k] = list(v)

    def snapshot() -> dict:  # the shared/saved artifact: single table (mean of the two estimators under --double-q)
        if QB is None:
            return {repr(k): v for k, v in Q.items()}
        return {repr(k): [(Q[k][i] + QB[k][i]) / 2 for i in range(len(actions))]
                for k in set(Q) | set(QB)}
    alpha, gamma, eps0 = 0.2, 0.99, 1.0
    try:
        wins = first_ep = None
        wins = 0
        steps_log: list[int] = []
        win_steps: list[int] = []  # solved-episode steps only: the number that shows learning
        visits: dict[tuple, int] = defaultdict(int)
        total_steps = 0
        for ep in range(a.episodes):
            eps = max(a.eps_floor, eps0 * (1.0 - ep / max(1, a.episodes)))  # decay, but never stop exploring
            obs = env.reset()
            last_pub = 0.0
            traj = []  # n-step buffer: (s, a, r, s')
            ep_path = []  # full (obs, act) record for --trace run-level analysis
            novelty_budget = 0.2
            reward_components = {'extrinsic': 0.0, 'novelty': 0.0, 'potential': 0.0}
            for _ in range(env.max_steps):
                allowed = env.allowed_actions()
                if QB is not None:
                    qs = [x + y for x, y in zip(Q[obs], QB[obs])]
                    act = (rng.choice(allowed) if rng.random() < eps
                           else max(allowed, key=lambda i: qs[i]))
                else:
                    act = (rng.choice(allowed) if rng.random() < eps
                           else max(allowed, key=lambda i: Q[obs][i]))
                ep_path.append(list(obs) + [act])
                nxt, rew, done, info = env.step(act)
                reward_components['extrinsic'] += rew
                if phi:
                    shaping = 0.01 * potential_reward(phi(obs), phi(nxt), gamma, info['terminated'])
                    rew += shaping
                    reward_components['potential'] += shaping
                now = time.time()
                if now - last_pub >= 1.0 / a.publish_fps:  # wall-clock pacing, not step pacing
                    env.publish()
                    last_pub = now
                visits[nxt] += 1
                if visits[nxt] == 1:
                    bonus = min(a.novelty, novelty_budget)
                    rew += bonus  # first-visit bonus only: rewarding every visit paid wandering
                    novelty_budget -= bonus
                    reward_components['novelty'] += bonus
                traj.append((obs, act, rew, nxt))
                terminal = info['terminated']  # goal ends bootstrap to 0; step-cap truncation still bootstraps
                while traj and (len(traj) >= a.n_step or done):
                    s0, a0 = traj[0][0], traj[0][1]
                    L = len(traj)
                    G = sum((gamma ** i) * r for i, (_, _, r, _) in enumerate(traj))
                    T = (Q if rng.random() < 0.5 else QB) if QB is not None else Q
                    if not terminal:
                        boot = traj[-1][3]
                        if QB is not None:
                            S = QB if T is Q else Q
                            a_star = max(range(len(actions)), key=lambda i: T[boot][i])
                            G += (gamma ** L) * S[boot][a_star]
                        else:
                            G += (gamma ** L) * max(Q[boot])
                    T[s0][a0] += alpha * (G - T[s0][a0])
                    traj.pop(0)
                obs = nxt
                if done:
                    break
                if a.throttle_ms:
                    time.sleep(a.throttle_ms / 1000)
            steps_log.append(env.steps)
            total_steps += env.steps
            won = env.goal_reached  # episode ended by reaching the goal, not the step cap
            if won:
                wins += 1
                win_steps.append(env.steps)
                if first_ep is None:
                    first_ep = ep
                print(f"  ep {ep}: SOLVED in {env.steps} steps" + (" (first success!)" if ep == first_ep else ""), flush=True)
            if a.trace and ep_path:
                try:
                    Path("runs/traces").mkdir(exist_ok=True)
                    tid = a.frame_port if a.frame_port is not None else a.seed
                    with open(f"runs/traces/{a.segment}_{tid}.jsonl", "a") as tf:
                        tf.write(json.dumps({"ep": ep, "steps": env.steps, "won": won,
                                             "path": ep_path, "final_obs": list(obs), "schema": schema,
                                             "outcomes": env.battle_outcomes, "rewards": reward_components}) + "\n")
                except Exception:
                    pass
            if a.save_q:
                save_model(a.save_q, snapshot(), schema, len(actions))
            if a.share_every and (ep + 1) % a.share_every == 0:
                try:  # collective: publish own table, adopt element-wise max over the per-segment pool
                    sdir = Path('runs/qshare') / schema
                    sdir.mkdir(parents=True, exist_ok=True)
                    lid = str(a.frame_port if a.frame_port is not None else a.seed)
                    mine = sdir / f'{a.segment}_{lid}.json'
                    save_model(mine, snapshot(), schema, len(actions))
                    tables = []
                    for f in sdir.glob(f'{a.segment}_*.json'):
                        try:
                            tables.append(load_model(f, schema, len(actions)))
                        except (ValueError, OSError, TypeError):
                            continue
                    for k, v in mean_tables(tables).items():
                        Q[k] = [(x+y)/2 for x, y in zip(Q[k], v)]
                        if QB is not None:
                            QB[k] = [(x+y)/2 for x, y in zip(QB[k], v)]
                except Exception:
                    pass
            if a.frame_port is not None:
                best = min(steps_log); worst = max(steps_log)
                atomic_json(f'runs/rlstatus_{a.frame_port}.json', {"instance": a.frame_port, "tag": a.tag, "generation": ep, "wins": wins,
                           "schema": schema, "actions": len(actions), "outcomes": env.battle_outcomes, "rewards": reward_components,
                           "steps_total": total_steps, "steps_avg": round(total_steps / len(steps_log), 1),
                           "steps_best": best, "steps_worst": worst,
                           "win_avg": round(sum(win_steps) / len(win_steps), 1) if win_steps else None})
            if (ep + 1) % 25 == 0:
                print(f"  ep {ep + 1}: {wins} solves so far" + (f" (first at ep {first_ep})" if first_ep is not None else ", none yet"), flush=True)
        def greedy(obs, _r):
            if QB is not None:
                return max(env.allowed_actions(), key=lambda i: Q[obs][i] + QB[obs][i])
            return max(env.allowed_actions(), key=lambda i: Q[obs][i])
        learned = [run_episode(env, greedy, rng, a.publish_fps) for _ in range(a.evals)]
        if learned:
            atomic_json(f'runs/eval_{a.segment}_{schema}.json',
                        {'version': 2, 'schema': schema, 'segment': a.segment,
                         'episodes': len(learned), 'wins': sum(w for w, _ in learned),
                         'source_state': str(start), 'epsilon': 0,
                         'success_definition': 2,
                         'git_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                         'model_digest': hashlib.sha256(json.dumps(snapshot(), sort_keys=True).encode()).hexdigest(),
                         'source_digest': hashlib.sha256(Path(start).read_bytes()).hexdigest(),
                         'evaluation_scope': 'fixed_checkpoint_greedy',
                         'steps': [s for w, s in learned if w]})
        rand = [run_episode(env, lambda o, r: r.choice(env.allowed_actions()), rng, a.publish_fps) for _ in range(a.evals)]
    finally:
        env.close()

    def rep(name, res):
        if not res:
            print(f'{name:8s} evaluation disabled')
            return
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
