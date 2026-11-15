# Trailswarm: memory fault injection - plant known-wrong facts in a scratch copy of maps.json and check that the agent's trust drops and it stops following them

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Depends on:** `Memory_Self_Grading_Directive.md` (Draft) AND `Memory_Audit_And_Fact_Labels_Directive.md` (Review), both merged first. From the self-grading directive: `src/pokeagent/explorer/grades.py` <!-- new: src/pokeagent/explorer/grades.py -->, `src/pokeagent/explorer/grade_store.py` <!-- new: src/pokeagent/explorer/grade_store.py -->, `src/pokeagent/explorer/grade_view.py` <!-- new: src/pokeagent/explorer/grade_view.py -->. From the audit directive: `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> and `src/pokeagent/brain/audit.py` <!-- new: src/pokeagent/brain/audit.py -->. Check with `git ls-files src/pokeagent/explorer/grades.py src/pokeagent/explorer/grade_store.py docs/MEMORY_FACTS.md`. If any of the three prints nothing, STOP and write "dependency not merged" in the Status row; do not recreate them. Self-grading is still a Draft, so the merged file wins over every description of it in this directive; where they differ, follow the merged code and say what differed in the PR description. Base: current main containing both.

**Read first (all in the worktree; if one is missing, stop and say so):** `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> (which fields are world facts), `docs/directives/Memory_Self_Grading_Directive.md` (the sidecar schema, grade thresholds, key kinds), `docs/directives/Memory_Audit_And_Fact_Labels_Directive.md`, `src/pokeagent/explorer/memory.py` (the maps.json shape, `learn`), `src/pokeagent/explorer/memory_warps.py`, `src/pokeagent/explorer/retalk_veto.py`, `src/pokeagent/explorer/interaction_policy.py`, `src/pokeagent/brain/fileops.py`, `src/pokeagent/explorer/edits.py`.

## Standing rule for synthetic data (Robert, 2026-11-07, verbatim)

"We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system."

An injected fact is synthetic memory. It exists to TEST whether the agent's self-grading catches a wrong fact; it is never a real fact, never merged into the live memory, and a passing check on it is a claim to be confirmed on organic runs (a real wrong fact that grades down), not proof by itself.

## 1. Why this exists

Robert, 2026-11-14, approved. The self-grading directive makes every learned entry earn or lose trust, and says "a wrong fact stops steering the agent". Today nothing proves that. The evidence the mechanism is needed is real (from `docs/directives/Memory_Self_Grading_Directive.md`): on 2026-11-11 a starter-ball entry typed `info` with `done` true made every later run press B for thousands of steps with an empty party, and on 2026-11-08 Red with its own memory never finished the potion goal in 600 steps while cold runs finished by step 35. Those were wrong facts found by accident. This directive plants wrong facts ON PURPOSE, in a scratch copy, with a manifest of exactly what was planted, and reports for each one whether the agent stopped trusting it after M runs. That turns "self-grading works" from a hope into a measured, repeatable check, and it gives the regression test the grading code never had.

Facts you need (pasted; the worktree cannot be searched; `uv run python --version` prints `Python 3.12.12`).

The `runs/maps.json` document shape (a runtime output of the agent, gitignored, absent in your worktree; read `src/pokeagent/explorer/memory.py` for the code). Top level: a key `maps` holding one entry per map id (decimal string), plus an optional list `bad_warps` of strings of the form map:x,y,DIR. Each map entry has these keys, all optional except where noted: `visited` (tile "x,y" to visit count; always present), `blocked` (a list of strings of the form x,y,DIR meaning pressing DIR from tile x,y did not move), `warps` (a key x,y,DIR to a destination list of three ints: map, x, y), `warp_taken` and `warp_cand` and `warp_disproof` (counters per warp key), `interactions` (a key x,y,FACING to an entry dict with at least `type` and often `text`, `pages`, `done`, `done_run`, `gave`, `type_votes`), `npcs` (each with a `results` entry of the same shape as an interaction entry), `last_seen`.

`DIRS` in `src/pokeagent/explorer/perceive.py` maps the four button names UP, DOWN, LEFT, RIGHT to a (dx, dy) step. Interaction types are the constants in `src/pokeagent/explorer/interaction_types.py` (INFO, SIGN, GIVER, HEALER, SHOP, VENDOR, PC, TRAINER, BLOCKER, STORY).

How a wrong fact steers the agent today:
- A false dead end: a key in `blocked` makes routing treat that edge as a wall. `MapMemory.learn` removes it when the press from that tile in that direction later MOVES the player ("moved - cleared a false wall"), so a false wall the agent actually tests heals itself; one it never tests persists.
- A wrong warp: `warps[key]` sends routing to a destination that is wrong. `MapMemory.learn` overwrites `warps[key]` with the real destination when the agent takes it; `_note_warp_disproof` and `forget_warp` drop or tombstone a warp whose press moves the player one tile inside the same map.
- A false veto: an interaction entry typed INFO with text makes `interaction_policy.decide` answer False ("memorised - talking again teaches nothing"), so `retalk_veto.veto` presses B instead of talking. Typed on a spot that is really a giver or a healer, it blocks a goal.

The self-grading sidecar (from the dependency; confirm against the merged code): a file `memory_grades.json` in the same directory as the maps.json it grades, with a `schema` of 1 and an `entries` mapping from a key of the form map:kind:key to an evidence record with fields uses, confirms, contradicts, recent (a string of C and X, newest last), last_confirmed_run, last_run, state_run. The kind letter is `i` for an interaction (key x,y,FACING), `n` for an NPC result (key x,y), `w` for a warp (key x,y,BUTTON). `grade_of(evidence)` returns one of unknown, provisional, trusted, doubtful, quarantined. Walls (`blocked`) are NOT graded in v1 of that directive, so a false dead end cannot lower a grade; it is judged by whether the wall is gone.

## 2. Scope (in this order)

1. `src/pokeagent/brain/fault_inject.py` <!-- new: src/pokeagent/brain/fault_inject.py --> - pure: plan the faults, apply them to a data mapping, remove one by tag. No file access. Under 200 lines.
2. `src/pokeagent/brain/fault_scratch.py` <!-- new: src/pokeagent/brain/fault_scratch.py --> - the file side: make the scratch copy under `runs/`, write and read the manifest, and the safety refusals. Under 120 lines.
3. `src/pokeagent/brain/fault_check.py` <!-- new: src/pokeagent/brain/fault_check.py --> - the check: read the scratch memory, the manifest, the grades sidecar and the run summaries, and report one verdict per fault. Under 200 lines.
4. `tools/memory_fault.py` <!-- new: tools/memory_fault.py --> - the command line: inject, remove, list, check. Thin; under 120 lines.
5. `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> is NOT edited here. Add one short section "Fault injection" to `docs/KNOWLEDGE.md` instead (how to run the tool, where the scratch lives, what the verdicts mean).
6. Tests: `tests/test_fault_inject.py`, `tests/test_fault_scratch.py`, `tests/test_fault_check.py`, `tests/test_memory_fault_tool.py` <!-- new: tests/test_fault_inject.py --> <!-- new: tests/test_fault_scratch.py --> <!-- new: tests/test_fault_check.py --> <!-- new: tests/test_memory_fault_tool.py -->. Synthetic documents only: no ROM, no emulator, no real maps.json.

Size rules: every new module under 300 lines, no file over 600.

## 3. The work

### 3.1 `src/pokeagent/brain/fault_inject.py` (pure)

```
KINDS = ("dead_end", "wrong_warp", "false_veto")

@dataclass(frozen=True)
class Fault:
    tag: str          # "fault-<kind>-<index:03d>", unique within one injection
    kind: str         # one of KINDS
    map: str          # the map id key in data["maps"]
    table: str        # "blocked", "warps" or "interactions"
    key: str          # the entry key inside that table (for blocked: the whole string x,y,DIR)
    before: object    # a deep copy of what was there before the fault (None when nothing was)
    after: object     # what the fault put there (for blocked: the same string as key)
    note: str         # one human line: what is wrong about it

def plan(data: dict, counts: dict, seed: int) -> tuple[list[Fault], list[str]]: ...
def apply(data: dict, faults: list[Fault]) -> dict: ...
def remove(data: dict, fault: Fault) -> tuple[dict, str]: ...
def is_present(data: dict, fault: Fault) -> bool: ...
```
`counts` is a mapping of kind name to how many to inject (a kind with 0 or missing injects none). `plan` returns the faults it could build AND a list of skip reasons for any it could not (for example "dead_end: fewer than 1 visited neighbouring tile pair found"); it never raises for lack of material, and it never changes `data` (work on reads only). It is deterministic for the same data, counts and seed (`random.Random(seed)`; iterate maps and keys in sorted order before sampling, because dict order is not a contract).

Fault construction rules, each producing a fact that LOOKS like something the agent could have learned (no marker inside `maps.json`; the tag lives only in the manifest, so the agent cannot tell an injected fact from a learned one):

- `dead_end`: pick a map, a tile in its `visited` whose neighbour in some direction is ALSO in `visited` (so a real walkable edge exists), where the key x,y,DIR is not already in `blocked`, not in `warps`, and not in a `jumps` table. The fault appends that key string to `blocked`. `before` is None, `after` is the key string, `table` is `blocked`.
- `wrong_warp`: pick an existing key in some map's `warps` whose `warp_taken` count is 0 or absent (an untested warp, so the agent has not already corrected it). Set its destination to a DIFFERENT destination copied from another existing warp in the document (so it names a real known map but the wrong place); skip a destination that equals the original, and never use a destination in `WHITEOUT_LANDINGS` (`src/pokeagent/explorer/memory.py`). `before` is the original three-int list, `after` the new one, `table` is `warps`.
- `false_veto`: pick an interaction entry (a `interactions` entry, or an NPC `results` entry; if you use the NPC form, `table` is `npcs` and `key` names the NPC the same way `edits.py` does) whose `type` is GIVER, HEALER, SHOP or VENDOR. Rewrite a COPY of it with `type` set to INFO and `text` set to a fixed short marker string that reads like ordinary dialogue; keep every other field. `before` is a deep copy of the original entry, `after` the rewritten copy. Only fields that `docs/MEMORY_FACTS.md` <!-- new: docs/MEMORY_FACTS.md --> labels world facts may be changed: read that doc first and, if `type` or the table you touch is not labelled a world fact there, STOP and write that in the Status row. NEVER inject or change a playthrough-state flag (`done`, `gave`, `beaten`): the self-grading code strips those across runs by design, so injecting one proves nothing.
- Exact removal: `remove(data, fault)` undoes ONE fault and nothing else. For `blocked` it deletes that one string (the first equal occurrence) from the list; for `warps` it restores `before` ONLY IF the current value equals `after` (otherwise the agent has already changed it: leave it and report "changed by the run"); for `interactions` and `npcs` it restores `before` only if the current entry equals `after`. It returns a new document and a status string: `removed`, `already_gone` or `changed_by_run`. It never touches a fact that is not in the manifest. `apply` then `remove` of every fault in reverse order returns a document equal to the original (assert this on a document with other, non-injected content in the same tables).
- `apply` returns a deep copy of `data` with the faults applied; it never mutates its argument. Applying the same faults twice does not duplicate a `blocked` string.

### 3.2 `src/pokeagent/brain/fault_scratch.py`

- Scratch layout (a runtime output under `runs/`, gitignored, never committed): `runs/fault_scratch/<name>/maps.json` (the faulted copy) and `runs/fault_scratch/<name>/manifest.json`, with `<name>` chosen by the caller. The manifest document has these keys: `schema` (1), `created` (UTC iso), `source` (the path string the copy was made from, repo relative as given), `seed`, `counts`, `skipped` (the skip reasons), `faults` (one entry per fault: tag, kind, map, table, key, before, after, note, and `snapshot`, see below), and `runs_required` (the M the check uses).
- `snapshot` (per fault, for the check): for `dead_end` the visit counts of the source tile and the target tile at injection time (taken from `visited`); for the others the `uses` and `contradicts` the sidecar held at injection (0 when there is none).
- Copy the source maps.json with a plain read and a JSON parse; the source is opened for reading ONLY. Write the scratch files atomically (temp file in the same folder, then `os.replace`; copy the pattern of `src/pokeagent/fsutil.py` `atomic_write_text`). If a scratch `<name>` folder already exists, refuse (exit code 2) unless the caller passes the explicit overwrite option, and even then replace only files this tool wrote (`maps.json`, `manifest.json`, `memory_grades.json`); never delete anything else.
- The safety refusals, each with a test: (1) the scratch folder must resolve to a path INSIDE `runs/fault_scratch/` under the current directory; anything else exits 2. (2) The scratch `maps.json` path must never equal the source path, and the source must never be inside the scratch folder, after resolving both. (3) The tool never opens the live `runs/maps.json` for writing under any name or option; a test creates a fake live file, runs inject on it, and asserts the live file's bytes and modification time are unchanged. (4) It never touches the live `runs/memory_edits.jsonl` or the live `memory_grades.json`; the scratch memory gets no edit journal, so `MapMemory` in a scratch run starts from the scratch `maps.json` alone.
- `list_faults(scratch)` and `load_manifest(scratch)` return plain Python structures. A manifest with a newer `schema` is read as "unsupported" and reported, never overwritten.

### 3.3 `src/pokeagent/brain/fault_check.py`

`check(scratch, run_dirs, runs_required=None) -> dict` reads, all read-only:
- the manifest and the CURRENT scratch `maps.json` (what the agent left after its runs);
- the grades sidecar `memory_grades.json` beside that scratch `maps.json`, when it exists (through the dependency's loader in `src/pokeagent/explorer/grade_store.py`, not a second parser; when the file is missing there are simply no grades);
- the per-run summaries: for each directory in `run_dirs`, the rows of its `grades.jsonl` (the per-run summary row the self-grading directive writes; each row has a `run` id). The number of distinct run ids across all given directories is `runs_seen`.

Per fault, one verdict, evaluated in this order:
1. `corrected`: the fault is no longer present (`is_present` is False: the wall is gone, the warp holds a different value from `after`, the entry no longer equals `after`) OR the warp key is in `bad_warps`. The agent stopped following it by fixing the fact.
2. `distrusted`: still present, and the sidecar grade for its key is `doubtful` or `quarantined` (key: map:w:key for a warp, map:i:key for an interaction, map:n:key for an NPC result; a wall has no grade). Trust dropped and the fact no longer steers (the effective entry is ignored by the grade view).
3. `insufficient_runs`: still present, ungraded or graded unknown, provisional or trusted, and `runs_seen` is below `runs_required`. The check cannot judge yet.
4. `untested`: runs_seen is at least `runs_required`, still present, and nothing shows the agent met it: for a wall, the visit count of the source tile is not above its snapshot; for the others, the evidence `uses` is 0 or the sidecar has no record.
5. `still_followed`: runs_seen is at least `runs_required`, still present, and the agent did meet it (source tile visited more, or `uses` above 0) yet the grade is unknown, provisional or trusted, or a wall stayed. This is the failure the check exists to find.

Return a mapping with keys `scratch`, `runs_seen`, `runs_required`, `grades_present` (bool), `faults` (the list of per-fault results: tag, kind, map, key, verdict, grade or None, uses, contradicts, a one-line `why`), and `counts` (a count per verdict). The check never writes. `tools/memory_fault.py check` prints it as stable JSON by default and a plain table with `--text`, and exits 1 with `--require-clean` when any fault is `still_followed` (default exit 0, so it can be read without gating). A fault the run never met is `untested`, not a pass: say so in the output header ("untested is not a pass").

### 3.4 `tools/memory_fault.py`

```
uv run --frozen python tools/memory_fault.py inject --src runs/maps.json --name NAME --dead-end N --wrong-warp N --false-veto N --seed S [--runs-required M] [--overwrite]
uv run --frozen python tools/memory_fault.py list --name NAME
uv run --frozen python tools/memory_fault.py remove --name NAME --tag TAG [--tag TAG ...]
uv run --frozen python tools/memory_fault.py check --name NAME [--run-dir D ...] [--runs-required M] [--text] [--require-clean]
```
Defaults: `--runs-required` 3, each count 1, `--seed` 0. `inject` prints the manifest summary (tag, kind, map, key, note) and the skip reasons, and says "scratch only; the live maps.json was not opened for writing". `remove` removes only the named tags through `remove` in section 3.1, rewrites the scratch `maps.json` and the manifest (marking each removed fault with its status; a removed fault stays listed in the manifest so the history is kept) and prints the status per tag. Unknown tag: exit 2, nothing changed. Put the work in functions in the library modules; `main(argv=None)` stays thin so tests call it without a subprocess.

### 3.5 Running it against real agents (Claude's, after merge; say so in the Report)

Devin cannot run an agent here (no ROM, no emulator, no `runs/`). The Report states these post-merge steps for Claude: inject into a scratch copy of the live `runs/maps.json` with a fixed seed; point a small number of headless explorer runs at the scratch memory with the existing `--maps-copy` flag of `tools/explore_headless.py` or the `--maps` flag of `tools/explore_demo.py` (confirm the flag and that the run writes its grades sidecar beside THAT maps.json before any run; do not use `tools/swarm.py` against the live `runs/maps.json`); after M runs, `check` and read the verdicts; record the result in `docs/KNOWLEDGE.md` as a claim to confirm on a real wrong fact.

## 4. What NOT to do

- Never write to, rename, delete or hold open for writing the live `runs/maps.json`, its edit journal, its grades sidecar, or any file outside `runs/fault_scratch/<name>/`. The source is read once, as a parsed document.
- Do not add a marker, tag or extra key inside the scratch `maps.json` entries: the point is that the agent cannot tell an injected fact from a learned one. The manifest is the only record.
- Do not inject or alter playthrough-state flags (`done`, `gave`, `beaten`) or anything `docs/MEMORY_FACTS.md` labels as playthrough state or a derived guess.
- Do not change `MapMemory`, `learn`, `retalk_veto`, `interaction_policy`, the grading code from the dependency, `tools/swarm.py`, `tools/swarm_merge.py` or any existing test. Do not make the swarm merge a scratch memory back into the live one.
- No emulator, no ROM, no window, no real RAM read. Tests build small `maps.json` documents in `tmp_path`.
- Do not print dialogue or any `text` or `pages` content in tool output beyond the fixed injected marker string; keys, counts and verdicts only.
- Do not add a dependency. Do not state where any game copy came from.

## 5. Verification (exact commands)

```
uv run --frozen pytest -q tests/test_fault_inject.py tests/test_fault_scratch.py tests/test_fault_check.py tests/test_memory_fault_tool.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_retalk_memory.py tests/test_loop_memory.py tests/test_brain_edits.py tests/test_pokecenter_maps.py
```
Expected: no new failures (existing memory tests, unchanged). Claude ran this exact command on main while writing the directive; the tail was `40 passed, 1 warning`.

```
git diff --stat origin/main -- src/pokeagent tools docs
```
Expected: the files in Scope only.

## 6. Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command. Never bare `python`.
- Branch only (`directive/pokeagent-memory-fault-injection-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.
- Synthetic data may train, test and drill but never decides truth: never scored on (evaluation is always organic held-out data), never a checkpoint start, chain best, KNOWLEDGE fact or shared-memory veto without organic confirmation. Every synthetic record carries a provenance tag (here: the fault tag in the manifest, and `source` naming the copy). Reports show organic versus synthetic side by side. The synthetic share of any training mix is capped by a config constant (not applicable: this tool trains nothing; scratch memory is never merged into shared memory). ROM-derived data stays local and gitignored, never published. Never state where a game copy came from.
- Tests never open a window.

## 7. Completion criteria

- [ ] `plan` is deterministic for the same document, counts and seed, never mutates its input, and returns skip reasons instead of raising when there is no material. <!-- test: tests/test_fault_inject.py -->
- [ ] Each of the three kinds builds a plausible fact: a false wall only on a real visited edge, a wrong warp only on an untested warp and to a real other destination, a false veto only on a giver, healer, shop or vendor entry and never on a playthrough-state flag. <!-- test: tests/test_fault_inject.py -->
- [ ] `apply` never mutates its argument; `remove` undoes exactly one tag, reports `already_gone` or `changed_by_run` instead of clobbering, and apply then remove-all returns a document equal to the original (other content in the same tables untouched). <!-- test: tests/test_fault_inject.py -->
- [ ] The scratch copy lands only under the scratch folder, refuses an existing name without the overwrite option, refuses any path that resolves outside it or onto the source, and leaves a fake live maps.json byte-identical with an unchanged modification time. <!-- test: tests/test_fault_scratch.py -->
- [ ] The manifest records tag, kind, map, table, key, before, after, note and the snapshot for every fault, plus the skip reasons, and a newer schema is read as unsupported without being overwritten. <!-- test: tests/test_fault_scratch.py -->
- [ ] `check` returns the five verdicts in the specified order on synthetic scratch memories and sidecars (corrected by a cleared wall and by a changed warp, distrusted by a doubtful or quarantined grade, insufficient_runs below M runs, untested when never met, still_followed when met and trusted), counts distinct run ids across run directories, and never writes. <!-- test: tests/test_fault_check.py -->
- [ ] `inject`, `list`, `remove` and `check` work through `main(argv)`; `remove` of an unknown tag exits 2 and changes nothing; `--require-clean` exits 1 only when a fault is still_followed. <!-- test: tests/test_memory_fault_tool.py -->
- [ ] The four existing memory test files in section 5 pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## 8. Report

Diff stat, test tails, the dependency files it read and any place the merged self-grading code differed from this directive's description, the manifest of one synthetic injection (tag, kind, map, key, note) and the `check` output for it, and the three post-merge steps of section 3.5 for Claude.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture. Never commit a real `maps.json` or any dialogue text from one.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The post-merge agent runs in section 3.5, done by Claude. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
