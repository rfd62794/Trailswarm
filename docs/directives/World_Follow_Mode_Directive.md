# PokeAgent: World view follow mode - lock the camera onto one agent and ride along

**Read first:** nothing outside this file is needed. Everything you need is pasted below.
**Do not list the tree recursively**; use `git ls-files`. Do not search, glob or hunt: if a file or symbol named
here is missing, stop and write that in the Status row.

## 1. Why this exists

Robert, 2026-11-06, watching the World view (all swarm agents drawn on one ROM-rendered map of Kanto):
"I almost want to be able to lock onto an agent and follow them." Confirmed: the camera locks onto one agent and
keeps it centred while it walks, across map changes and into buildings; zoom still works while following.

Today the World view can select an agent (single click -> side panel), open it (double click -> focus view),
pan (drag) and zoom (wheel), but the camera never moves by itself.

## 2. Scope (in order)

1. New pure module `src/pokeagent/world/follow.py` (no Dear PyGui import): the follow state and the camera step.
2. Wire it into `src/pokeagent/viewer/ui/world_view.py` (`WorldView`).
3. Show the follow state on the canvas (one line of text).
4. Tests in a new file `tests/test_world_follow.py`.

## 3. The work

### 3.1 `src/pokeagent/world/follow.py`

```python
"""Follow mode: the World view camera rides along with one agent (pure; the view applies it each frame)."""
from __future__ import annotations

from dataclasses import dataclass

LOST_AFTER_S = 10.0   # the followed agent has had no position this long (finished / restarted): stop following
EASE_PER_S = 8.0      # camera catch-up rate: fraction of the remaining distance closed per second (clamped to 1)
SNAP_PX = 2048.0      # a jump this far (world px: a warp, a map change) snaps instead of gliding across Kanto


@dataclass
class Follow:
    agent_id: str | None = None
    last_seen: float = 0.0

    def start(self, agent_id: str, now: float) -> None: ...
    def stop(self) -> None: ...
    @property
    def active(self) -> bool: ...

    def target(self, points: dict[str, tuple[float, float]], now: float) -> tuple[float, float] | None:
        """World-px point to centre on, or None. Updates last_seen when the agent is in `points`;
        stops (agent_id -> None) when it has been missing for LOST_AFTER_S."""

    def step(self, vp, target: tuple[float, float], dt: float) -> None:
        """Move vp.cx/vp.cy toward target: snap when the distance > SNAP_PX, else close
        min(1, dt * EASE_PER_S) of the gap. Never changes vp.zoom. Must not set vp.auto_fit back to True."""
```

Write `vp.cx` / `vp.cy` directly and then call the viewport's clamp the same way `Viewport.center_on` does
(pasted below), or call `vp.center_on(nx, ny)` with the eased point - either is fine; `center_on` already sets
`auto_fit = False` and clamps.

The `Viewport` in `src/pokeagent/world/view.py` (real code, abbreviated):

```python
class Viewport:
    """Which part of the world is on screen: ``cx, cy`` = world pixel at the screen centre, ``zoom`` = screen px per world px."""
    world_w: int; world_h: int; screen_w: int = 800; screen_h: int = 600
    cx: float = 0.0; cy: float = 0.0; zoom: float = 0.1
    auto_fit: bool = True      # until the user zooms/pans, a resize re-fits the world
    def pan(self, dsx, dsy): self.auto_fit = False; self.cx -= dsx / self.zoom; self.cy -= dsy / self.zoom; self._clamp()
    def center_on(self, wx, wy): self.auto_fit = False; self.cx, self.cy = wx, wy; self._clamp()
    def step_zoom_at(self, sx, sy, direction): ...   # wheel zoom about a screen point
```

### 3.2 Wiring in `WorldView` (`src/pokeagent/viewer/ui/world_view.py`)

Relevant real code today:

```python
    def __init__(self, parent, world_model, on_focus, on_select, loader, side_cls=None) -> None:
        ...
        self._points: dict[str, tuple[float, float]] = {}   # agent id -> world px, filled by draw_agents each frame

    def _wheel(self, delta) -> None:
        m = self._mouse()
        if m and self.pyr and not self.interiors.edit_wheel(delta):
            self.vp.step_zoom_at(m[0], m[1], 1 if float(delta) > 0 else -1)

    def _release(self) -> None:
        m, d = self._mouse(), self._down_at
        self.interiors.release()
        self._down_at = self._last_mouse = None
        if m and d and abs(m[0] - d[0]) < 4 and abs(m[1] - d[1]) < 4 and self.world:
            aid = pick(self._points, self.vp, *m)
            if aid:
                self._on_select(aid)
            elif self.side:
                ...   # tile info for an empty-map click

    def _drag(self) -> None:
        m = self._mouse()
        if m and dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            if self._last_mouse:
                d = (m[0] - self._last_mouse[0], m[1] - self._last_mouse[1])
                if not self.interiors.edit_drag(*d):
                    self.vp.pan(*d)
            self._last_mouse = m
        else:
            self._last_mouse = None

    def _frame(self, now: float, dl) -> None:
        self.interiors.tick_world()
        self._maybe_rebuild(now)
        self._drag()
        vp, self._uploads = self.vp, 0
        f, chunks = self.pyr.plan(vp.zoom, vp.visible(), MAX_TEX - 10)
        ...   # draws chunks, then agents (draw_agents fills self._points)
```

Behaviour to add:

- `self.follow = Follow()` and `self._follow_t: float | None = None` in `__init__`.
- **Start:** a single click on an agent (the `if aid:` branch of `_release`) keeps calling `self._on_select(aid)`
  and also calls `self.follow.start(aid, time.monotonic())`. Clicking a different agent switches the follow.
- **Stop:** a drag that actually pans the map (in `_drag`, when `self.vp.pan(...)` runs and the delta is non-zero),
  and a single click on empty map (the `elif` branch of `_release`) call `self.follow.stop()`.
  Zooming with the wheel does NOT stop following.
- **Each frame:** at the start of `_frame`, after `self._drag()` and before `self.pyr.plan(...)`:
  `t = self.follow.target(self._points, now)`; if `t` is not None, `self.follow.step(self.vp, t, dt)` where
  `dt = now - self._follow_t` (0 on the first frame), then `self._follow_t = now`. `self._points` is last frame's
  positions - one frame of lag is fine.
- Double click (focus view) is unchanged.

### 3.3 Status line

When `self.follow.active`, draw one line at the top-left of the canvas, after the agents, e.g.
`dpg.draw_text((12, 8), f"Following {aid[-8:]} - drag the map or click empty space to stop", size=ui_scale.px(15), parent=dl)`.
Use the same `dpg.draw_text(..., parent=dl)` style already used in `_frame` / `draw_agents`.

## 4. What NOT to do

- Do not change `Viewport`, `pick`, `locate`, `draw_agents`, the interiors layer, the side panel, the focus view,
  or any key bindings (`src/pokeagent/viewer/ui/keys.py` already owns Escape, P and T - do not add keys).
- No new dependencies. No changes outside the four items in section 2.
- Do not open a window, start the viewer, or send OS input to test it: tests are pure (no Dear PyGui viewport).
  Robert does the real-window check.
- Do not refactor `world_view.py` beyond the lines needed.

## 5. Verification

- `uv run pytest -q tests/test_world_follow.py` - all pass. Cover at least:
  1. `start` then `target` returns the agent's point; `active` is True.
  2. Agent missing from `points` for longer than `LOST_AFTER_S` -> `target` returns None and `active` is False;
     missing for less -> still active (returns None that frame, no crash).
  3. `step` with a small gap moves `cx, cy` part of the way (dt=0.05 -> 40% of the gap at EASE_PER_S=8), never
     overshoots with a large dt (dt=10 -> exactly on target), and leaves `zoom` unchanged.
  4. A gap larger than `SNAP_PX` snaps exactly to the target.
  5. `step` leaves `vp.auto_fit` False (use a real `pokeagent.world.view.Viewport(world_w=4000, world_h=4000)`).
- `uv run pytest -q tests/test_world_view.py tests/test_viewer_core.py tests/test_viewer_agents.py` - still pass
  (`tests/test_world_view.py` is 20 passed today).
- `uv run pytest -q` - the full suite passes (about 1,010 tests; 25 skipped is normal - ROM-gated).
  Test command checked on this repo: `uv run python --version` -> Python 3.12.12.

## 6. Rules for this run

- The run is NON-INTERACTIVE: any tool call needing confirmation is rejected and the run ends. Never install,
  download or fetch. Never read outside the working directory.
- Never run `uv run pokeagent ...` entry points (the sandbox refuses them); `uv run pytest` and
  `uv run python -c` are fine.
- Create no scratch or debug files. If one is unavoidable it goes under `.devin-scratch/` and stays.
- Work only on your `directive/<slug>` branch; never commit to main, never push to main, never deploy.
- If a tool call is genuinely blocked, stop and write why in the Status row rather than trying another way around it.

## 7. Completion criteria

- `follow.py` exists with the API in 3.1; `WorldView` starts/stops/steps follow exactly as in 3.2; the status line
  shows while following.
- New tests and the full suite pass (paste the tail lines).
- The Status row is set to Review with the branch pushed.

## 8. Report

Files changed, the test tails, and a 5-line manual checklist for Robert's real-window check (click an agent ->
camera follows; it follows into a building and across a map change; wheel zoom keeps following; dragging stops it;
clicking empty map stops it).

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-06 21:14 · robert-claude-laptop · none → Queued
<!-- queue:end -->
