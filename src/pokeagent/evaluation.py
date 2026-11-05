import hashlib
import json
import random
import time
from pathlib import Path


def exploration_rate(episode, decay_episodes, floor):
    if decay_episodes < 1 or not 0 <= floor <= 1:
        raise ValueError('Invalid exploration schedule')
    return max(floor, 1.0 - episode / decay_episodes)


def evaluate_table(env_factory, table, states, episodes, schema, *, seed=0, random_policy=False,
                   throttle_ms=0, unseen_random=True):
    if episodes < 1 or not states:
        raise ValueError('Evaluation requires episodes and starting states')
    frozen = {state: tuple(row) for state, row in table.items()}
    digest = hashlib.sha256(json.dumps({repr(k): list(v) for k, v in frozen.items()},
                                      sort_keys=True).encode()).hexdigest()
    rng = random.Random(seed)
    rollouts = []
    for episode in range(episodes):
        state = str(states[episode % len(states)])
        env = env_factory(state)
        try:
            obs = env.reset()
            reward_total = 0.0
            unseen = 0
            info = {}
            for _ in range(env.max_steps):
                allowed = env.allowed_actions()
                if not allowed:
                    raise ValueError('Evaluation received an empty action mask')
                unseen += int(obs not in frozen)
                row = frozen.get(obs)
                if random_policy or (row is None and unseen_random):
                    action = rng.choice(allowed)
                elif row is None:
                    action = allowed[0]
                else:
                    best = max(row[index] for index in allowed)
                    action = rng.choice([index for index in allowed if row[index] == best])
                obs, reward, done, info = env.step(action)
                reward_total += reward
                if done:
                    break
                if throttle_ms:
                    time.sleep(throttle_ms / 1000)
            rollouts.append({'won': bool(env.goal_reached), 'steps': env.steps,
                             'return': reward_total, 'unseen_states': unseen,
                             'outcome': info.get('outcome', 'unknown'),
                             'battle': info.get('battle', {}), 'source_state': state,
                             'source_digest': hashlib.sha256(Path(state).read_bytes()).hexdigest()})
        finally:
            env.close()
    solved = [row['steps'] for row in rollouts if row['won']]
    return {'version': 2, 'success_definition': 2, 'schema': schema,
            'epsilon': 1.0 if random_policy else 0.0, 'episodes': episodes,
            'wins': len(solved), 'win_rate': len(solved) / episodes,
            'mean_solved_steps': sum(solved) / len(solved) if solved else None,
            'model_digest': digest, 'source_digest': rollouts[0]['source_digest'],
            'source_states': list(map(str, states)),
            'evaluation_scope': 'multi_checkpoint' if len(set(states)) > 1 else 'fixed_checkpoint_greedy',
            'unseen_fallback': 'random' if unseen_random else 'first_action',
            'rollouts': rollouts}
