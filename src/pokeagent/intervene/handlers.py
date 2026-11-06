"""Agent-side command handlers for the intervention tools, merged into ExplorerAgentView.handlers().

``claude_hold`` starts the lease, ``hold_release`` ends it (together with the human hold), ``press`` with source "claude"
goes through the ClaudeDriver (refreshes the lease, marks decisions.jsonl) and ``macro_cancel`` stops a running macro. The
``macro`` command itself is the view's MacroController (it runs a step per frame tick, see runner.py). Nothing here is
reachable except through ControlServer.
"""
from __future__ import annotations

from pokeagent.snapshot import Event


def intervene_handlers(view) -> dict:
    """{command: handler} (un-wrapped; the view marshals them onto the emulator thread)."""
    ctx, hold = view.ctx, view.claude_hold

    def claude_hold(seconds: int, **_) -> dict:
        view.recent.append(Event(step=ctx.step, driver="claude", text=f"hold {seconds}s"))
        return {"claude_hold_s": hold.grant(seconds)}

    def hold_release(**_) -> dict:
        view.hold.release()
        hold.release()
        return {}

    return {"claude_hold": claude_hold, "hold_release": hold_release, "macro_cancel": lambda **_: view.macros.cancel()}
