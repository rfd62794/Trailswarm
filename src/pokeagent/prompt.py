"""Builds the per-step prompt sent to the backend.

One pure function: given the current game state, the recent log entries and
the agent's notes file, produce the text that asks the model for exactly one
JSON decision object.
"""

from __future__ import annotations

from pokeagent.ram import GameState

GOAL = "You are playing Pokemon Red. Explore, talk to people, progress the story."

REPLY_CONTRACT = (
    'Reply with exactly one JSON object: '
    '{"thinking": "...", "button": "UP|DOWN|LEFT|RIGHT|A|B|START|SELECT|NONE", '
    '"note": "optional, something worth remembering"}. No other text.'
)

RECENT_LIMIT = 10


def build_prompt(
    state: GameState,
    recent: list[dict],
    notes: str,
    step: int,
    max_steps: int,
) -> str:
    """Assemble the prompt for one step. Pure function, no I/O."""
    lines = [
        GOAL,
        "",
        f"## Step {step} of {max_steps}",
        "",
        "## Current state",
        state.summary(),
        "",
        "## Recent steps",
    ]
    if recent:
        for entry in recent[-RECENT_LIMIT:]:
            line = f"step {entry.get('step')}: pressed {entry.get('button')}"
            thinking = entry.get("thinking") or ""
            if thinking:
                line += f" ({thinking})"
            lines.append(line)
    else:
        lines.append("(none yet)")
    lines += [
        "",
        "## Your notes",
        notes.rstrip("\n") if notes.strip() else "(empty)",
        "",
        REPLY_CONTRACT,
    ]
    return "\n".join(lines)
