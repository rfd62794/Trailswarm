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
    def __init__(self, name: str, table_path: str, goal_fn, max_steps: int = 100):
        data = json.loads(Path(table_path).read_text())
        self.table = load_model(table_path, data.get('schema'), data.get('actions', 6))
        self.n_actions = data.get('actions', 6)
        self.goal_fn = goal_fn
        self.max_steps = max_steps
        self.name = name

    def act(self, obs) -> int:
        row = self.table.get(tuple(obs))
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
