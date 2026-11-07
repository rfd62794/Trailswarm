"""Classify one byte change (before -> after) and test it against a predicted kind."""
from __future__ import annotations


def flat_vals(vals: dict) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for k, v in (vals or {}).items():
        items = v if isinstance(v, list) else [v]
        out[k] = {int(i) for i in items if isinstance(i, int) and i}
    return out


def kinds_of(before: int, after: int, vals: dict | None = None) -> list[str]:
    """Descriptions that fit this change, most specific first."""
    ks: list[str] = []
    diff = (after - before) % 256
    if after == (before + 1) & 255:
        ks.append("inc1")
    if after == (before - 1) & 255:
        ks.append("dec1")
    added, removed = after & ~before, before & ~after
    if added and not removed and added & (added - 1) == 0:
        ks.append(f"set_bit:{added.bit_length() - 1}")
    if removed and not added and removed & (removed - 1) == 0:
        ks.append(f"clear_bit:{removed.bit_length() - 1}")
    for name, s in flat_vals(vals or {}).items():
        if after in s:
            ks.append(f"copy:{name}")
    if after == 0:
        ks.append("zero")
    ks.append(f"const:{after}")
    ks.append("inc" if diff < 128 else "dec")
    return ks


def matches(kind: str, before: int, after: int, vals: dict | None = None) -> bool:
    return kind in kinds_of(before, after, vals)


def describe(kind: str) -> str:
    head, _, arg = kind.partition(":")
    return {"inc1": "increments by 1", "dec1": "decrements by 1", "inc": "increases", "dec": "decreases",
            "zero": "cleared to 0", "set_bit": f"sets bit {arg}", "clear_bit": f"clears bit {arg}",
            "copy": f"copies the event {arg}", "const": f"set to {arg}"}.get(head, kind)
