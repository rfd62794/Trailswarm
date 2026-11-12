"""Options (Sutton): learned sub-policies invoked as single meta-actions.

An Option wraps a trained Q-table + termination predicate + step cap. When a
meta-agent selects an option action, the sub-policy runs greedy until its goal
fires, the cap hits, or the environment ends — then control returns upward.
"""
from __future__ import annotations

import json
from pathlib import Path

from pokeagent.navigation import load_memory, shortest_path
from pokeagent.qmodels import load_model
from pokeagent.ram import read_state
from pokeagent.ram_symbols import IS_IN_BATTLE


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
            idx = self.act(obs)
            if idx >= len(getattr(env, 'actions', ())):
                info['option_failed'] = 'action_out_of_range'  # skill trained with more buttons than this env
                break
            nxt, rew, done, info = env.step(idx)
            total += rew
            steps += 1
            if self.goal_fn(env.emu):
                done = True
                info['option_solved'] = True
        info['option'] = self.name
        info['option_steps'] = steps
        return total, steps, done, info


class ScriptedNav:
    """Deterministic skill: BFS the learned map graph to a target tile.

    Not learned — geometry the shared map already knows. Re-plans each step so
    moving NPCs or newly blocked edges can't trap it.
    """

    def __init__(self, target: tuple[int, int], max_steps: int = 200, target_map: int | None = None):
        self.target = target
        self.target_map = target_map
        self.max_steps = max_steps
        self.name = f'nav:{target[0]},{target[1]}' if target_map is None else f'nav:{target_map}:{target[0]},{target[1]}'

    def available(self, env) -> bool:
        try:
            return env.emu.read(IS_IN_BATTLE) == 0 and env.emu.read_range(0xC3A0, 360).find(bytes([0x79, 0x7A])) < 0
        except Exception:
            return False

    def run(self, env) -> tuple[float, int, bool, dict]:
        total, steps, done, info = 0.0, 0, False, {}
        memory = load_memory()
        while steps < self.max_steps and not done:
            s = read_state(env.emu)
            tmap = s.map_id if self.target_map is None else self.target_map
            if s.map_id == tmap and (s.x, s.y) == self.target:
                done = True
                info['option_solved'] = True
                break
            path = shortest_path(memory, s.map_id, s.x, s.y, *self.target, tmap=tmap, nearest=True)
            if not path:
                info['option_failed'] = 'max_reach'  # rode to the frontier of known space
                break
            _, rew, done, info = env.step(path[0])
            total += rew
            steps += 1
        info['option'] = self.name
        info['option_steps'] = steps
        return total, steps, done, info
