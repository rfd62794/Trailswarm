"""One supervised slot of the continuous swarm."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Slot:
    idx: int
    role: str
    handle: Any = None
    cfg: dict = field(default_factory=dict)
    started: float = 0.0
    streak: int = 0           # consecutive fast non-zero exits
    paused_until: float = 0.0
    retire: bool = False      # removed by a smaller --agents: no refill once its agent is done
