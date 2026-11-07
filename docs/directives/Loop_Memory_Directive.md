# PokeAgent: loop memory - measure progress as well as success, and stop repeating known non-useful actions (NPC bumping, repeated dialog, repeated menu paths, repeated blocked walks)

**Depends on (merged to main; if missing from your worktree, stop and write that in the Status row):** PR #150 (branch `fix/route24-blocked-tile`, OPEN at the time of writing): `explorer/blocked_cap.py` (`BLOCKED_PRESS_CAP = 20`, `note(streak, before, name, moved)`), `ctx.deciding_rule`, `ctx.blocked_streak`, the `press_interact.py` change (`EXPLORE_RULES`, the cap temp-blocking the tile ahead). It is the FAST path for one kind of loop and stays exactly as it is. PR #144 (training progress) is merged: `src/pokeagent/training_progress.py` (`marks`, `gained`) and `tools/swarm_watch.py::ProgressWatch`.
**Do not list the tree recursively**; use `git ls-files`.

**Read first (all in the worktree):** `src/pokeagent/stalls.py` (`likely_cause`, `build_dossier`, `make_signature`), `src/pokeagent/training_progress.py`, `tools/swarm_watch.py` (`ProgressWatch`: read only, its thresholds do NOT change), `src/pokeagent/explorer/engine.py` (`Engine.step`: the `choose` -> `veto` / `toss_veto` -> `presser.press` -> `classify_outcome` -> `make_record` sequence, `_note_novelty`), `src/pokeagent/explorer/selector.py` (`Selector.choose`), `explorer/retalk_veto.py` (the existing veto pattern: a rule name and a "B instead"),
`explorer/behaviours/guards.py` (`LoopGuard`: 60/150-press windows, `shake`, endless-A guard, `DIR_FAIL_BACKOUT`; `StallGuard`: 15 same-signature steps -> escalate), `explorer/behaviours/already_out.py` (`AlreadyOutGuard`, the repeat-screen guard of PR #145), `src/pokeagent/novelty/features.py` (`Snapshot`, `read_snapshot`, `flag_bits`, `features`), `explorer/party_log.py`, `explorer/press.py` (`write_transition`), `explorer/memory.py` (`MapMemory.save`, `data`), `tools/swarm_merge.py` (`merge_memory`: the max/union conventions), `docs/KNOWLEDGE.md` (the stall entries, the Route 24 entry at the end), `tests/test_stalls.py`, `tests/test_novelty.py`, `tests/test_explorer_behaviours.py` (`Engine(` test patterns), `tests/test_already_out.py`.

## 1. Why this exists

Robert (2026-11-07): "We need to teach it to measure progress as well as success, as well as stall periods and loops, instead of continuing to cycle known non-useful combinations and tactics, including NPC Bumping."

Evidence today:
- Route 24, 2026-11-07: ~1,500 UP presses into a beaten trainer who stands still (PR #150: the cap of 20 blocked presses now temp-blocks that tile), and a NEW loop found by that PR's follow-up: at Route 24 (5,20) about 1,700 presses of A/B on a wandering trainer's dialog. The press count was huge, the tile set tiny, nothing was learned: no stall guard fired in time because each guard watches ONE shape (blocked moves, 40 A in a row, 60/150 presses on few tiles, 15 identical (map, x, y, goals) steps).
- The guards are all reactive, per-shape and forgetful: each fires after the waste, and nothing remembers across the run, let alone across runs, that "A here, facing this, with this text, does nothing". The same dialog trap was re-entered by every agent that reached it.
- The swarm's `ProgressWatch` judges progress only from outside the run (new tiles in a press window, goals, XP via `training_progress`); the run itself has no notion of "steps since I last learned or gained anything".

This directive adds ONE mechanism: a per-step progress signal, an in-run ledger of (situation, action) -> progress or not with a veto after N fruitless repeats, and a cross-run memory of recurring dead actions that decays. NPC bumping, repeated dialog A/B, repeated menu paths and repeated blocked walks are all instances of the same rule: no special cases per loop kind.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `runs/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure `tests/test_resources.py::test_lock_takeover_is_exclusive`, unrelated: ignore it and say so if it fails for you).
- `runs/`, `roms/`, `baselines/`, `kb/rom_tables.json` are gitignored: no run data in your worktree. Tests use `FakeEmulator` (`from pokeagent.emulator import FakeEmulator`: `FakeEmulator({addr: byte})`, `.memory`, `.read`, `.read_range`, `.set`), `tmp_path`, and fixture data you write in the test. Engine/behaviour test patterns: `tests/test_explorer_behaviours.py`, `tests/test_bandit.py`, `tests/test_exploration_momentum.py`, `tests/test_novelty.py`, `tests/test_already_out.py`.
- **The engine step today** (`src/pokeagent/explorer/engine.py`, `Engine.step`): `decision = self.selector.choose(ctx)`; `party_log.of(ctx).tick(ctx)`; if there is no button, return; `why_veto = veto(ctx, decision)` (retalk: replaces the decision with `Decision("B", "retalk_veto", ...)`); `toss_veto(...)` the same way; then `before = (m, x, y)`, `ctx.deciding_rule = decision.rule` (PR #150), `self.presser.press(...)`, `after = ctx.pos()`, `classify_outcome(...)`, `make_record(...)` -> `decisions.jsonl`, `self._note_novelty()` (calls `ctx.novelty.observe(ctx.emu, ctx.step)` when novelty is on). The new veto belongs beside `veto`/`toss_veto`; the progress observation beside `_note_novelty`.
- `Selector.choose(ctx)` walks `default_behaviours()` in order and returns the first behaviour's non-None decision (it sets `decision.behaviour = behaviour.name`). It has NO way to skip a behaviour: add one optional argument `skip: frozenset[str] = frozenset()` that makes the loop pass over behaviours whose `name` is in it (default behaviour unchanged; the existing tests stay green).
- Decision records (`decisions.jsonl`): `{"step", "behaviour", "rule", "button", "map", "x", "y", "goal_stage", "box", "battle", "outcome", "reversal"}`; `outcome` from `classify_outcome` is one of moved / blocked / none / goal ... (read the function; do not assume).
- Per-step state available WITHOUT pixels: `ctx.view` (`m, x, y, tm, box, lines, battling`), `ctx.facing`, `ctx.pos()`, `ctx.goal_steps` (goal -> step), `ctx.step`, `ctx.mem.data["maps"][str(map)]["visited"]` (tile -> count; a tile is NEW when it is absent before the press), `ctx.emu.read(0xD057)` (battle flag), `ctx.battles_won`, `ctx.battle_log`. `novelty.features.read_snapshot(emu)` returns a `Snapshot(map, x, y, flags: bytes (0xD747, 320 bytes, wEventFlags), bag, pc, money, party ((species, level, exp, moves, ident),...), in_battle, enemy)`; `features.flag_bits(cur_flags, prev_flags)` returns newly set flag bit indexes; `training_progress.marks(party_rows)` / `gained(before, after)` need `[species, level, exp, ...]` rows (the Snapshot party tuples have that shape in positions 0-2).
- Screen text: `ctx.view.lines` is the on-screen text lines when a box is up (empty otherwise). The loop guards note that printing text changes the screen every press, so a text hash that includes a PARTIALLY printed box changes each press: that is correct for this feature (a box still printing is not a loop) and it is why the situation includes the text hash.
- Run files written in the run dir today: `meta.json`, `decisions.jsonl`, `levels.jsonl`, `transitions.jsonl` (a run dir is `runs/explore-YYYYMMDD-HHMMSS-<pid>/`). New files this directive adds: `progress.jsonl`, `loops.jsonl`.
- Shared memory: `ctx.mem.data` (saved by `MapMemory.save` to the shared maps file; the swarm merges per-agent memories with `tools/swarm_merge.py::merge_memory(dst, src, edits=None)`, which uses MAX for counts and union for sets, never sum, because every agent starts from a copy of the shared memory). New top-level key this directive adds: `"loops"`.
- Stall dossier: `stalls.build_dossier(root, run, stall=None, maps_doc=None, rdir=None, ...)` assembles `{run, t, slot, reason, presses, map, x, y, segment, seed, starter, goal_stage, signature, signature_key, dominant, histogram, text_on_screen, sprites_near, start_state, likely_cause, decisions_tail}`; it reads the run dir's `decisions.jsonl` / `transitions.jsonl` through `_jsonl_tail(path, n)`.
- **Files you must NOT modify:** `src/pokeagent/explorer/planner*.py`, `ship_gate.py` (planners), `tools/swarm_watch.py` (ProgressWatch thresholds: `WINDOW_PRESSES`, `MIN_NEW_TILES`, `HUNG_S`, `START_GRACE_S` and the rules stay as they are), `explorer/blocked_cap.py` (the fast path stays), the existing guards' thresholds (`LoopGuard`, `StallGuard`, `AlreadyOutGuard`), and any bandit/RL code.

## 3. Scope (one PR, in order)

1. `src/pokeagent/explorer/progress.py` (pure): the per-step progress signal and the steps-since-progress counter; `progress.jsonl`.
2. `src/pokeagent/explorer/loop_memory.py` (pure ledger) and `loop_veto.py` (the engine seam): in-run veto after N fruitless repeats; `loops.jsonl`.
3. Cross-run persistence: promotion into `ctx.mem.data["loops"]`, probe/decay, and `swarm_merge.merge_loops`.
4. Stall dossier gains the top vetoed actions.
5. Tests.

## 4. The work

Every constant is NAMED with a comment that it is an untuned first value. Each new module under 300 lines.

### 4.1 `explorer/progress.py`: progress, not just success

```python
PROGRESS_LOG_EVERY = 100        # steps between heartbeat rows in progress.jsonl when nothing new happened

REASONS = ("tile", "map", "flag", "xp", "level", "goal", "money", "item", "battle", "hp")

def progress_reasons(prev: Snapshot | None, cur: Snapshot, new_tile: bool, goals_before: int, goals_after: int,
                     battle_ended: bool) -> list[str]
class ProgressTracker:
    steps_since: int            # presses since the last progress
    def observe(self, step: int, prev, cur, new_tile: bool, goals_before: int, goals_after: int, battle_ended: bool) -> list[str]
```
A press made progress when ANY of these holds (each is a reason string): `tile` (the tile the player is on after the press was never visited before this press: use the map memory's `visited` table BEFORE the press adds it, or equivalently ask `Engine` to pass `new_tile`), `map` (the map id changed), `flag` (`features.flag_bits(cur.flags, prev.flags)` is non-empty), `xp` / `level` (`training_progress.gained(marks(prev.party), marks(cur.party))` and whether a level rose), `goal` (a goal landed: `goals_after > goals_before`), `money` (money changed), `item` (any bag item quantity changed or a new item appeared), `battle` (a battle ended this press: `prev.in_battle` and not `cur.in_battle`), `hp` (the party's total current HP rose - a heal at the nurse or a Potion). The first `hp` reason is added to the coordinator's list because a heal visit is useful work with no other trace; say so in your report. NO pixels, no screen scraping; reuse `novelty.features` (do not copy `flag_bits`).
`ProgressTracker.observe` returns the reasons (empty list = no progress), resets `steps_since` to 0 on progress and increments it otherwise. `read_snapshot` costs a handful of RAM reads: call it once per press AFTER the press and keep the previous one; when `ctx.novelty` is already on, reuse its snapshot if it exposes one, else read directly (do not read twice).
`ctx.steps_since_progress: int` (new context field) mirrors the counter. `progress.jsonl` (in the run dir, one JSON object per line, flushed like `transitions.jsonl`): a row on every progress event `{"step", "frame": None-or-known, "reasons": [...], "since": <steps since the previous progress>}`, plus a heartbeat `{"step", "reasons": [], "since": n}` every `PROGRESS_LOG_EVERY` steps with no progress. Write failures are swallowed with one log line, never stop a run.

### 4.2 `explorer/loop_memory.py` and the veto seam

```python
LOOP_NO_PROGRESS_N = 3         # the same (situation, action) with no progress this many times -> veto
LOOP_VETO_STEPS = 60           # how long the veto holds in that situation (steps); then the action is allowed once more
MAX_RECHOOSE = 3               # times the engine asks the selector for another behaviour before giving up on the veto
LEDGER_MAX = 2000              # situations kept in the in-run ledger (oldest dropped)
NEVER_VETO = frozenset({"battle", "battle_moves", "battle_text_wait", "catch", "switch_out", "party_order", "settle_wait"})   # behaviours whose repeated presses are legitimate; extend only with a comment saying why

@dataclass(frozen=True)
class Situation: map: int; x: int; y: int; facing: str; text: int; battle: bool    # text = stable hash of the normalised on-screen text lines
def situation_of(ctx) -> Situation
def text_hash(lines: list[str]) -> int     # " ".join(line.lower().split()) joined by "|", hashed with hashlib (NOT Python's salted hash) and truncated to 8 bytes
class LoopLedger:
    def record(self, sit: Situation, action: str, progressed: bool, step: int) -> LoopEvent | None   # after a press: progress resets that entry's fruitless count; else count += 1; returns a "veto" event when count reaches LOOP_NO_PROGRESS_N
    def vetoed(self, sit: Situation, action: str, step: int) -> bool
    def top(self, n: int = 5) -> list[dict]
```
- The ACTION is the button pressed (`decision.button`); the rule/behaviour that proposed it is logged but is not part of the key (one mechanism: whichever behaviour asks for "A here, with this text" meets the same veto).
- A press is fruitless when `progress_reasons(...)` is empty. The ledger counts CONSECUTIVE fruitless repeats of the same (situation, action); a progress reset clears that entry. Entries older than `LOOP_VETO_STEPS * 4` steps with no new press are dropped (bounded memory, `LEDGER_MAX`).
- **Why the text is in the situation:** a text box that is still printing, or a dialog that advances page by page, changes the on-screen text every press, so it is a different situation each time and is never a loop; only the SAME text (a dialog that restarts, a menu that returns to itself, a wall that prints nothing) repeats a situation. Test this explicitly.
- **The veto seam** (`explorer/loop_veto.py`, called from `Engine.step` right after `choose` and BEFORE the retalk and toss vetoes): if `decision.behaviour in NEVER_VETO` -> no veto. If the ledger says `(situation_of(ctx), decision.button)` is vetoed (or the shared memory says so, 4.3): ask the selector again with `skip=frozenset({decision.behaviour})` up to `MAX_RECHOOSE` times, taking the first decision whose button is NOT itself vetoed in this situation, then log ONE line per veto: `[loop_veto: A at map 35 (5,20) facing LEFT, same screen, no progress x3 -> vetoed for 60 steps; rule talk_wanderer proposed it; chose DOWN by frontier]` (use the real rule names) and write a `kind: "veto"` row to `loops.jsonl`. If every re-choose is also vetoed, the original decision goes through with a `kind: "veto_exhausted"` row (never deadlock; the existing guards still own escalation). The engine's other behaviour (press, record, novelty) is unchanged.
- **One mechanism, no special cases:** NPC bumping (same tile, same direction, blocked, no text) is `(situation, UP)` repeated 3x with no progress; repeated dialog is the same text and `A`; a repeated menu path returns to the same screen text and the same button; a repeated blocked walk is the first again. The #150 blocked cap (20) is the FAST path for the routing side (it temp-blocks the tile in the world graph so the PLANNER stops targeting it): it still fires on its own count and is not modified; the loop veto acts earlier (3) on the press itself and the two coexist. A test shows both fire in their own right on a repeated blocked move.
- `loops.jsonl` (run dir, one row per event, flushed): `{"step", "kind": "veto"|"veto_exhausted"|"probe"|"promote"|"expire", "map", "x", "y", "facing", "text": <hash int>, "battle", "button", "rule", "behaviour", "no_progress": n, "veto_until": step, "source": "run"|"shared"}`; at shutdown one `{"kind": "ledger", "top": [...]}` row with the 5 most-vetoed (situation, action) entries. Review tools read it later (do not build a reader here).

### 4.3 Persistence across runs: promotion, probe, decay, merge

- A veto in this run is a "recurrence candidate" keyed `"{map},{x},{y},{button}"` (NOT including the text hash or facing: a new agent should skip a dead action on sight at that tile). At run end (and every `PROMOTE_FLUSH_STEPS = 500` steps), fold this run's veto keys into `ctx.mem.data["loops"]`:
  `loops[key] = {"runs": [run ids, newest last, at most LOOP_RUNS_KEPT = 10], "last": <epoch seconds>, "clear": <epoch seconds or 0>}` (add this run's id once; update `last`).
- **Promotion rule:** an entry is ACTIVE (applied to new runs) when `len(runs) >= LOOP_PROMOTE_RUNS` (K = 3 distinct runs), `last > clear`, and `now - last < LOOP_TTL_DAYS * 86400` (`LOOP_TTL_DAYS = 7`, so a bug that gets fixed stops being vetoed even if nobody ever probes it). A `kind: "promote"` row goes to `loops.jsonl` the first time a run applies it.
- **Applying an active shared entry** (so new agents skip known dead actions on sight): in `loop_veto`, when the player stands on a tile `(map, x, y)` with an ACTIVE entry for the button the decision wants, treat that (tile, button) as vetoed, EXCEPT one PROBE per `PROBE_EVERY = 200` steps per key: the probe lets the action through; if the press makes progress, the entry's `clear` is set to now (the dead action is alive again, a `kind: "probe"` row with `ok: true`), else the probe's fruitless result is just recorded (`ok: false`) and the entry stays active.
- **Merge** - handler name: `tools/swarm_merge.py::merge_loops(dst: dict, src: dict) -> None`, called from `merge_memory` next to the other per-key merges. Rule (never sum): for each key, `runs` = union of both lists (order preserved, dst first, capped to the newest `LOOP_RUNS_KEPT`), `last` = max, `clear` = max. Also drop entries whose `last` is older than `LOOP_TTL_DAYS` at merge time and any entry whose `clear >= last` and `len(runs) < LOOP_PROMOTE_RUNS`. `merge_loops` must be idempotent (merging the same src twice changes nothing).
- Shared state is DATA, not instructions: a malformed `loops` value is ignored (never raises, never vetoes).

### 4.4 Stall dossier: top vetoed actions

`stalls.build_dossier` gains a key `top_vetoed`: the five most frequent `kind == "veto"` / `"veto_exhausted"` (situation, button) groups from the run's `loops.jsonl` (missing file -> `[]`), each `{"map", "x", "y", "facing", "button", "rule", "count"}`, and `since_progress`: the latest `since` from `progress.jsonl` (or None). `stalls.likely_cause` is NOT changed. Existing dossier keys and `tests/test_stalls.py` expectations stay intact (the new keys are additive).

### 4.5 Tests (all fixtures; no ROM, no emulator run)

`tests/test_progress.py`: each reason fires on a crafted `Snapshot` pair (tile, map change, new flag bit, XP gain, level gain, goal landed, money change, item add/remove, battle end, HP rise), a plain blocked press yields `[]`, `steps_since` increments and resets, heartbeat rows at `PROGRESS_LOG_EVERY`, a write failure is swallowed.
`tests/test_loop_memory.py` (pure): `text_hash` is stable across runs/processes and insensitive to case/whitespace; the ledger vetoes exactly at `LOOP_NO_PROGRESS_N` consecutive fruitless repeats of the same `(situation, button)`, a progress press resets the count, a different text/facing/tile is a different situation, the veto expires after `LOOP_VETO_STEPS`, `NEVER_VETO` behaviours are never vetoed, `LEDGER_MAX` bounds memory, a printing box (text changing each press) never vetoes.
`tests/test_loop_veto_engine.py` (FakeEmulator + `Engine`, pattern of `tests/test_explorer_behaviours.py`): **loop reproduction: the same screen and the same button 3 times with no progress -> on the 4th the engine asks the selector for another behaviour (`Selector.choose(..., skip=...)` is exercised), the log line names the rule, and `loops.jsonl` gets a `veto` row**; veto exhausted when every behaviour proposes the same button (decision goes through, `veto_exhausted` row); `Selector.choose` without `skip` is unchanged (the existing selector tests unedited); the blocked-move case: a repeated blocked UP at one tile is vetoed at 3 while `blocked_cap` still counts to 20 independently.
`tests/test_loop_persistence.py`: fold a run's vetoes into `ctx.mem.data["loops"]`; an entry becomes active only at `LOOP_PROMOTE_RUNS` distinct runs; TTL expiry; a successful probe sets `clear` and deactivates it, a failed probe leaves it active; `PROBE_EVERY` spacing; a malformed `loops` value is ignored.
`tests/test_swarm_merge_loops.py`: `merge_loops` union/max/cap rules, never sums, idempotent, drops stale entries, ignores malformed input, and `merge_memory` calls it (the existing `tests/` for `swarm_merge` stay green).
`tests/test_stalls.py` (add cases): the dossier carries `top_vetoed` and `since_progress` from fixture `loops.jsonl` / `progress.jsonl`, and lacks nothing when those files are missing.

## 5. What NOT to do

- No RL / bandit changes. No edits to `planner*.py`, `ship_gate.py`, `blocked_cap.py`, `tools/swarm_watch.py` (ProgressWatch thresholds unchanged). Do not change the existing guards (`LoopGuard`, `StallGuard`, `AlreadyOutGuard`) or their numbers; this mechanism is added beside them, not instead.
- No pixels or image hashing: the situation uses RAM and the on-screen text lines only. No special-casing by loop kind, map, NPC or trainer. Do not veto anything inside a battle (`NEVER_VETO` plus the situation's battle flag; battle loops belong to the battle code). No emulator runs by you, no `uv run pokeagent ...`.
- The shared `loops` memory is advisory and decays: never make a promoted entry permanent, never block the only route (the probe and TTL exist for that). No new dependencies; modules under 300 lines.

## 6. Verification

- `uv run pytest -q tests/test_progress.py tests/test_loop_memory.py tests/test_loop_veto_engine.py tests/test_loop_persistence.py tests/test_swarm_merge_loops.py tests/test_stalls.py tests/test_explorer_behaviours.py` - new and neighbouring tests pass (paste the tail).
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed.
- **Controller validation (not Devin; the ROM is on the laptop):** a headless segment on Route 24 (for example from `runs/checkpoints/nugget_bridge.state`, where the wandering-trainer talk loop at (5,20) was found): confirm a `loop_veto` log line and `loops.jsonl` rows instead of ~1,700 A/B presses, `progress.jsonl` showing steps-since-progress, a dossier with `top_vetoed` if the run stalls, and that a normal run (no loop) shows no vetoes and unchanged frames.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-loop-memory-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `explorer/progress.py` (progress reasons, `ProgressTracker`, `ctx.steps_since_progress`, `progress.jsonl`); tested
- [ ] `explorer/loop_memory.py` + `loop_veto.py`; `Selector.choose(skip=...)`; `Engine.step` seam; N=3 veto, re-choose, exhaustion, `loops.jsonl`; the same-screen-and-button-3x repro test passes
- [ ] Cross-run `ctx.mem.data["loops"]` with promotion at K runs, probe, TTL and `swarm_merge.merge_loops`; tested
- [ ] Stall dossier carries `top_vetoed` and `since_progress`
- [ ] The new test files pass; neighbouring tests unedited and green; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures and every named constant, the exact `NEVER_VETO` list and why, where the veto and the progress observation sit in `Engine.step`, how the situation text is hashed, the `merge_loops` call site, every existing test you had to touch, and anything that did not fit (for example if `classify_outcome` or the snapshot reuse differed from this directive's section 2).

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-loop-memory-directive |
| Base branch | - |
| Base commit | e37ee66bc3e910a45b8fb9f129b8a84b844705bd |
| Head commit | bfce37814396f52c7febfddef9f75cdfe9cc5d21 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 15:55 · robert-claude-laptop · none → Draft — Claude 2026-11-07: progress signal + loop memory (veto, cross-run promotion with decay); depends on PR #150
- 2026-11-07 15:55 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; depends on PR #150 merging; lint_override: dispatch-path-missing on greenfield modules/tests and gitignored kb/ path
- 2026-11-07 16:11 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing on greenfield modules/tests and gitignored kb/rom_tables.json; known false positives. Dependency PR #150 (blocked_cap, ctx.deciding_rule) merged.
- 2026-11-07 16:11 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-loop-memory-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VXMJ5HCPSC7GB4XVR23B53
- 2026-11-07 16:16 · dispatcher · launched pid=832; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-loop-memory-directive; provisioned: uv sync --frozen
- 2026-11-07 16:29 · devin · In progress → Review — Done + verified. Tail before: 1550 passed, 40 skipped; after: 1592 passed, 40 skipped (full suite, 119s); targeted run: 80 passed. diff --stat vs base e37ee66: 17 files, +1205/-8; the extra entries in `git diff --stat main` are main's own drift since base (legality/lineage/envelope deletions), not this branch. New: explorer/progress.py (progress_reasons REASONS tile/map/flag/xp/level/goal/money/item/battle/hp, ProgressTracker.steps_since -> ctx.steps_since_progress, ProgressLog -> progress.jsonl, PROGRESS_LOG_EVERY=100), explorer/loop_memory.py (Situation, sha256-text hash truncated to 8 bytes, LoopLedger, shared-table helpers; LOOP_NO_PROGRESS_N=3, LOOP_VETO_STEPS=60, MAX_RECHOOSE=3, LEDGER_MAX=2000, ENTRY_IDLE_DROP=240, PROMOTE_FLUSH_STEPS=500, LOOP_RUNS_KEPT=10, LOOP_PROMOTE_RUNS=3, LOOP_TTL_DAYS=7, PROBE_EVERY=200 — all untuned first values), explorer/loop_veto.py (Loops facade on ctx.loops, check/record/fold/finish, loops.jsonl). Seams in Engine.step: loop_veto.check right after choose + before retalk/toss vetoes; _note_progress right after _note_novelty (reuses ctx.novelty.prev snapshot when present, else one read_snapshot per press — never two); loop_veto.finish inside `if ctx.done` before mem.save. NEVER_VETO = {battle, battle_moves, battle_text_wait, catch, switch_out, party_order, settle_wait} — repeated presses there are legitimate (battle menus/party ops/waits); battle flag in Situation also blocks vetoes entirely. Selector.choose gained skip: frozenset (accumulates over vetoed alternatives; empty-button/no-press alternatives accepted, None => veto_exhausted). loops.jsonl kinds: veto/veto_exhausted/probe/promote/expire/ledger. merge_loops (doc-level dst/src) called from merge_memory just before dst['updated']; union of runs capped to newest 10, max last/clear, drops stale/cleared-underpromoted/malformed, idempotent. Dossier gained top_vetoed + since_progress (LOOPS_ROWS=5000 scan). Existing tests touched: tests/test_explorer_behaviours.py only — 'training_progress' added to the layering allowed-set (progress.py imports it); test_stalls.py got additive cases only. Notes: Snapshot gained `hp` (party total HP) — the only way the directive's `hp` reason is computable from snapshots; it is the coordinator-added reason since a nurse heal has no other trace. Shared entries probe once per PROBE_EVERY window before vetoing (spec's probe rule), so 'dead on sight' = probe first, veto inside the window. Forbidden files untouched: planner*.py, ship_gate.py, swarm_watch.py, blocked_cap.py, guard thresholds, bandit code — verified in the diff. Controller ROM validation (Route 24 headless segment) still owed by the controller as the directive specifies. [origin] spent: devin 13 min est. n/a
<!-- queue:end -->
