"""Parse a model's raw reply into a Decision: one button plus reasoning text.

The reply protocol is a single JSON object::

    {"thinking": "one or two sentences", "button": "A", "note": "optional memory"}

The parser is deliberately tolerant: replies wrapped in markdown fences or
surrounded by prose still yield a Decision, and anything unparseable becomes
a safe Decision("NONE") carrying an error string instead of raising.
"""

import json
from dataclasses import dataclass

VALID_BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "START", "SELECT", "NONE")

_THINKING_LIMIT = 1000
_NOTE_LIMIT = 500
_RAW_LIMIT = 500


@dataclass(frozen=True)
class Decision:
    """One step's choice. A non-empty `error` means the reply failed to parse."""

    button: str
    thinking: str = ""
    note: str = ""
    error: str = ""
    raw: str = ""

    def __post_init__(self) -> None:
        button = str(self.button).strip().upper()
        object.__setattr__(self, "button", button)
        if button not in VALID_BUTTONS:
            object.__setattr__(self, "button", "NONE")
            if not self.error:
                object.__setattr__(self, "error", f"unknown button {button!r}")


def parse_reply(text: str) -> Decision:
    """Turn raw model output into a Decision. Never raises."""
    if not isinstance(text, str):
        text = str(text or "")
    obj, err = _first_json_object(text)
    if obj is None:
        return Decision("NONE", error=err, raw=text[:_RAW_LIMIT])
    if not isinstance(obj, dict):
        return Decision("NONE", error="reply is not a json object", raw=text[:_RAW_LIMIT])
    thinking = str(obj.get("thinking") or "")[:_THINKING_LIMIT]
    note = str(obj.get("note") or "")[:_NOTE_LIMIT]
    button = obj.get("button")
    if button is None:
        return Decision("NONE", thinking=thinking, error="missing button", raw=text[:_RAW_LIMIT])
    button = str(button).strip().upper()
    if button not in VALID_BUTTONS:
        return Decision(
            "NONE", thinking=thinking, error=f"unknown button {button!r}", raw=text[:_RAW_LIMIT]
        )
    return Decision(button, thinking=thinking, note=note)


def _first_json_object(text: str):
    """First balanced ``{...}`` span that ``json.loads`` accepts, else an error reason."""
    pos = 0
    saw_object = False
    while True:
        start = text.find("{", pos)
        if start == -1:
            return None, ("bad json" if saw_object else "no json object")
        end = _balanced_end(text, start)
        if end is None:
            return None, "unbalanced braces"
        saw_object = True
        try:
            return json.loads(text[start:end]), None
        except json.JSONDecodeError:
            pos = end


def _balanced_end(text: str, start: int) -> int | None:
    """Index just past the close brace matching ``text[start]``, or None.

    String-aware so braces inside ``"..."`` do not count toward depth.
    """
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None
