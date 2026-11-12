"""Load and validate RAM observation files: one byte value per sample, tagged with a game key and a slug context.

Format (version 1)::

    {"version": 1, "game": "pokemon-red",
     "samples": [{"addr": "0xD35E", "value": 12, "context": "walk-route1"}]}

Every rule is an allow-list; any violation raises ``ObservationError`` naming the file, sample index and rule.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

GAMES = ("pokemon-red", "pokemon-blue")

TOP_KEYS = frozenset({"version", "game", "samples"})
SAMPLE_KEYS = frozenset({"addr", "value", "context"})
ADDR_RE = re.compile(r"^0x[0-9A-Fa-f]{4}$")
CONTEXT_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$")
RAM_RANGES = ((0xC000, 0xDFFF), (0xFF80, 0xFFFE))


class ObservationError(ValueError):
    """A malformed observation file."""


@dataclass(frozen=True)
class Sample:
    addr: int
    value: int
    context: str


@dataclass(frozen=True)
class Observation:
    game: str
    samples: tuple[Sample, ...]


def _fail(path: Path, where: str, rule: str) -> ObservationError:
    return ObservationError(f"{path}: {where}: {rule}")


def _sample(path: Path, i: int, raw: Any) -> Sample:
    where = f"sample {i}"
    if not isinstance(raw, dict):
        raise _fail(path, where, "sample must be an object")
    extra = sorted(set(raw) - SAMPLE_KEYS)
    if extra:
        raise _fail(path, where, f"unknown key(s) {extra}; allowed {sorted(SAMPLE_KEYS)}")
    missing = sorted(SAMPLE_KEYS - set(raw))
    if missing:
        raise _fail(path, where, f"missing key(s) {missing}")
    addr_s = raw["addr"]
    if not isinstance(addr_s, str) or not ADDR_RE.match(addr_s):
        raise _fail(path, where, "addr must be a hex string '0x' plus 4 hex digits")
    addr = int(addr_s, 16)
    if not any(lo <= addr <= hi for lo, hi in RAM_RANGES):
        raise _fail(path, where, "addr must be in 0xC000..0xDFFF or 0xFF80..0xFFFE")
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise _fail(path, where, "value must be an int 0..255")
    context = raw["context"]
    if not isinstance(context, str) or not CONTEXT_RE.match(context):
        raise _fail(path, where, f"context must match {CONTEXT_RE.pattern}")
    return Sample(addr, value, context)


def load_observation_file(path: str | Path) -> Observation:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _fail(path, "file", f"must be readable JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise _fail(path, "top level", "must be an object")
    extra = sorted(set(data) - TOP_KEYS)
    if extra:
        raise _fail(path, "top level", f"unknown key(s) {extra}; allowed {sorted(TOP_KEYS)}")
    version = data.get("version")
    if isinstance(version, bool) or version != 1:
        raise _fail(path, "top level", "version must be 1")
    game = data.get("game")
    if game not in GAMES:
        raise _fail(path, "top level", f"game must be one of {list(GAMES)}")
    samples = data.get("samples")
    if not isinstance(samples, list):
        raise _fail(path, "top level", "samples must be a list")
    return Observation(game, tuple(_sample(path, i, s) for i, s in enumerate(samples)))


def load_observations(paths: Iterable[str | Path]) -> dict[str, list[Sample]]:
    """Merge files by game key; every game in ``GAMES`` is present (possibly empty)."""
    out: dict[str, list[Sample]] = {g: [] for g in GAMES}
    for p in paths:
        obs = load_observation_file(p)
        out[obs.game].extend(obs.samples)
    return out
