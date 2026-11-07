# PokeAgent: review and replay tools - `pokeagent review run | swarm | replay | diff` for the operator and overseer (JSON + text, no UI)

**Read first (all in the worktree; if one is missing, stop and write that in the Status row):** `src/pokeagent/cli.py` (how subcommands attach: `cli_hex.register(sub)` / `cli_brain.register(sub)` near line 215) and `src/pokeagent/cli_brain.py` (the model to copy: JSON by default with sorted keys, `--text` for humans, one `register(sub)`, logic in a package, the file is argparse + emit),
`tools/review_runs.py` (scores runs, fastest segment per goal -> `runs/best_paths.json`), `tools/segments.py`, `tools/seg_store.py`, `tools/seg_ingest.py` (`build_attempt`: how a run is judged solved; the segment tag/stop-goal rules), `src/pokeagent/stalls.py` (`build_dossier`, `likely_cause`, `load_dossiers`, `cluster`),
`src/pokeagent/invariants/` (`runner.run_all`, `findings.Finding`, `has_errors`), `src/pokeagent/evaluation_ab.py` and `tools/ab.py` (how `decisions.jsonl` / `goal_frames.jsonl` are read for comparisons), `tools/explore_headless.py` (the seeded headless run; its `argparse` flags), `src/pokeagent/statefp.py` (state fingerprints),
`src/pokeagent/explorer/behaviours/already_out.py` (the "already out" screen), `src/pokeagent/explorer/behaviours/battle.py` lines ~236-285 and ~50-60 (the `runs/battles.jsonl` record and the `outcome` values), `src/pokeagent/explorer/press.py` (`write_transition`), `tests/test_cli.py` and `tests/test_stalls.py` (test patterns). **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-07): "Is there a way to build a better review and replay system to allow assessment of progress, stalls, and breaks?" and then "That's more of a request of better tools for you." These are therefore OPERATOR/OVERSEER command-line tools (Claude and the overnight overseers read them), not a viewer.

Today an overseer answers "what happened in this run / this swarm" by hand: `tail` on `decisions.jsonl`, `grep` on `battles.jsonl`, `tools/segments.py` for the table, `tools/stalls.py` for dossiers, `tools/invariants.py` for breaks, and a manual comparison against the swarm log. Each is a separate, text-only, differently shaped output. There is no one-run event timeline, no cross-run roll-up with a "breaks" section,
no check that a run is reproducible, and no way to diff two runs. The same four questions repeat every beat: how far did it get, where did it stall, what broke, is it reproducible.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `runs/` or `kb/` in the worktree)

- `uv run python --version` prints `Python 3.12.12`. Always `uv run`; never bare `python`. Full suite: `uv run pytest -q` (about 100-210 s; 1557 passed, 1 skipped on the live checkout today, plus one environment-dependent failure `tests/test_resources.py::test_lock_takeover_is_exclusive`, unrelated: ignore it and say so if it fails for you).
- `runs/`, `roms/`, `baselines/`, `kb/rom_tables.json` are gitignored: **no run data, ROM or `kb/` in your worktree.** Every test uses SYNTHETIC fixture run directories that you commit under `tests/fixtures/review/` (tiny: tens of rows, hand-written, clearly marked synthetic in a README line inside the fixture folder name or a `meta.json` field `"synthetic": true`). Never copy a real run into the repo.
- **A run directory today** (`runs/explore-YYYYMMDD-HHMMSS-<pid>/`, local time in the name) holds exactly these files on the live checkout: `meta.json`, `decisions.jsonl`, `levels.jsonl`, `transitions.jsonl`. `goal_frames.jsonl` exists only on some runs (swarm segment runs write it; `seg_ingest` and `evaluation_ab` read it) - treat it as optional. There is NO end-of-run marker file today. Shapes (real examples):
  - `meta.json`: `{"start": "nugget_bridge", "stop_at_goal": "gyarados", "stop_at_map": null, "tag": "seg:gyarados:1794079641-402", "steps": 3000, "explore_rate": 0.0, "box_pace": 8, "starter": "bulbasaur", "seed": 80043, "frame_share": true, "train_level": 8, "window": false, "git_sha": "d99055f2...", "initial_goals": [..23 goal ids..]}`.
    There is NO `state` key: the start state of a segment run is `runs/checkpoints/<start>.state`, which is overwritten over time, so the faithful copy is the one `seg_ingest` keeps under `runs/segments/inputs/<tag>/` (with its sha256 and a map-memory snapshot) while a candidate is pending; it may be gone. the replay tool must say "start state not recoverable" instead of guessing.
  - `decisions.jsonl` (one line per press; extra lines with an `"event"` key are bandit/anomaly extras and MUST be skipped for press counts): `{"step": 1, "behaviour": "frontier", "rule": "frontier", "button": "UP", "map": 35, "x": 10, "y": 35, "goal_stage": "gyarados", "box": false, "battle": false, "outcome": "moved", "reversal": false}`.
  - `transitions.jsonl` (one line per press): `{"step": 1, "from": [35, 10, 35], "button": "UP", "to": [35, 10, 34], "moved": true, "textbox": "none", "text": "", "facing": "UP", "source": "agent", "ahead_tiles": [..], "stand_tile": 60}`. `text` is the screen text when a box is up; `source` is `agent`, `human` or `claude`. There is NO `rule` key here: the rule lives in `decisions.jsonl`; join the two on `step`.
  - `levels.jsonl`: `{"step": 0, "frame": 4, "map": 35, "cause": "start", "party": [[133, 9, 938, 23, 23], [179, 26, 13936, 63, 72]]}` - party rows are `[species id, level, exp, hp, max_hp]`; `cause` is `start` or `battle_end` (others may appear).
  - `goal_frames.jsonl` when present: one line per goal reached, `{"goal": ..., "step": ..., "frame": ...}`.
- Shared files: `runs/milestones.json` = `{goal id: [{"run": "explore-...", "step": N}, ...]}` (goal firsts for older runs); `runs/battles.jsonl` (one object per battle; keys include `start` (step), `kind` (1 wild, 2 trainer), `run`, `won`, `outcome` (`win`, `trainer_win`, `blackout`, ... from `battle.py`), `battle_map`, `end_map`, `stage`, `trainer`, `enemy_species`, `turns`, `party_before` / `party_after` as `[species, level, exp, hp, max_hp]` rows);
  `runs/stalls/<run>.json` = one dossier per stalled run with keys `run, t, slot, reason, presses, map, x, y, segment, seed, starter, goal_stage, signature, signature_key, dominant, histogram, text_on_screen, sprites_near, start_state, likely_cause, decisions_tail` (so `likely_cause` is already in the file; `stalls.likely_cause(sig, outcomes, text, textbox, reversal_share, tiles)` computes it);
  `runs/segments.json` (curriculum stats, read through `seg_store`), `runs/checkpoints/*.state` (+ `.fp.json` fingerprints from `statefp`), `runs/anomalies.jsonl`, `runs/after_victory.jsonl` (planned by `Goal_Procedures_Directive.md`: read it if it exists, ignore it if not), `runs/bandit.json`, `runs/economy.json`.
- The invariant checker: `pokeagent.invariants.runner.run_all(runs_dir, load_states=False, rom=None) -> list[Finding]`, `Finding(check, level in ERROR|WARN|INFO, kind, message, data)`, `has_errors(findings)`. A **legality checker** (`legality.check`) is being built in `Legal_State_Verify_Directive.md` (in review on the queue); if `pokeagent.legality` is importable use its `check`, otherwise leave the seam described in 4.2 and say so in the report.
- Seeded headless run: `tools/explore_headless.py` flags include `--rom --state --steps --seed --starter --stop-at-goal --maps-copy --adaptive --fast-text --bandit --par-follow --novelty --verbose`; it prints one JSON object. Whether it keeps its run directory is NOT verified in this repo - hence the injected runner in 4.4.
- `cli.py` registers subcommand trees with `register(sub)` (see `cli_brain`); tests call the handler functions directly (see `tests/test_cli.py`). Devin does not run the `pokeagent` entry point (the sandbox refuses it): your tests call `cli_review.main(argv)` / the handlers.
- **Files you must NOT modify:** `src/pokeagent/explorer/**` behaviours and engine (this directive changes no behaviour), `ship_gate.py`, `planner*.py`, `tools/seg_*.py`, `tools/segments.py`, `tools/review_runs.py` (read them; import pure helpers only).

## 3. Scope (one PR, SOLID, each tool small; every module under 300 lines)

1. `src/pokeagent/review/` package: loading, event extraction, loop detection, rule summary, rendering (shared by all four tools).
2. `pokeagent review run <run-dir>`: a compressed event timeline for ONE run.
3. `pokeagent review swarm --since <time>`: the cross-run roll-up with a "breaks" section.
4. `pokeagent review replay <run-dir> --steps N`: determinism check (diff logic + tests; the emulator call is thin and injected).
5. `pokeagent review diff <runA> <runB>`: timeline diff.
6. `src/pokeagent/cli_review.py` (argparse + emit only) registered from `cli.py` with one import line and one `cli_review.register(sub)` line; tests; fixtures.

Output conventions for ALL four: text by default; `--json` for machine use (stable key order, `sort_keys=True`, indent 1, same shape as the text's data); exit 0 = nothing broken, exit 1 = breaks found (defined per tool below), exit 2 = usage/missing input (a clear one-line message, JSON `{"error": ...}` under `--json`). Never raise a traceback for a missing or malformed file: skip the row, count it in a `skipped_rows` field, continue.

## 4. The work

Every threshold is a NAMED constant with a comment that it is an untuned first value. No tool deletes, moves or edits anything under `runs/` (read-only; `replay` writes only to a temp dir it is given).

### 4.1 `review/` package and `pokeagent review run <run-dir>`

```
review/load.py       # RunData: meta, decisions (press rows only), transitions, levels, goal_frames, battles (filtered to this run), dossier, after_victory rows; tolerant readers; run start time from the dir name
review/events.py     # build_events(RunData) -> list[Event]   (Event = {step, frame|None, kind, ...fields})
review/loops.py      # find_loops(transitions, decisions) -> list[Episode]
review/rules.py      # top_rules(decisions, n=10) -> [{rule, behaviour, presses, share}]
review/render.py     # text renderers (one function per tool) + json helpers
review/timeline.py   # summarise(RunData) -> the dict the run tool prints
```

`pokeagent review run <run-dir> [--json] [--runs-dir runs] [--max-events 200]`. `<run-dir>` is a path or a bare run name resolved under `--runs-dir`. Output sections (text and the same keys in JSON):
1. **header**: run name, segment (tag/`stop_at_goal`), start, starter, seed, git_sha, steps used / budget, presses by source (`agent`/`human`/`claude`), frames if known.
2. **events** (a compressed timeline, ordered by step, each with `kind`):
   - `goal`: goal firsts from `goal_frames.jsonl`; else from `runs/milestones.json` entries whose `run` equals this run (frames unknown -> `None`, never invented).
   - `map`: a row where `to[0] != from[0]` (warp/map change), collapsing immediate A->B->A bounces into one `map_bounce` event with a count.
   - `battle`: from `battles.jsonl` records with this run's name: `kind`, `outcome`, enemy species, `hp_delta` = sum of member HP in `party_before` minus in `party_after` (positive = lost), `turns`. Wild fights are summarised in one `wild_battles` line (count, wins) unless `--max-events` leaves room.
   - `blackout`: a battle with `outcome == "blackout"`, plus the respawn map (`end_map`).
   - `heal` and `buy`: decision runs whose `behaviour` or `rule` matches the named tuples `HEAL_RULES = ("heal", "potion", "nurse", "cave_topup")` and `BUY_RULES = ("restock", "buy", "shop")` (substring match, first press of each contiguous block = one event with its press count). Rule names that match neither tuple are listed under `unclassified_rules` (top 5 by presses) so the lists can be improved from the output, not guessed.
   - `stall`: if `runs/stalls/<run>.json` exists, one event with `reason`, `signature_key`, `likely_cause`, `presses`, position. If not, a press-window stall is NOT invented here.
   - `loop`: episodes from `find_loops` (below).
   - `level`: each row of `levels.jsonl` after the first where any member's level or exp rose, as `{species, level_from, level_to, exp_gain}` (levels from the `[species, level, exp, hp, max_hp]` rows; species ids are printed as ids unless a `names` table is supplied by the caller - do NOT read `kb/` here).
   - `after_victory`: rows of `runs/after_victory.jsonl` for this run when that file exists.
3. **loops / "already out" episodes** (`find_loops`): an episode is a maximal run of at least `LOOP_MIN_ROWS = 6` consecutive press rows that share the same `(button, normalised screen text)` key, where the normalised text is `" ".join(text.lower().split())` truncated to `LOOP_TEXT_LEN = 60`, OR the same `(map, x, y, button)` with `moved == false`. An episode whose text contains `"already out"` is tagged `kind: "already_out"`; one with the same position/button unmoved is `kind: "blocked_loop"`; others `kind: "text_loop"`. Report start step, length, the repeating key, and the dominant `rule` of those steps (joined from `decisions.jsonl`).
4. **decisions by rule**: the top 10 rules by press count with behaviour, presses, share of all presses.
5. **levels/exp**: first vs last party rows and the total exp gained per member.
6. **end reason** (inferred; there is NO end marker today, and the output says "inferred"): `solved` (the `stop_at_goal` goal appears in goal firsts), `stalled` (a dossier exists), `step_budget` (presses >= `meta.steps`), `crashed` (a file `<run>/error.txt` or `<run>/crash.json` exists - a SEAM: nothing writes them today; the check just looks), else `ended_early` with the last step and position. Several can be true; report the first match in that order plus `also: [...]`.
Exit code: 1 when the run shows a break: `crashed`, an `already_out` or `blocked_loop` episode of at least `BREAK_LOOP_ROWS = 30` rows, or a blackout; else 0. A stall alone is reported but is exit 0 (a stall is a result, not a break).

### 4.2 `pokeagent review swarm --since <time>`

`pokeagent review swarm --since <time> [--until <time>] [--runs-dir runs] [--json] [--segment NAME] [--top 5] [--invariants]`. `<time>` accepts `HH:MM` (today, local time), `YYYY-MM-DDTHH:MM[:SS]` or `Nm`/`Nh` (N minutes/hours ago); a run is in range by the timestamp in its directory name (`explore-YYYYMMDD-HHMMSS-pid`, local time), falling back to the file mtime of `meta.json`. Sections:
1. **runs**: count, how many are segment runs (`meta.stop_at_goal` or `stop_at_map`), how many were watched/human-driven (`window` true or non-`agent` sources).
2. **per segment** (grouped by `meta.stop_at_goal` or `meta.stop_at_map`): attempts, solves (judged exactly as `seg_ingest.build_attempt` does: `goal_frames.jsonl` first, else `milestones.json`), solve rate, frames to solve (best, median; `None` when no frames are recorded), presses, stall rate (runs with a dossier / attempts), blackout rate (blackouts per attempt, from `battles.jsonl` outcome field equal to blackout), loop-episode count (from `find_loops`), the failing run names.
3. **top stall causes** (`likely_cause` from the dossiers in range, counted, with the `signature_key` of the biggest cluster and one example run each; reuse `stalls.load_dossiers` / `stalls.cluster` rather than re-implementing), **top rules** across the swarm (presses), **new checkpoints** (files in `runs/checkpoints/*.state` with mtime in range, with the `.fp.json` fingerprint summary: map, badges, party levels, money, when present).
4. **breaks** - the section the exit code depends on: (a) invariant violations: `invariants.runner.run_all(Path(runs_dir))` ERROR-level findings (WARN counted, listed with `--invariants`; skip silently if `run_all` raises and report `invariants: "unavailable: <message>"`); (b) legality violations: if `pokeagent.legality` imports and exposes `check`, call it per its signature on the checkpoints in range and report its findings; otherwise emit `"legality": "unavailable (no pokeagent.legality on this branch)"` - a SEAM, not an error; (c) runs that ended by crash/exception: `crashed` per 4.1 plus any run whose `decisions.jsonl` is missing or empty while `meta.json` exists (`no_decisions`), listed with names; (d) the `already_out` / `blocked_loop` episodes at or over `BREAK_LOOP_ROWS`.
Exit 1 when (a) has an ERROR, (b) has a violation, or (c)/(d) is non-empty; else 0.
Performance: it reads each run's files once, streams `.jsonl` (no whole-file load of `battles.jsonl` more than once per invocation), and finishes in a few seconds for ~100 runs.

### 4.3 `pokeagent review diff <runA> <runB>`

`pokeagent review diff <runA> <runB> [--json] [--runs-dir runs]`. Both summarised with the 4.1 machinery, then compared:
- **first divergence** in the press stream (aligned on `step`): the first step where `(button, map, x, y)` differs (from `transitions.jsonl`, with the `rule`/`behaviour` of each side from `decisions.jsonl`); `None` when one stream is a prefix of the other (report the shorter length) or they are identical.
- **per-goal timing**: for each goal reached by either run, step and frame deltas (`B - A`, `None` where a side lacks the data) and which reached it first; **per-segment frame delta** when both are segment runs of the same segment.
- **event diff**: counts by `kind` side by side (battles, blackouts, heals, buys, stalls, loop episodes), the rules whose press share differs by at least `RULE_SHARE_DELTA = 0.05`, level/exp gain difference, and the end reasons.
- **comparability warnings**: different `seed`, `starter`, `start`, `git_sha`, `steps` are listed first ("not an apples-to-apples diff: seed differs") but the diff still runs.
Exit 0 always for identical-or-different runs when both load (a diff is information); exit 2 when a run cannot be loaded.

### 4.4 `pokeagent review replay <run-dir> --steps N`

Determinism check: re-run the same start state + seed + git_sha headlessly for N steps and compare the decision stream with the original's first N.
```python
def replay_command(meta: dict, start_state: Path, steps: int, out_dir: Path, python: str = "uv run python") -> list[str]   # pure: the explore_headless argv from meta (seed, starter, stop_at_goal, ...)
def locate_start_state(meta: dict, runs_dir: Path) -> Path | None   # runs/segments/inputs/<tag>/... if it exists, else None (no guessing, never the current checkpoint)
def compare_streams(a: list[dict], b: list[dict], n: int) -> Divergence | None   # pure; the heart of this tool
@dataclass(frozen=True) class Divergence: step: int; field: str; a: dict; b: dict; rule_a: str; rule_b: str; agreed_steps: int
def run_replay(run_dir, steps, runs_dir, runner=None, head_sha=None) -> ReplayReport   # `runner(argv, out_dir) -> list[dict]` is INJECTED
```
- `compare_streams` compares the press rows in order on `(button, map, x, y, outcome)` (the `decisions.jsonl` fields; tolerate extra keys), returns the FIRST divergence with the step, which field differed, both rows and both rules, and how many steps agreed; `None` when the first `n` rows (or all rows if fewer) are identical; a length mismatch before `n` is itself a divergence (`field: "length"`).
- `run_replay`: loads the original's first `steps` rows, resolves the start state (`locate_start_state`; if None -> report `status: "start_state_unrecoverable"` with the reason and exit 2, never a guess), compares `meta.git_sha` with `head_sha` (`git rev-parse HEAD` is called ONLY by the default wrapper, not by the pure functions; a mismatch is a WARNING in the report: "code differs: divergence is expected"), builds the command, calls `runner`, compares. Statuses: `identical`, `diverged` (with the Divergence), `start_state_unrecoverable`, `runner_unavailable`. Exit 0 identical, 1 diverged, 2 unavailable.
- The default `runner` is a thin subprocess call of `tools/explore_headless.py` (built by `replay_command`) that parses the decisions from the temp out dir; **Devin does NOT run it** (no emulator): the tests inject a fake runner that returns canned streams. Because it is NOT verified whether `explore_headless` keeps its run directory, the default runner must write to a temp dir passed in (`--maps-copy` from the original's snapshot if available) and, if it cannot find a `decisions.jsonl` afterwards, return `runner_unavailable` with the command it ran printed (the controller wires the last inch).

### 4.5 CLI, fixtures and tests

- `src/pokeagent/cli_review.py`: `register(sub)` adds `review` with subcommands `run`, `swarm`, `replay`, `diff`; `main(argv) -> int` for tests; handlers return the exit code and print via `render`. `cli.py` gets exactly one import and one `register` call (no other change).
- Fixtures under `tests/fixtures/review/` (synthetic, tiny): `run_ok` (a solved segment run: goal_frames, a warp, a trainer win, a heal block, levels rows), `run_stall` (with a dossier, a blocked loop of 40 rows), `run_alreadyout` (an "already out" text loop of 12 rows), `run_blackout` (a battle with `outcome: "blackout"`), `run_crash` (`error.txt`, no decisions), `run_ok_b` (same as `run_ok` but diverges at press 7), a `runs/`-shaped root with `milestones.json`, `battles.jsonl`, `stalls/`, `checkpoints/` (empty `.state` files + `.fp.json`), and run directory names with distinct timestamps for `--since`. Tests build a temp copy with `tmp_path` where they must modify files.
- `tests/test_review_run.py`: the event kinds and their fields on `run_ok` (goal firsts from `goal_frames.jsonl`, from `milestones.json` when it is absent, map change + bounce collapse, battle `hp_delta`, heal/buy blocks, stall event with `likely_cause`, level gains), loop episodes (`blocked_loop` 40 rows, `already_out` 12 rows, a 5-row repeat is NOT an episode), top-10 rules ordering, end reasons (`solved`, `stalled`, `step_budget`, `crashed`, `ended_early`), exit codes (blackout/crash/loop >= 30 -> 1; clean and stall-only -> 0), `--json` equals the data the text prints, a corrupt line is skipped and counted.
- `tests/test_review_swarm.py`: `--since` parsing (`HH:MM`, ISO, `30m`), range filtering by directory-name timestamp, per-segment solve rate / stall rate / blackout rate / loop count on a fixture with 4 runs of two segments, top stall causes, new checkpoints by mtime (set with `os.utime`), the breaks section with a monkeypatched `run_all` returning an ERROR finding (exit 1) and a clean one (exit 0), `legality` unavailable seam (monkeypatch the import away), crash and `no_decisions` detection, `--segment` filter.
- `tests/test_review_replay.py`: `compare_streams` on fixture streams: identical -> None; first divergence reports the right step, field, rules and `agreed_steps`; length mismatch; extra keys tolerated; `replay_command` produces the expected argv from a fixture `meta` (seed, starter, stop_at_goal, steps); `locate_start_state` returns None when no inputs copy exists; `run_replay` with an injected runner covers `identical`, `diverged`, `start_state_unrecoverable`, `runner_unavailable` and the git_sha-mismatch warning.
- `tests/test_review_diff.py`: first divergence between `run_ok` and `run_ok_b`, per-goal deltas, event-count diff, rule-share deltas over `RULE_SHARE_DELTA`, comparability warnings for seed/starter mismatch, a missing run -> exit 2.
- `tests/test_cli_review.py`: `cli_review.main([...])` for each subcommand prints valid JSON with `--json`, text otherwise, and returns the documented exit code; `cli.py` registers `review` (the existing `tests/test_cli.py` stays green unedited).

## 5. What NOT to do

- No viewer/GUI. No changes to behaviours, the engine, planners, `ship_gate.py`, or any file that writes run data (the readers must tolerate today's files as they are). No emulator runs by you; no `uv run pokeagent ...`; do not run `tools/explore_headless.py`.
- No deletion, move or rewrite of anything under `runs/` (read-only); `replay` writes only inside the temp directory it is handed. No new dependencies. Do not copy real run data into `tests/fixtures/`.
- Do not duplicate logic that already exists: use `stalls.load_dossiers` / `cluster` / `likely_cause`, `invariants.runner.run_all`, and the `seg_ingest` solve rule (import the pure function if it is importable without side effects, else re-state its rule in one place with a comment naming it). Do not invent end markers: the "crash" check only looks for the seam files named above.
- Do not change `tools/review_runs.py`, `tools/segments.py`, `tools/seg_*.py`.

## 6. Verification

- `uv run pytest -q tests/test_review_run.py tests/test_review_swarm.py tests/test_review_replay.py tests/test_review_diff.py tests/test_cli_review.py tests/test_cli.py` - new tests pass, the existing CLI test unedited (paste the tail).
- `uv run pytest -q` green; paste the before/after tails and `git diff --stat main`; confirm no forbidden file changed and that `cli.py` changed by the import and the one `register` call only.
- **Controller validation (not Devin; the real `runs/` is on the laptop):** run the run tool on today's gyarados stall runs (for example `explore-20261107-153827-24324`, which has a dossier: `no new goal and only 3 new tiles in the last 600 presses`, map 35, signature `35|frontier|frontier|UP|blocked|True`) and the swarm tool with --since 14:50, and check the numbers against the swarm log; run the replay tool on one segment run with a pending input copy and wire the real runner's last inch; run the diff tool on two same-seed runs.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-review-replay-tools-directive`. Never commit to `main`; never push; never deploy; no `git stash`. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `review/` package (load, events, loops, rules, render, timeline) and `pokeagent review run` with text + `--json` and the documented exit codes
- [ ] `pokeagent review swarm --since` with per-segment table, stall causes, rules, new checkpoints and the breaks section (invariants now, legality as a seam or live, crashes, loop episodes)
- [ ] `pokeagent review replay` with `compare_streams`, `replay_command`, `locate_start_state`, `run_replay` (injected runner); the emulator call is thin and untouched by tests
- [ ] `pokeagent review diff`; fixtures under `tests/fixtures/review/` are synthetic and tiny
- [ ] The new test files pass; `tests/test_cli.py` unedited and green; `uv run pytest -q` green (tail pasted); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures, the exact value of every named constant, which run-dir files your readers actually needed vs what the fixtures cover, whether `pokeagent.legality` was importable (seam used or live), every place the live file shapes differ from this directive's section 2, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-review-replay-tools-directive |
| Base branch | - |
| Base commit | 0d1aade9a7d6ae069930c3ca84ab89da88a73bc4 |
| Head commit | fde87383638dc7408981b53b224c8bbfe101d0f0 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 15:41 · robert-claude-laptop · none → Draft — Claude 2026-11-07: review run/swarm/replay/diff operator CLI tools
- 2026-11-07 15:42 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override: dispatch-path-missing on greenfield modules/tests/fixtures and gitignored runs/kb paths
- 2026-11-07 15:43 · robert-claude-laptop · Queued → Draft — Claude: lint rewording (command-looking mentions, secret false positive)
- 2026-11-07 15:43 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override: dispatch-path-missing on greenfield modules/tests/fixtures and gitignored runs/kb paths
- 2026-11-07 15:56 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing / verification-path-missing on greenfield modules, tests and fixtures under tests/fixtures/review/ and gitignored runs/ and kb/ evidence paths; known false positives.
- 2026-11-07 15:57 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-review-replay-tools-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VWTFEZXNH4N3917D3J69VD
- 2026-11-07 16:03 · dispatcher · launched pid=2800; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-review-replay-tools-directive; provisioned: uv sync --frozen
- 2026-11-07 16:20 · devin-overseer (delegated) · In progress → Review — Done + verified (run resumed after a process die; recovered and finished). TESTS: targeted `uv run pytest -q tests/test_review_run.py tests/test_review_swarm.py tests/test_review_replay.py tests/test_review_diff.py tests/test_cli_review.py tests/test_cli.py` = 59 passed (test_cli.py unedited, green). Full suite `uv run pytest -q` = 1577 passed, 40 skipped in 144.82s (directive's live-checkout count was 1557/1; +59 new; the noted env-dependent test_resources failure did not fire this run). DIFF: vs base 0d1aade +1859/-3 over 19 files; cli.py changed ONLY by one import (cli_review added to existing import line) + one `cli_review.register(sub)`. `git diff --stat main` additionally shows main-side drift (-834 lines on files untouched here; main is ahead of base, merge-base f068332). CONSTANTS (each commented 'untuned first value'): loops.py LOOP_MIN_ROWS=6, LOOP_TEXT_LEN=60, BREAK_LOOP_ROWS=30; timeline.py MAX_EVENTS=200, TOP_UNCLASSIFIED=5; diff.py RULE_SHARE_DELTA=0.05, COMPARE_META_KEYS=(seed,starter,start,git_sha,steps); replay.py COMPARE_FIELDS=(button,map,x,y,outcome); events.py HEAL_RULES=(heal,potion,nurse,cave_topup), BUY_RULES=(restock,buy,shop); swarm.py EST_FRAMES_PER_STEP=10.5 (restated seg_store.FRAMES_PER_STEP for the fallback only). SIGNATURES: timeline.summarise(RunData,max_events=200)->dict; swarm.parse_since(s,now=None), swarm.summarise(runs_dir,since,until=None,segment=None,top=5,invariants_verbose=False)->dict; diff.first_divergence(a,b), diff.diff(a,b)->dict; replay.compare_streams(a,b,n)->Divergence|None, replay_command(meta,start_state,steps,out_dir,python='uv run python')->list[str], locate_start_state(meta,runs_dir)->Path|None, run_replay(run_dir,steps,runs_dir,runner=None,head_sha=None)->ReplayReport. READERS needed: meta.json, decisions.jsonl (press rows only; 'event' rows skipped), transitions.jsonl, levels.jsonl, goal_frames.jsonl (optional), runs/{milestones.json,battles.jsonl,after_victory.jsonl}, stalls/<run>.json, checkpoints/*.state+.fp.json, segments/inputs/<tag>/{job.json,*.state}; error.txt/crash.json existence only. Fixtures cover all except crash.json, stop_at_map and window:true metas. LEGALITY: pokeagent.legality not importable on this branch -> seam emits 'unavailable (no pokeagent.legality on this branch)'; the live path (check per checkpoint via an emulator) is exercised by test with a fake module. DEVIATIONS/DID-NOT-FIT: seg_ingest loaded lazily via spec_from_file_location (tools/ on sys.path during exec only) with a documented local restatement fallback; invariants run_all invoked inside swarm._invariants so tests monkeypatch it; loop timeline events carry kind 'loop' plus loop_kind subfield; no_decisions covers missing OR empty decisions.jsonl; swarm dossier loading falls back to a direct stalls/ glob when --runs-dir is not literally named 'runs'.; under delegate.envelope [origin] spent: devin 10 min est. n/a
- 2026-11-07 16:30 · robert-claude-laptop · Review → Done — note: PR #153 merged 0889c37 (merge commit); Sonnet review APPROVE on real run data; verify at fde8738 1577 passed 40 skipped; loop-noise collapse follow-up queued separately
<!-- queue:end -->
