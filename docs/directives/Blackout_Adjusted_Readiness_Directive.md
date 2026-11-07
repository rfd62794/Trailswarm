# PokeAgent: blackout-adjusted readiness - each blackout raises that stage's margin, so the agent grinds more before re-boarding

**Read first:** `src/pokeagent/knowledge/readiness.py` (`MARGIN`, `assess`), `src/pokeagent/explorer/training.py`
(`readiness_for`, `required_level`, `under_level`, `stage_goal`, `_cache`), `src/pokeagent/explorer/grind.py`
(`record_battle_result`, `GRIND_BLACKOUTS`), `src/pokeagent/explorer/behaviours/plan_goal.py`, `tests/test_readiness_all_bosses.py`,
`tests/test_grind.py`. If any of these is missing, stop and write that in the Status row. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-07): "Should blacking out trend toward more leveling after?" Yes. Today the readiness bar is one global
constant, `knowledge/readiness.py` `MARGIN = 0.30` (the HP fraction that must be left on the mons that fought, in the simulated
duel), so a stage that has just beaten the agent 95 times is judged exactly like a stage it has never seen. Evidence
(`docs/superpowers/specs/2026-11-07-save-state-ledger.md`, "Rival / captain note"): 309 blackouts on the S.S. Anne maps, the
rival killing a Lv29 lead team that readiness called ready. The simulation is optimistic where the real fight (items, crits, AI
switches) is not; the blackout count is the measured correction. After a blackout, the readiness check must demand a higher lead
level before the agent tries again, so it grinds more.

## 2. Scope (in order)

1. New pure module `src/pokeagent/knowledge/blackout_tax.py`.
2. `knowledge/readiness.py`: `assess(..., margin: float = MARGIN)`; behaviour with the default is byte-for-byte unchanged.
3. `explorer/training.py`: a process-wide tax table consulted by `readiness_for` (so every caller sees it with no signature change,
   including `ship_gate.under_level`, which you must NOT edit).
4. `explorer/grind.py::record_battle_result`: record a blackout / a win into the shared learned data. `GRIND_BLACKOUTS` logic is unchanged.
5. `explorer/behaviours/plan_goal.py` + `explorer/context.py`: publish the current stage and feed the tax table from the learned data each step.
6. Tests: `tests/test_blackout_tax.py`.

## 3. The work

### 3.1 Where the learned value lives

The shared learned data is `ctx.mem.data`, the dict behind `runs/maps.json` (`MapMemory`, `explorer/memory.py`, saved atomically by
`MapMemory.save`). It already holds per-subject learned tables as top-level keys (`battle_lessons`, `training`, `threat_by_species`).
Add one more top-level key, **`blackout_tax`**, shape:

```json
{"blackout_tax": {"rival_ss_anne": {"steps": 3}, "beat_misty": {"steps": 1}}}
```

The key of each entry is a stage goal exactly as `training.stage_goal(goals)` returns it (a key of `TRAIN_LEVEL_BY_GOAL`).
`steps` is an INTEGER (never store a float; derive the margin from it). A stage with zero steps is removed from the dict.
It has the same cross-process semantics as `battle_lessons` (read at start, written by `save`); do not add locking or a new file.

### 3.2 `blackout_tax.py` (pure, no emulator, no I/O)

```python
TAX_STEP = 0.10          # margin added per blackout step
TAX_CAP = 0.40           # the most that can be added
MAX_STEPS = 4            # round(TAX_CAP / TAX_STEP)

def steps(data: dict, goal: str) -> int            # data.get("blackout_tax", {}).get(goal, {}).get("steps", 0), clamped to 0..MAX_STEPS
def extra_margin(data: dict, goal: str) -> float   # round(steps * TAX_STEP, 2)
def extras(data: dict) -> dict[str, float]         # {goal: extra_margin} for every goal with steps > 0
def on_blackout(data: dict, goal: str) -> int      # steps = min(steps + 1, MAX_STEPS); creates the key; returns the new steps
def on_win(data: dict, goal: str) -> int           # steps = max(steps - 1, 0); removes the goal's entry at 0; returns the new steps
```

All five tolerate a missing or malformed `blackout_tax` key (treat as empty; never raise).

### 3.3 `readiness.py` and `training.py`

- `assess(party, boss, label, kb=None, margin=MARGIN)`: replace the two uses of `MARGIN` (`ready = score >= margin`, and the
  `fight(...) >= margin` search for `required`) with the parameter. Add `required` unchanged otherwise. The log text gains nothing here.
- `training.py`: add a module dict `_tax: dict[str, float] = {}` and `set_blackout_tax(extras: dict[str, float]) -> None` (replaces it;
  `{}` clears). In `readiness_for`, compute `margin = MARGIN + _tax.get(goal, 0.0)`, include `margin` in the `_cache` key, and pass
  `margin=margin` to `assess`. With `_tax` empty, results are identical to today. `required_level`'s clamp to
  `TRAIN_LEVEL_BY_GOAL[goal] + CAP_ABOVE_TABLE` stays: the tax raises the target up to that clamp, not past it.

### 3.4 Recording and publishing

- `context.py`: add `stage_goal: str | None = None` to the context (next to `readiness_note`).
- `plan_goal.py`: where it already has `goals_now_all`, set `ctx.stage_goal = stage_goal(goals_now_all)` and call
  `training.set_blackout_tax(blackout_tax.extras(ctx.mem.data))` once per planning step (cheap dict work). In the existing
  `[readiness]` log line, append ` (+{extra:.2f} blackout margin)` only when the stage's extra is above 0.
- `grind.py::record_battle_result(ctx, *, won, moved_away, trainer=False)`: after the existing logic, if `ctx.stage_goal` is set:
  `moved_away and not won` -> `blackout_tax.on_blackout(ctx.mem.data, ctx.stage_goal)`; `won and trainer` -> `blackout_tax.on_win(...)`.
  Rationale for the asymmetry (put it in the docstring): any blackout counts against the stage, but only a won TRAINER battle
  decays it; wild wins are cheap and would erase the tax within a few steps. A flee changes nothing (as today).
- The ONE-line caller change: in `explorer/behaviours/battle.py` the call is `record_battle_result(ctx, won=won, moved_away=moved_away)`
  (around line 235); change it to also pass `trainer=trainer` (the local `trainer` is defined three lines above it). Touch no other line
  of `battle.py` (another directive edits the battle record there).

## 4. What NOT to do

- Do not edit `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`.
- `GRIND_BLACKOUTS`, `GrindBudget`, `battle_outcome` and the `blackouts_row` counter stay exactly as they are (the budget still lifts
  the gate after 2 blackouts in a row; the tax only raises the bar while the gate is on).
- No new file for the learned value (`runs/maps.json` via `ctx.mem.data` only), no new dependency, no float stored in `blackout_tax`.
- Do not change `MARGIN`, `CAP_ABOVE_TABLE`, or the fallback table. No module over 300 lines.
- Pure functions + tests: no emulator, no ROM (`kb/rom_tables.json` is gitignored and absent in your worktree).

## 5. Verification

- `uv run pytest -q tests/test_blackout_tax.py` - new tests:
  1. `on_blackout` x6 on one goal -> `steps == 4`, `extra_margin == 0.4` (cap holds); `on_win` x2 -> `steps == 2`; down to 0 removes the goal key.
  2. `extras`, `steps`, `extra_margin` tolerate `{}`, `{"blackout_tax": None}`, `{"blackout_tax": {"g": "x"}}` without raising.
  3. `assess(..., margin=0.7)` needs a lead level >= the `margin=0.3` result for the same party/boss (use the synthetic cartridge exactly as
     `tests/test_readiness_all_bosses.py` does: `from test_knowledge import SYN, _starter`, the `_rom(monkeypatch, ...)` helper pattern,
     and `training._cache.clear()`), and the default call equals `margin=MARGIN`.
  4. `training.set_blackout_tax({"beat_surge": 0.4})` makes `training.readiness_for(goals, [water]).required` larger than with `{}` for the
     same goals and party, and `set_blackout_tax({})` restores the old value (always clear in a `finally`/fixture so other tests are unaffected).
  5. `record_battle_result` with a `SimpleNamespace` ctx (`stage_goal="rival_ss_anne"`, `mem=SimpleNamespace(data={})`, `blackouts_row=0`):
     a blackout adds a step and still bumps `blackouts_row`; a trainer win removes one and resets `blackouts_row`; a wild win only resets the row;
     with `stage_goal=None` nothing is recorded.
- `uv run pytest -q` green; paste the before/after tails (existing readiness / grind / training tests must pass unedited).
- Do NOT run `uv run pokeagent ...`.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-blackout-adjusted-readiness-directive`. Never commit to `main`; never push; never deploy. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## Repo facts (verified 2026-11-07 on the live checkout; they are pasted because you cannot look outside the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`.
- Full suite: `uv run pytest -q` (about 80-120 s; 1419 passed, 18 skipped on a clean tree per the controller). Per item:
  `uv run pytest -q tests/<file>`.
- `roms/`, `baselines/` and `runs/` are gitignored. **Your worktree has NO ROM, no `.state` baselines and no `runs/` data.**
  Every test uses `FakeEmulator` (`from pokeagent.emulator import FakeEmulator`, defined in `src/pokeagent/emulator.py`):
  `FakeEmulator({addr: byte, ...})` with `.memory` (dict), `.read(addr)`, `.read_range(start, n)`, `.set(addr, v)`,
  `.frames`, and `save_state(path)` / `load_state(path)` which write/read the memory dict as JSON. Use `tmp_path` for files.
- The existing test helper to copy from is `tests/test_state_fingerprint.py::world()`, which builds a FakeEmulator on map 0x61:

```python
LEAD = 0xD16B
def world(respawn=5, hp=79, mx=79, level=29, potions=2):
    emu = FakeEmulator({0xD35E: 0x61, 0xD362: 13, 0xD361: 6, 0xD719: respawn, 0xD356: 0b11,
                        0xD347: 0x00, 0xD348: 0x12, 0xD349: 0x34, 0xD057: 0, 0xD163: 1, 0xD164: 179})
    for off, v in ((0, 179), (1, hp >> 8), (2, hp & 255), (33, level), (34, mx >> 8), (35, mx & 255)):
        emu.memory[LEAD + off] = v
    emu.memory.update({0xD31D: 1, 0xD31E: 0x14, 0xD31F: potions, 0xD320: 0xFF})
    return emu
```

  That file also shows how tests import the `tools/` scripts: `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))`
  then `import seg_store as ss`.
- **Files you must NOT modify** (another agent is working on the walk-off there): `src/pokeagent/explorer/ship_gate.py`,
  `planner.py`, `planner_east.py`, `planner_checkpoint.py`. Read them if you must; do not edit them.

## 7. Completion criteria

- [ ] `knowledge/blackout_tax.py` with the five functions and three constants; the `blackout_tax` key documented in its docstring
- [ ] `assess(margin=...)`, `training.set_blackout_tax`, `readiness_for` honouring it, with an unchanged result when no tax is set
- [ ] `record_battle_result` records blackouts / trainer wins; the one-line `battle.py` change; `plan_goal` publishes `ctx.stage_goal` and the tax
- [ ] `tests/test_blackout_tax.py` passes; `uv run pytest -q` green (paste the tail); `git diff --stat main` pasted
- [ ] Status row moved to Review with the branch name

## 8. Report

Findings first: test tails (before/after), `git diff --stat`, the final names/signatures, how the tax reaches `ship_gate` without an edit,
any caller of `required_level`/`readiness_for` you found that this does not reach, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 12:15 · robert-claude-laptop · none → Draft — Claude 2026-11-07: blackout tax on readiness margin
- 2026-11-07 12:16 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override candidate: dispatch-path-missing on new module and new test (greenfield)
<!-- queue:end -->
