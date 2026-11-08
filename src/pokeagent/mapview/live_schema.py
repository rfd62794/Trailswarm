"""The live record's schema: validation and the file stem an agent name is allowed to become."""
from __future__ import annotations

import math
import re

SCHEMA = 1
MAX_COORD = 1e9                # same sanity bound the ghost reader uses


def valid(rec) -> bool:
    if not isinstance(rec, dict) or rec.get("schema") != SCHEMA:
        return False
    if not all(isinstance(rec.get(k), str) for k in ("agent", "run", "area")):
        return False
    if not all(type(rec.get(k)) in (int, float) and math.isfinite(rec[k]) and abs(rec[k]) < MAX_COORD
               for k in ("x", "y")):
        return False
    t = rec.get("updated_at")
    if type(t) not in (int, float) or not math.isfinite(t):
        return False
    return all(v is None or type(v) is int for v in (rec.get("screen_x"), rec.get("screen_y"),
                                                     rec.get("screen_w"), rec.get("screen_h")))


def safe_name(agent: str) -> str:
    """The agent name as a file stem: no separators or odd characters, never empty or hidden."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", agent).lstrip(".")[:64] or "agent"
