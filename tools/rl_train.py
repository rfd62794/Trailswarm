"""Tabular Q-learning on a short segment (exploration lane experiment 1).

    uv run python tools/rl_train.py --segment left_house --episodes 200 --evals 40

Trains epsilon-greedy Q on (map,x,y) observations, then reports:
  - learned greedy success rate and mean steps over --evals episodes
  - the same numbers for a random-policy baseline
A run that lands the goal inside --max-steps counts as a success.
"""
from __future__ import annotations

import argparse
import ast
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
from pokeagent.evaluation import evaluate_table, exploration_rate

from rl_env import ACTIONS, EXTRA_OBS, GOAL_FNS, SEGMENT_STATES, SEGMENT_SUBGOALS, SegmentEnv, make_goal


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
    ap.add_argument('--eval-every', type=int, default=10)
    ap.add_argument('--periodic-evals', type=int, default=3)
    ap.add_argument('--eval-state', action='append', default=[])
    ap.add_argument('--eps-decay-episodes', type=int, default=100)
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--rom", default="roms/Pokemon Red.gb")
    ap.add_argument("--state", action="append", default=None,
                    help="start checkpoint; repeat to cycle episodes/evaluations across states")
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
    if (a.n_step < 1 or a.max_steps < 1 or a.episodes < 1 or a.evals < 0
            or a.publish_fps <= 0 or a.novelty < 0 or a.hold < 1 or a.settle < 1
            or a.eval_every < 0 or a.periodic_evals < 1 or a.eps_decay_episodes < 1
            or not 0 <= a.eps_floor <= 1):
        ap.error('Invalid episode, horizon, FPS, control timing or exploration setting')
    if any(not Path(state).is_file() for state in a.eval_state):
        ap.error('An evaluation starting state does not exist')
    if a.screen_context or a.spatial_context or a.combat_context or a.battle_learning:
        if a.load_q and not Path(a.load_q).exists():
            ap.error('Requested model does not exist')
    from pokeagent.emulator import Button
    actions = list(ACTIONS) + ([Button.START, Button.SELECT] if a.menu_controls else [])
    rng = random.Random(a.seed)
    if a.frame_port is not None:  # register for tools/rl_admin.py --reap (stale-learner fix)
        import atexit
        from pokeagent.registry import register_worker, unregister_worker
        reg_p = Path('runs/rl_agents.json')
        info = {'tag': a.tag, 'segment': a.segment,
                'cmd': sys.argv[1:]}  # rl_cull replays this to respawn the learner
        try:
            lease = register_worker(reg_p, a.frame_port, info)
        except (OSError, ValueError, RuntimeError) as error:
            ap.error(str(error))
        atexit.register(unregister_worker, reg_p, a.frame_port, lease)
    default_state = next((s for s in SEGMENT_STATES[a.segment] if Path(s).exists()),
                         SEGMENT_STATES[a.segment][-1])
    start_states = [str(s) for s in (a.state or [default_state])]
    start = start_states[0]
    from rl_env import curriculum_subgoals
    env = SegmentEnv(a.rom, start, make_goal(a.segment), goal_name=a.segment,
                     subgoals=tuple(SEGMENT_SUBGOALS.get(a.segment, ())) + tuple(curriculum_subgoals(a.segment)),
                     max_steps=a.max_steps, hold=a.hold, settle=a.settle,
                     windowed=a.window, speed=a.speed, frame_port=a.frame_port,
                     publish_frames=a.publish_frames, half_res=not a.full_res,
                     obs_extra=EXTRA_OBS.get(a.segment), screen_context=a.screen_context)
    env.actions = actions
    env.render_interval = 1.0 / a.publish_fps
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
    def evaluation_env(state):
        evaluation = SegmentEnv(a.rom, state, make_goal(a.segment), goal_name=a.segment,
                                max_steps=a.max_steps, hold=a.hold, settle=a.settle,
                                obs_extra=EXTRA_OBS.get(a.segment), screen_context=a.screen_context)
        evaluation.actions = list(actions)
        evaluation.battle_learning = a.battle_learning
        evaluation.travel_priority = a.travel_priority
        evaluation.combat_context = a.combat_context
        evaluation.spatial_observer = observer if a.spatial_context else None
        evaluation._goal_saved = True
        return evaluation

    run_git_sha = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1], text=True).strip()

    def evaluate(episodes, random_policy=False):
        frozen = {ast.literal_eval(key): tuple(row) for key, row in snapshot().items()}
        result = evaluate_table(evaluation_env, frozen, a.eval_state or start_states, episodes,
                                schema, seed=a.seed + 100003, random_policy=random_policy,
                                throttle_ms=min(a.throttle_ms, 2))
        result.update(segment=a.segment, git_sha=run_git_sha)
        return result

    alpha, gamma, eps0 = 0.2, 0.99, 1.0
    latest_eval = None
    try:
        wins = first_ep = None
        wins = 0
        steps_log: list[int] = []
        win_steps: list[int] = []  # solved-episode steps only: the number that shows learning
        visits: dict[tuple, int] = defaultdict(int)
        total_steps = 0

        def publish_status(episode, epsilon, phase='TRAIN', in_episode=False):
            if a.frame_port is None:
                return
            atomic_json(f'runs/rlstatus_{a.frame_port}.json',
                        {'instance': a.frame_port, 'pid': os.getpid(), 'tag': a.tag,
                         'generation': episode, 'episode': episode + 1, 'wins': wins,
                         'schema': schema, 'git_sha': run_git_sha, 'actions': len(actions), 'phase': phase,
                         'epsilon': epsilon, 'evaluation': latest_eval, 'updated_at': time.time(),
                         'outcomes': env.battle_outcomes, 'rewards': reward_components,
                         'current_steps': env.steps,
                         'steps_total': total_steps + (env.steps if in_episode else 0),
                         'steps_avg': round(sum(steps_log)/len(steps_log), 1) if steps_log else None,
                         'steps_best': min(steps_log) if steps_log else None,
                         'steps_worst': max(steps_log) if steps_log else None,
                         'win_avg': round(sum(win_steps)/len(win_steps), 1) if win_steps else None})

        reward_components = {}
        publish_status(-1, 1.0, 'STARTING')
        for ep in range(a.episodes):
            eps = exploration_rate(ep, a.eps_decay_episodes, a.eps_floor)  # decay, but never stop exploring
            env.state = Path(start_states[ep % len(start_states)])  # cycle recurring start states
            obs = env.reset()
            last_pub = 0.0
            traj = []  # n-step buffer: (s, a, r, s')
            ep_path = []  # full (obs, act) record for --trace run-level analysis
            novelty_budget = 0.2
            reward_components = {'extrinsic': 0.0, 'novelty': 0.0, 'potential': 0.0}
            publish_status(ep, eps, in_episode=True)
            for _ in range(env.max_steps):
                allowed = env.allowed_actions()
                values = [x + y for x, y in zip(Q[obs], QB[obs])] if QB is not None else Q[obs]
                if rng.random() < eps:
                    act = rng.choice(allowed)
                else:
                    best = max(values[i] for i in allowed)
                    act = rng.choice([i for i in allowed if values[i] == best])
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
                            a_star = max(env.allowed_actions(), key=lambda i: T[boot][i])
                            G += (gamma ** L) * S[boot][a_star]
                        else:
                            G += (gamma ** L) * max(Q[boot][i] for i in env.allowed_actions())
                    T[s0][a0] += alpha * (G - T[s0][a0])
                    traj.pop(0)
                obs = nxt
                if env.steps % 50 == 0 or info.get('outcome') != 'none':
                    publish_status(ep, eps, in_episode=True)
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
            if a.eval_every and (ep + 1) % a.eval_every == 0:
                publish_status(ep, eps, 'EVAL')
                evaluated = evaluate(a.periodic_evals)
                evaluated.update(training_episode=ep + 1, training_steps=total_steps)
                lid = a.frame_port if a.frame_port is not None else a.seed
                atomic_json(f'runs/evaluations/{schema}/{lid}_{os.getpid()}_{ep + 1}.json', evaluated)
                latest_eval = {key: evaluated[key] for key in (
                    'wins', 'episodes', 'win_rate', 'mean_solved_steps', 'model_digest',
                    'evaluation_scope', 'training_episode', 'training_steps')}
                print(f"  EVAL ep {ep + 1}: {evaluated['wins']}/{evaluated['episodes']} wins",
                      flush=True)
            publish_status(ep, eps)
            if (ep + 1) % 25 == 0:
                print(f"  ep {ep + 1}: {wins} solves so far" + (f" (first at ep {first_ep})" if first_ep is not None else ", none yet"), flush=True)
        learned, rand = [], []
        if a.evals:
            evaluated = evaluate(a.evals)
            atomic_json(f'runs/eval_{a.segment}_{schema}.json', evaluated)
            learned = [(row['won'], row['steps']) for row in evaluated['rollouts']]
            baseline = evaluate(a.evals, random_policy=True)
            rand = [(row['won'], row['steps']) for row in baseline['rollouts']]
            atomic_json(f'runs/baseline_{a.segment}_{schema}.json', baseline)
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
