"""One finding = one broken invariant, with the data a remediation needs."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"


def fmt_map(map_id) -> str:
    """Map id in decimal AND hex, so '@61' (hex) is never read as 61 decimal (0x61 = 97)."""
    try:
        i = int(map_id)
    except (TypeError, ValueError):
        return str(map_id)
    return f"{i} (0x{i:02X})"


@dataclass
class Finding:
    check: str                  # warps | milestones | states | segments | tables
    level: str                  # ERROR | WARN | INFO
    kind: str                   # machine-readable subtype, drives the fix plan
    message: str
    data: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


def read_json(path: Path):
    """(value, error): a missing file is (None, None); an unreadable or unparsable one is (None, reason)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as e:
        return None, str(e)
    try:
        return json.loads(text), None
    except ValueError as e:
        return None, f"invalid JSON: {e}"
