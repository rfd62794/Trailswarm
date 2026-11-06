"""Battle text parsing: the result messages pokered prints after a move.

The text box wraps sentences across screen rows and the charmap leaves some punctuation as '?',
so matching is whitespace/punctuation-insensitive: "It's super effective!" and a row-wrapped
"It's supereffec|tive!" classify the same.
"""
from __future__ import annotations

import re

_USED = re.compile(r"\bused\s+(.+)$", re.IGNORECASE)


def _flat(text) -> str:
    return " ".join(str(text).split())


def parse_effect(text) -> dict:
    """{"effect": "super"|"weak"|"none"|None, "crit": bool} for one line of battle text.

    The four messages: "It's super effective!", "It's not very effective...", "It doesn't
    affect <MON>..." (the apostrophe decodes as '?', hence the loose 'doesn' check) and
    "Critical hit!". Anything else gives effect None.
    """
    t = re.sub(r"[^a-z0-9]", "", str(text).lower())
    out = {"effect": None, "crit": "criticalhit" in t}
    if "supereffective" in t:
        out["effect"] = "super"
    elif "notveryeffective" in t:
        out["effect"] = "weak"
    elif ("doesn" in t or "doesnot" in t) and "affect" in t:
        out["effect"] = "none"
    return out


def battle_events(text) -> list[tuple]:
    """Ordered battle events in flowed dialog text ('!'- and '...'-separated sentences).

    ('used', 'enemy'|'ours', 'MOVE NAME'), ('effect', 'super'|'weak'|'none'), ('crit',).
    '<who> used <MOVE>!' lines whose speaker starts with 'Enemy' are the opponent's; ours are
    '<POKEMON> used <MOVE>!'. '...' ends a sentence too: "It's not very effective..." has no '!'.
    """
    out = []
    for seg in _flat(text).replace("...", "!").split("!"):
        seg = seg.strip()
        if not seg:
            continue
        m = _USED.search(seg)
        if m:
            who = seg[:m.start()].strip()
            side = "enemy" if who.lower().startswith("enemy") else "ours"
            move = " ".join(m.group(1).split()).upper()
            if move:
                out.append(("used", side, move))
            continue
        fx = parse_effect(seg)
        if fx["effect"]:
            out.append(("effect", fx["effect"]))
        elif fx["crit"]:
            out.append(("crit",))
    return out
