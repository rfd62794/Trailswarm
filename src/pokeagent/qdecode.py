"""Decode tabular Q-model observations for humans and tools.

Shared by tools/qview.py and tools/watch.py so the "model's-eye view" has one
implementation: base obs fields, screen context, tile window, combat fields.
"""
from __future__ import annotations

from pokeagent.screencontext import MenuKind, ScreenType

BUTTONS = ['UP', 'DOWN', 'LEFT', 'RIGHT', 'A', 'B', 'START', 'SELECT']
MAPS = {0: 'pallet', 1: 'viridian', 2: 'pewter', 0x0C: 'route1', 0x0D: 'route2',
        0x25: 'house_f1', 0x26: 'house_f2', 0x28: 'oaks_lab', 0x36: 'pewter_gym'}
FACING = {0: 'DOWN', 1: 'UP', 2: 'LEFT', 3: 'RIGHT'}
TILES = {0: '?', 1: '.', 2: '#', 3: '~'}  # unknown/walkable/solid/grass


def decode_obs(obs) -> dict:
    obs = tuple(obs)
    out = {'map': MAPS.get(obs[0], hex(obs[0])), 'pos': (obs[1], obs[2]),
           'box': bool(obs[3]), 'facing': FACING.get(obs[4], obs[4]),
           'battle': bool(obs[5]), 'hp_q': obs[6], 'bag_n': obs[7]}
    if len(obs) >= 14:
        out.update(screen=ScreenType(obs[8]).name, menu=MenuKind(obs[9]).name,
                   cursor=(obs[11], obs[12]), option=obs[13])
    if len(obs) >= 24:
        out.update(tiles=[''.join(TILES.get(v, str(v)) for v in obs[14:17]),
                          ''.join(TILES.get(v, str(v)) for v in obs[17:20]),
                          ''.join(TILES.get(v, str(v)) for v in obs[20:23])],
                   blocked_mask=obs[23])
    if len(obs) > 24:
        out['rest'] = list(obs[24:])
    return out


def preferred(table: dict, obs, n_actions: int):
    """(action_name, value) the model prefers at obs, or (None, None) if unvisited."""
    row = table.get(tuple(obs)) or table.get(obs)
    if not row:
        return None, None
    best = max(range(min(len(row), n_actions)), key=lambda i: row[i])
    return BUTTONS[best] if best < len(BUTTONS) else best, row[best]


def brain_line(table: dict, obs, n_actions: int) -> str:
    """Compact GUI line: 'MENU/START opt3 -> A(0.07)'."""
    if obs is None:
        return 'brain: (no trace yet)'
    d = decode_obs(obs)
    where = d.get('menu') or d.get('screen') or d['map']
    if d.get('option', -1) >= 0:
        where += f" opt{d['option']}"
    act, val = preferred(table, obs, n_actions)
    choice = f"{act}({val:.2f})" if act else 'unseen'
    return f"brain: {where} -> {choice} @{d['map']}{d['pos']}"
