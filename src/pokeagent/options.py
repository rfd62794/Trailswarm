"""Options (Sutton): learned sub-policies invoked as single meta-actions.

An Option wraps a trained Q-table + termination predicate + step cap. When a
meta-agent selects an option action, the sub-policy runs greedy until its goal
fires, the cap hits, or the environment ends — then control returns upward.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.qmodels import load_model


class Option:
    def __init__(self, name: str, table_path: str, goal_fn, max_steps: int = 100, initiation=None):
        data = json.loads(Path(table_path).read_text())
        self.table = load_model(table_path, data.get('schema'), data.get('actions', 6))
        self.n_actions = data.get('actions', 6)
        self.goal_fn = goal_fn
        self.max_steps = max_steps
        self.initiation = initiation or (lambda env: True)
        self.name = name
        self.key_len = len(next(iter(self.table), ()))  # skill's obs width for outer->skill mapping

    def available(self, env) -> bool:
        try:
            return bool(self.initiation(env))
        except Exception:
            return False

    def _key(self, obs):
        """Map outer-env obs to the skill's obs width: first 14 fields + last (L-14) tail fields."""
        obs = tuple(obs)
        L, M = self.key_len, len(obs)
        if L >= M:
            return obs[:L]
        if L <= 14:
            return obs[:L]
        return obs[:14] + obs[M - (L - 14):]

    def act(self, obs) -> int:
        row = self.table.get(self._key(obs))
        if row is None:
            return 0  # unvisited state under this skill: first action as fallback
        return max(range(min(len(row), self.n_actions)), key=lambda i: row[i])

    def run(self, env) -> tuple[float, int, bool, dict]:
        """Drive env greedy until goal, cap, or env termination. Returns (reward, steps, done, info)."""
        total, steps, done, info = 0.0, 0, False, {}
        while steps < self.max_steps and not done:
            obs = env._obs()
            nxt, rew, done, info = env.step(self.act(obs))
            total += rew
            steps += 1
            if self.goal_fn(env.emu):
                done = True
                info['option_solved'] = True
        info['option'] = self.name
        info['option_steps'] = steps
        return total, steps, done, info
