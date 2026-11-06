"""PressFrame: the locals one do_press call shares between its steps."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PressFrame:
    name: str
    source: str
    why: str
    before: tuple = (0, 0, 0)
    after: tuple = (0, 0, 0)
    tm: bytes = b""
    tm2: bytes = b""
    box_before: bool = False
    box_after: bool = False
    text: str = ""
    result: str = ""
    goals: dict = field(default_factory=dict)
    goals_before: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    snap_pre: Any = None
    bag_pre: dict = field(default_factory=dict)
    fp_pre: Any = None  # press_value.fingerprint before the press
