"""Agent-side command handlers for the intervention tools, merged into ExplorerAgentView.handlers().

``claude_hold`` starts the lease, ``hold_release`` ends it (together with the human hold), ``press`` with source "claude"
goes through the ClaudeDriver (refreshes the lease, marks decisions.jsonl) and ``macro`` runs a screen-verified procedure
on the emulator thread (the view wraps it with a long timeout). Nothing here is reachable except through ControlServer.
"""
from __future__ import annotations

from pokeagent.intervene.macros import run_macro
from pokeagent.intervene.rig import EmuRig
from pokeagent.snapshot import Event

MACRO_TIMEOUT_S = 120.0
AUTO_LEASE_S = 30


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

    def macro(name: str, args: dict | None = None, **_) -> dict:
        if not hold.active():
            hold.grant(AUTO_LEASE_S)  # a macro always runs under a lease: the agent must not decide between its presses
        out = run_macro(EmuRig(ctx, view.driver, name), name, args)
        hold.touch()
        view.recent.append(Event(step=ctx.step, driver="claude", text=f"macro {name}: {out.get('result')}"))
        return out

    return {"claude_hold": claude_hold, "hold_release": hold_release, "macro": macro}
