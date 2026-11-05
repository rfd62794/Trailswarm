# PokeAgent: Explorer as behaviours - extract the demo's policy into small modules with decision logs

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` section 5 step 1 and 7a.
This supersedes `docs/directives/Explorer_Policy_Module_Directive.md` (Draft; leave that file alone).
**Do not list the tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree` are refused by the sandbox and
end the run); use `git ls-files`.

## 1. Why this exists

The rule-based Explorer reached the potion (14 presses), the house exit, the starter, the rival win, Route 1,
Viridian and Oak's Parcel inside a day, and beat the later low-level RL work. But its policy is one closure:
`agent_step()` inside `main()` of `tools/explore_demo.py` (lines ~935-1383 of a 1,562-line file), sharing state
through an `st` dict, next to a tk window and an HTTP API. Nothing else can call it, test it, or let RL choose
among its parts. `src/pokeagent/explorer.py` (296 lines) is an older, simpler port of the same ideas; it is
imported by `src/pokeagent/mcp_server.py` (`Explorer`), `tests/test_explorer.py` (`MapMemory`),
`tools/make_state.py` and `tools/rl_env.py` (`frame_lines`).

The next steps of the design (a stuck-watchdog, an RL selector over behaviours, seeding from Explorer runs)
all need the Explorer as named behaviours with explicit start, termination and failure, and a log of
behaviour-level decisions.

## 2. Scope (in order)

1. Turn `src/pokeagent/explorer.py` into a package `src/pokeagent/explorer/` whose `__init__.py` re-exports
   every name currently imported from `pokeagent.explorer` (`Explorer`, `MapMemory`, `frame_lines`, and any
   other public name in the old module), so all existing imports keep working unchanged.
2. Move the demo's pure helpers and memory out of `tools/explore_demo.py` into the package:
   `perceive.py` (`ahead_tiles, sprite_snapshot, npc_positions, ascii_vision, battle_view, effects, box_open,
   frame_lines, box_text, is_menu, party_hp`), `memory.py` (the demo's `MapMemory`, a superset of the old
   module's - merge them; keep the `runs/maps.json` schema byte-compatible), `dialog.py` (`learn_decision,
   yesno_answer, goal_menu_choice`), `battle.py` (`move_value, move_scores`).
3. Split `agent_step()` into behaviours, one module each under `src/pokeagent/explorer/behaviours/`, in the
   demo's existing priority order: `readiness` (input-readiness wait), `advance_dialog`, `menu`, `battle`,
   `catch`, `heal`, `replay_beat`, `goto`, `plan_goal`, `frontier`, plus the existing loop guards kept as one
   behaviour `guards` (the watchdog directive replaces them later - move them, do not redesign them).
4. `context.py` - an `ExplorerContext` dataclass replacing the `st` dict (emu, memory, goals, step, logger,
   and every field `st` held), and `selector.py` - `Selector(behaviours)` that, each step, asks behaviours in
   order and runs the first that applies.
5. Decision log: `decisions.py` writes `runs/<run>/decisions.jsonl`, one line per behaviour decision:
   `{"step", "behaviour", "rule", "button", "map", "x", "y", "goal_stage", "box", "battle", "outcome"}`
   (`outcome` = `moved | blocked | box | map_change | goal | none`).
6. `tools/explore_demo.py` becomes a thin wrapper: build the context, run the selector, keep its tk window,
   HTTP API and CLI flags working exactly as today. Target under 450 lines.

## 3. The work

Behaviour interface (in `behaviours/base.py`):

```python
class Behaviour(Protocol):
    name: str
    def applies(self, ctx: ExplorerContext) -> bool: ...      # start condition
    def step(self, ctx: ExplorerContext) -> Decision | None:  # one press (or None = nothing to do)
        ...
    def done(self, ctx: ExplorerContext) -> bool: ...         # termination (goal reached / box closed / ...)
    def failed(self, ctx: ExplorerContext) -> bool: ...       # gave up (cap hit, path blocked)

@dataclass
class Decision:  button: str; rule: str; why: str = ""
```

This is a move-and-split refactor. Preserve behaviour exactly: same rule order, same constants (stall
windows, caps, pace), same `maps.json` writes, same log lines. When a piece of `agent_step` does not fit one
behaviour cleanly, keep it in the closest behaviour and note it in the Report - do not change what it does.

## 4. What NOT to do

- Do not change any game logic, constant, threshold, or the `runs/maps.json` / `milestones.json` schemas.
- Do not touch `tools/rl_*.py` (including `tools/rl_env.py`), `src/pokeagent/options.py`, `tools/watch.py`,
  `tools/agent_window.py`, `tools/webview.py`, `docs/directives/Explorer_Policy_Module_Directive.md`.
- Do not add the watchdog, RL, or a viewer adapter (later directives).
- No new dependencies. No module over 300 lines.
- Layer rule: `pokeagent.explorer` imports only from `emulator, ram, screentext, screencontext, hexmap, names,
  goals, navigation` and itself - never from `tools/`.

## 5. Verification

- `uv run pytest -q` green (178 passed, 5 skipped before; your new tests added; `tests/test_explorer.py`
  passes unchanged).
- New tests with `FakeEmulator` (`pokeagent.emulator.FakeEmulator(memory: dict[int, int])`, `.set(addr, v)`,
  `.press(...)` records presses): each behaviour's `applies` true/false on a scripted RAM/tilemap setup;
  `Selector` picks the first applicable behaviour in order; `decisions.jsonl` lines have every field;
  `MapMemory` load/save round-trip of a small `maps.json` in `tmp_path` is byte-identical to the input.
- `uv run python -m py_compile tools/explore_demo.py` and
  `uv run python -c "import pokeagent.explorer as e; print(e.Explorer, e.MapMemory, e.frame_lines)"` succeed.
- Do NOT run `uv run pokeagent ...` or start the demo (no ROM in your worktree; the sandbox refuses the entry
  point). The controller runs the parity check on the laptop: the extracted Explorer from
  `baselines/bedroom.state` reaches S1-S5 within 25% of the demo's recorded presses.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-explorer-behaviours-directive`. Never commit to `main`, never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Commit in small steps (one per scope item) so a partial run is still reviewable.

## 7. Completion criteria

- [ ] `src/pokeagent/explorer/` package; all existing `pokeagent.explorer` imports still work
- [ ] `perceive.py`, `memory.py`, `dialog.py`, `battle.py`, `context.py`, `selector.py`, `decisions.py`
- [ ] `behaviours/` with `base.py` and one module per behaviour in section 2 item 3
- [ ] `tools/explore_demo.py` under 450 lines and still runs the same flags
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail); every new module under 300 lines
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail; line counts per new module and for `explore_demo.py`; a table mapping each part of the old
`agent_step` (by line range) to its behaviour; anything that did not fit cleanly.
