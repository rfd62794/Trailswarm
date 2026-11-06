"""q_summary / q_state: read-only views of tabular Q-models (q_*.json) via qmodels + qdecode."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from pokeagent.qdecode import BUTTONS, decode_obs
from pokeagent.qmodels import load_model


def _read(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data, data.get("schema"), data.get("actions", 6)


def _parse_obs(obs):
    if isinstance(obs, str):
        obs = ast.literal_eval(obs)
    if isinstance(obs, (list, tuple)):
        return tuple(obs)
    raise ValueError(f"obs must be a tuple/list like (1, 18, 10, ...), got {obs!r}")


def _best(row, n_actions: int):
    if not row:
        return None, None
    i = max(range(min(len(row), n_actions)), key=lambda j: row[j])
    return (BUTTONS[i] if i < len(BUTTONS) else i), row[i]


def q_summary(path, top: int = 10) -> dict:
    """Model metadata plus the ``top`` highest-valued states, decoded for reading."""
    raw, schema, n_actions = _read(path)
    table = load_model(path, schema, n_actions)
    ranked = sorted(table.items(), key=lambda kv: max(kv[1]), reverse=True)[: max(0, top)]
    return {
        "path": str(path), "version": raw.get("version"), "schema": schema,
        "actions": n_actions, "states": len(table),
        "top": [{"obs": decode_obs(k), "best": _best(row, n_actions)[0],
                 "q": _best(row, n_actions)[1]} for k, row in ranked],
    }


def q_state(path, obs) -> dict:
    """The Q row at one observation: decoded obs plus per-button values."""
    _, schema, n_actions = _read(path)
    table = load_model(path, schema, n_actions)
    key = _parse_obs(obs)
    row = table.get(key)
    return {"path": str(path), "obs": decode_obs(key), "visited": row is not None,
            "q": dict(zip(BUTTONS[:n_actions], row or []))}
