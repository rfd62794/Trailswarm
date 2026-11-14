# PokeAgent: Save library and party gate - fingerprint every state's team, index checkpoints and legs by build, and refuse any state that breaks a party rule

**First of three:** `Curriculum_Build_Selection_Directive.md` and `Build_Comparison_And_Library_Tab_Directive.md` depend on this one. Base: current main.

## Why this exists

Robert, 2026-11-14: "How do we teach it NOT to catch Kakuna ... which also means building a new stable run without a wild-caught kakuna, as training it is impossible, with the current logic?" and, on the save library: there should be alternative saves with alternative team loads, kept as a library of checkpoints and legs that the curriculum can choose between.

Claude measured the save situation read-only on 2026-11-14 (`uv run pokeagent states list` over `runs/checkpoints`, `runs/legs/states`, `runs/segments/inputs`: 472 states):

- Every curriculum checkpoint from `to_pewter` through `nugget_bridge` carries a wild-caught KAKUNA (species id 113, knows only HARDEN), in about 25 distinct party lists and 70+ leg states. Checkpoints `to_route2` (party `165 L8 36 L8 176 L14`, no Kakuna) and older are clean.
- The wild KAKUNA is not removed by `catch_list.NEVER_CATCH` (`src/pokeagent/explorer/catch_list.py`), which only stops NEW throws. Worse, contamination spreads: `runs/checkpoints/to_pewter.state` was re-stamped at 14:06 by run `explore-20261114-140614-10704`, whose drill started from leg state `54_4_13` that already held the Kakuna. A run launched from a tainted state stamps tainted checkpoints.
- A fingerprint (`src/pokeagent/statefp.py` `fingerprint`) stores only `party = [[species, level, hp, max_hp], ...]`: no moves, so a wild Harden-only Kakuna is indistinguishable from a Kakuna that evolved from our own Weedle (which keeps POISON STING).
- The curriculum's selector `ckpt` (`tools/seg_store.py` L211-) asks `statelog.pick` first, then FALLS BACK to `<name>.best.state` / `<name>.state` with only a synthetic-lineage check, so a state refused by the ledger can still be chosen by the fallback.
- Fresh, clean, Kakuna-free alternatives exist in `runs/legs/states` from earlier runs (for example `54_4_13.2.state`: Charmander L9 + Weedle L4 at the Pewter Gym door, run `explore-20261111-214628-9392`), but nothing indexes them by team or ranks them.

This directive builds the machinery. Retiring the tainted real states and re-running the segments is Claude's post-merge step with the ROM (see the Report section).

## Scope (in this order)

1. `src/pokeagent/statefp.py` - extend `fingerprint()` with a `team` list (moves included). `VERSION` stays 1 (see below).
2. `src/pokeagent/team_fp.py` <!-- new: src/pokeagent/team_fp.py --> - pure functions over a fingerprint's `team`: the build key, species line, rounded level, HM capability. Under 120 lines.
3. `src/pokeagent/party_rules.py` <!-- new: src/pokeagent/party_rules.py --> - the rule registry and the first rule. Under 100 lines.
4. `src/pokeagent/statelog.py` - `bad()` and `status()` consult the rules.
5. `src/pokeagent/statelib/__init__.py`, `src/pokeagent/statelib/library.py`, `src/pokeagent/statelib/validate.py` <!-- new: src/pokeagent/statelib/__init__.py --> <!-- new: src/pokeagent/statelib/library.py --> <!-- new: src/pokeagent/statelib/validate.py --> - the library index `runs/states/library.json`, retention, ancestor search, re-validation. Each file under 150 lines.
6. `src/pokeagent/statescmd.py` - `pokeagent states library build|list|validate`; `check` and `promote` consult the rules.
7. Stamp-time enforcement: `src/pokeagent/explorer/press_goals.py` (the checkpoint write, line ~72), `src/pokeagent/legs/states.py` (`save_entry` stamp at ~165, `save_named` stamp at ~195), `tools/seg_store.py` `ckpt` (the fallback path).
8. Tests: `tests/test_team_fp.py`, `tests/test_party_rules.py`, `tests/test_state_library.py`, `tests/test_states_library_cli.py`, `tests/test_state_gate_enforcement.py` <!-- new: tests/test_team_fp.py --> <!-- new: tests/test_party_rules.py --> <!-- new: tests/test_state_library.py --> <!-- new: tests/test_states_library_cli.py --> <!-- new: tests/test_state_gate_enforcement.py -->.
9. `docs/KNOWLEDGE.md` - a short "Save library" paragraph (what is in the index, how the gate works).

## The work

Existing facts, pasted because the worktree cannot be searched. `uv run python --version` prints `Python 3.12.12`.

```
# src/pokeagent/statefp.py
SUFFIX = ".fp.json"; VERSION = 1
def fingerprint(emu, source_run: str | None = None) -> dict      # keys: v, map, x, y, respawn, badges, money, party, heal_items, bag_slots, frames, source_run
def write(state, fp) / read(state) -> dict | None / stamp(emu, state, source_run=None, *, inherit=None) -> dict
def party_hp_fraction(fp) -> float
# fp["party"] today: [[species, level, hp, max_hp], ...]; a real fingerprint:
{"badges": 0, "bag_slots": 1, "frames": 137849, "heal_items": 0, "map": 13, "money": 1265,
 "party": [[112, 4, 18, 18], [176, 9, 26, 26]], "respawn": 2, "source_run": "explore-20261111-214628-9392", "v": 1, "x": 8, "y": 0}
# src/pokeagent/ramstructs.py PartyMon fields: species, hp, box_level, status, type1, type2, catch_rate,
#   moves (4 move ids), ot_id, exp, stat_exp, dv_word, pp, level, max_hp, stats; read_party(emu) -> list[PartyMon]
# src/pokeagent/statelog.py
Entry(path, fp, mtime, stem); status(entry) -> "fresh"|"stale"|"retired"; bad(entry) -> str | None
select(items, want) / pick(directory, want) / retire(path, why, retired_dir=RETIRED_DIR) -> Path; CORRUPT = tuple of exceptions
# src/pokeagent/explorer/catch_list.py
NEVER_CATCH = frozenset({"KAKUNA"})
def wild_never_catch(name, moves) -> bool    # name in NEVER_CATCH and the known moves are a subset of {"HARDEN"}; moves are NAMES
# src/pokeagent/knowledge/kb.py: table(kb, key) -> dict ({} when absent); tables used: "name_of_internal" {"113": "KAKUNA"}, "moves" {"106": {"name": "HARDEN", "power": 0, ...}}
# src/pokeagent/knowledge/readiness.py
def team_readiness(party: list[Combatant], boss: list[tuple[int, str]], label: str, kb=None) -> TeamReadiness | None
def assess(party, boss, label, kb=None, margin=MARGIN, lead_i=None) -> Readiness | None
# src/pokeagent/knowledge/party.py: our_party(emu, kb=None) -> list[Combatant]; trainer_mon(name, level, kb=None)
# src/pokeagent/knowledge/team_value.py: EVOLUTIONS (species name -> evolution info; read it for the species line)
# src/pokeagent/knowledge/hm_compat.py: load() -> {hm: species names that can learn it} or None (no ROM data)
```
Species ids in this save family: WEEDLE 112, KAKUNA 113, CHARMANDER 176, CHARMELEON 178, PIDGEY 36, RATTATA 165. These are for tests only; production code resolves names through `table(kb, "name_of_internal")` and never hard-codes ids. In a worktree without the ROM tables `table(None, ...)` returns `{}`; every new function takes `kb` explicitly and the tests pass a synthetic dict (see `tests/test_switch_matchup.py` `SYN` for the style).

### 1. Team fingerprint (statefp + team_fp)

`statefp.fingerprint` adds `fp["team"] = [{"species": int, "level": int, "moves": [int x4 move ids], "hp": int, "max_hp": int, "ot_id": int, "exp": int}, ...]` in party-slot order, from `read_party(emu)`, inside the existing best-effort try (a failed read yields no `team`, never an exception). Do NOT bump `VERSION` (that would mark all 472 existing states stale); a state without `team` is "team unknown" and is handled everywhere below as unknown, never as clean.

`team_fp.py` pure functions (all take the fingerprint dict and `kb`):
- `species_line(species_id, kb) -> str`: the base species of the evolution line (WEEDLE for WEEDLE/KAKUNA/BEEDRILL), using `team_value.EVOLUTIONS`; unknown species falls back to its own name.
- `build_key(fp, kb) -> str | None`: None when `fp` has no `team`; else a stable string, the members sorted by (line, level) as `LINE:Lrounded` joined with `|`, level rounded DOWN to a multiple of 5 (`LEVEL_ROUND = 5`), moves NOT included (a build is a team shape, not a moveset). Two fingerprints with the same shape share a key.
- `moves_of(member, kb) -> frozenset[str]`: move names via `table(kb, "moves")`.
- `hm_capable(fp, kb, hm_table) -> frozenset[str]`: HMs (cut, flash, surf, strength) some member can learn (`hm_table` = the shape `knowledge.hm_compat.load()` returns) or already knows by move name. `hm_table=None` returns an empty set.
- `provenance(member, kb, starter_species=None) -> str`: `"starter"` when the member's species line equals `starter_species`'s line, `"wild-caught-harden-only"` when `catch_list.wild_never_catch(name, move_names)` is true, else `"unknown"`. Provenance is best effort; never guess beyond these three.

### 2. Party rules (party_rules.py)

```
@dataclass(frozen=True)
class Rule:
    name: str
    check: Callable[[dict, dict | None], list[str]]    # (fp, kb) -> violation texts, [] when the state complies
RULES: tuple[Rule, ...]                                 # registry; adding a rule = appending one Rule
def violations(fp: dict | None, kb: dict | None) -> list[str]
def verdict(fp, kb) -> str    # "clean" | "violation" | "unknown" (no team recorded, or no kb to name the moves)
```
First rule `wild-never-catch`: for each team member, resolve its species name and move names through `kb`; a violation when `catch_list.wild_never_catch(name, move_names)` is true. Message form: `wild KAKUNA L4 (Harden only) in slot 5`. `verdict` is `unknown` when `team` is missing or the `kb` has no `name_of_internal`/`moves` (do not treat unknown as clean in the gate; the CLI reports it and `--strict` fails on it, see below). The rule list is the single place future rules are added.

### 3. Library index (statelib/library.py)

File `runs/states/library.json` (`runs/` is gitignored; create the directory on first write; write atomically with `pokeagent.goexplore.store.atomic_write(path, text)` (temp file then `os.replace`)). Document: `{"v": 1, "built": "<iso utc>", "entries": [Entry, ...]}`. Entry:

```
{"tier": "checkpoint" | "leg",
 "name": "to_pewter" | "beat_brock@3c" | "54_4_13",   # checkpoint: the goal stem (segment_names.state_goal semantics, '.best' variants keep their own entry); leg: map_x_y key
 "segment": "to_pewter",                              # the curriculum segment the state belongs to (see below)
 "state": "runs/checkpoints/to_pewter.state",         # path relative to the repo root
 "build": "CHARMANDER:L10|PIDGEY:L5|RATTATA:L5",      # team_fp.build_key, None when unknown
 "team": [[species, level, [move names]], ...],       # as recorded, names resolved when kb is available
 "verdict": "clean" | "violation" | "unknown", "violations": [...],
 "run": "explore-20261111-214628-9392", "seed": 1047 | null,   # from fp["source_run"]; seed read from runs/<run>/meta.json when that file exists, else null
 "parent": "to_route2.state" | null,                  # fp["parent"] when present, else null
 "created": "<iso utc of the state file's mtime>",
 "metrics": {"steps": int | null, "faints": int | null, "readiness": float | null, "readiness_boss": "brock" | null}}
```
Metrics, each best effort and never fabricated (null when unavailable): `steps` = the state's `fp["frames"]` (emulator frames at the stamp; a null for legacy states); `faints` = sum of faint counts from `runs/<run>/battles.jsonl` records up to that point only when that file is present, else null (do not read other runs' logs; if you cannot compute it cheaply and exactly, leave it null and say so in the Report); `readiness` = `knowledge.readiness.team_readiness(party, boss, label, kb)` against the NEXT boss of the state's segment (use the same boss list the planner uses: read `src/pokeagent/explorer/training.py` `team_for` and `src/pokeagent/explorer/economy/budget.py` `BOSS_GOALS` for how bosses are looked up; if no boss lookup is cleanly callable without an emulator, store null and name the blocker in the Report) as the float `score` of the verdict.

Segments: reuse the curriculum's existing naming, do not rename any segment. `tools/seg_store.py` `layout(doc) -> list[Segment]` yields the leaf segments in chain order, `Segment(key, goal, start, end, stop_goal, stop_map)` (`key` is a goal id or `<goal>@<map hex>` / `<goal>@end` for a split sub-segment; `start` is the checkpoint base name the segment starts from). A checkpoint's `segment` is the `key` of the Segment whose `start` equals the checkpoint's base name (the `.best` suffix stripped); a leg state's `segment` is the Segment whose goal range contains the leg's map (use the checkpoint fingerprints of `start` and `end` in the index to bound it; when that cannot be decided from the sidecars alone, `segment` is null and the state stays in the index). Splits already exist (`doc["splits"]`, `tools/seg_split.py` `cut_maps`): a split boundary is a map transition, a goal boundary is a flag, and the library only records them. `ss.load(root)` loads the doc (`runs/segments.json` via `seg_store`); with no doc, fall back to `GOALS` order (`src/pokeagent/goals.py`).

Retention: `retain(entries, k=3) -> (kept, dropped)`: best-K per `(segment, build)` for legs, ranked by `(verdict == "clean", readiness or -1, -(steps or 10**12), created)`; checkpoints are never dropped by retention (a checkpoint is one per (name, build)). `dropped` is a list for the CLI to print; library build never deletes a file (retiring stays an explicit `states retire`).

### 4. Gate enforcement

- `statelog.bad(entry)`: after the existing checks, return `"party rule: " + "; ".join(violations)` when `party_rules.violations(entry.fp, kb)` is non-empty. `statelog.status(entry)`: `"stale"` for a state with violations, so `select`/`pick` (which keep only fresh states) never choose it. Load the `kb` once per call site, lazily, with the same loader `statescmd._kb_json("rom_tables.json")` uses; with no kb, `verdict` is `unknown` and `status` is unchanged (do not turn unknown into stale; that would stale every state in a worktree without the tables).
- `tools/seg_store.py` `ckpt`: apply the same verdict to the fallback `.best.state` / `.state` path: skip a candidate whose sidecar's verdict is `violation`.
- Stamp time (`press_goals.py`, `legs/states.py`): after `stamp_fingerprint` / `statefp.stamp`, run `party_rules.verdict`; on `violation` write the violations into the sidecar as `fp["rule_violations"]` (so no consumer needs a kb to see it), log `[state gate: <name> breaks <rule>: <text>]`, and in `press_goals.py` do NOT overwrite an existing checkpoint whose sidecar has verdict `clean`: write the new one as `<goal>.quarantine.state` instead, via the same `tmp` + `replace_retry` path. In `legs/states.py` a violating leg state is still saved (it is evidence) but `fp["rule_violations"]` is set and `status` makes it unselectable. Every stamp stays inside its existing try/except: a gate failure must never end a run.
- `states check`: print a row for each violating state (`<name>\tviolation\t<text>`); it fails (exit 1) only for violations in CHECKPOINT dirs (`runs/checkpoints`) or with `--strict` for any state; `unknown` states are listed but never fail without `--strict`.
- `states promote END --from START`: refuse (exit 1, reason printed) when `party_rules.violations` on END's fingerprint is non-empty. Do this in `statescmd.cmd_promote` before calling `lineage.promote`; do not change `lineage.promote`'s signature.

### 5. Re-validation on rule change (statelib/validate.py)

`revalidate(entries, kb, directory_index) -> Report` re-runs `violations` for every entry; an entry whose verdict changed from `clean` to `violation` is marked `retirable: true`, and for each such entry the report names the NEAREST CLEAN ANCESTOR: follow `parent` links through the index; when the chain ends at no clean state, fall back to the latest clean entry of the same tier with a smaller `GOALS` index (the clean checkpoint a regeneration would start from). Output lines: `RETIRABLE <name>: <violation>; nearest clean ancestor: <name> (<state path>)`. This is report-only: nothing is moved, retired or deleted by `revalidate` (that is `states retire`, run by a person).

### 6. CLI (statescmd.py)

Add a sub-subcommand group under the existing `states` parser (`add_parser` builds `s = p.add_subparsers(dest="states_cmd", required=True)`; keep every existing subcommand unchanged):
- `pokeagent states library build [--dir D ...] [--out runs/states/library.json] [--keep-legs 3]` scans the state dirs (default `runs/checkpoints`, `runs/legs/states`; exclude `runs/retired`), fingerprints are read from the sidecars (no emulator), writes the index, prints counts per tier, per verdict, and the legs retention would drop.
- `pokeagent states library list [--tier checkpoint|leg] [--segment S] [--build B] [--clean-only]` prints one row per entry: tier, name, segment, build, verdict, readiness, steps, run.
- `pokeagent states library validate [--strict]` runs `revalidate`, prints the RETIRABLE lines, exits 1 when any checkpoint is retirable (or any state under `--strict`).

## What NOT to do

- Do not retire, move, restamp, delete or regenerate any real state, and do not run any emulator or the swarm. Tests build fingerprints and state files in `tmp_path`; they never read `runs/`, `roms/` or `baselines/`.
- Do not bump `statefp.VERSION`, and do not rename any checkpoint, goal or segment. Do not change `lineage.promote`'s signature.
- Do not change catch behaviour (`catch_list.py`, `catch.py`), battle code, or `tools/swarm.py`.
- Do not add a dependency. Do not read RAM from the library or rule code (they work on sidecar JSON only).
- Do not hard-code species or move ids in production code; resolve names through the kb tables.
- Do not state where any game copy came from; states, ROMs and the library file are local and gitignored.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_team_fp.py tests/test_party_rules.py tests/test_state_library.py tests/test_states_library_cli.py tests/test_state_gate_enforcement.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_statelog.py tests/test_states_legal_cli.py tests/test_catch_list_never.py
```
Expected: no new failures (existing ledger and CLI tests, unchanged). Claude ran this exact command on main while writing the directive; the tail is in the PR description.

```
git diff --stat origin/main -- src/pokeagent tools
```
Expected: the files in Scope only, plus `tools/seg_store.py`.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only (`directive/pokeagent-save-library-and-party-gate-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] `fingerprint()` writes `team` with moves; a fingerprint without `team` yields `build_key` None and verdict `unknown`; `VERSION` is still 1. <!-- test: tests/test_team_fp.py -->
- [ ] `build_key` groups Weedle/Kakuna/Beedrill into one line, rounds levels down to 5, ignores moves, and is order independent. <!-- test: tests/test_team_fp.py -->
- [ ] `violations` flags a KAKUNA whose moves are a subset of HARDEN, does NOT flag a KAKUNA that knows POISON STING, and `verdict` is `unknown` with no team or no kb. <!-- test: tests/test_party_rules.py -->
- [ ] `library build` indexes checkpoints and legs from `tmp_path` state dirs with sidecars, fills every field above (nulls where unavailable), and `retain` keeps best-K legs per (segment, build) and never drops a checkpoint. <!-- test: tests/test_state_library.py -->
- [ ] `status` is `stale` and `bad` names the rule for a violating entry; `select`/`pick` skip it; `ckpt`'s fallback path skips a violating `.state`; an unknown-verdict state is unchanged. <!-- test: tests/test_state_gate_enforcement.py -->
- [ ] The stamp-time hook sets `rule_violations`, and the checkpoint writer does not overwrite a clean checkpoint with a violating one (quarantine name). <!-- test: tests/test_state_gate_enforcement.py -->
- [ ] `states promote` refuses a violating END; `states check` fails on a violating checkpoint and lists unknown ones without failing. <!-- test: tests/test_states_library_cli.py -->
- [ ] `states library validate` prints RETIRABLE lines with the nearest clean ancestor, changes no file, and exits 1 when a checkpoint is retirable. <!-- test: tests/test_states_library_cli.py -->
- [ ] The three existing test files above pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, which metrics came out null and why (faints, readiness), and the final Entry JSON for one synthetic checkpoint and one synthetic leg. Then the steps Claude runs afterwards with the ROM and the real `runs/` (Devin cannot; the worktree has no `runs/`):

1. `uv run pokeagent states restamp` on the state dirs so every sidecar gains `team` (needs the ROM; the swarm is paused first). Back up first.
2. `uv run pokeagent states library build` then `... validate`: expect the Kakuna checkpoints `to_pewter` through `nugget_bridge` flagged RETIRABLE with nearest clean ancestor `to_route2`.
3. Retire the tainted checkpoints and leg states with `pokeagent states retire <path> --why "wild KAKUNA"` (explicit, one by one, after reading the validate list). Clean seeds are already backed up read-only under `runs/clean_seeds_2026-11-14/` (`54_4_13.2`, `13_8_0.2`, `47_4_7.2`, `2_19_35.2`, `to_route2`, each with its `.fp.json`); copy `54_4_13.2.state` to `runs/checkpoints/to_gym.state` with its sidecar and restamp it as the clean seed.
4. Regenerate the chain with `uv run python tools/swarm.py --continuous --plan curriculum --save-leg-states` (`beat_brock`, `to_route3`, `to_route4`, `to_mt_moon` in order) and confirm `states check` exits 0 and `states library list --clean-only` shows the new checkpoints.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The post-merge ROM steps in the Report section, run by Claude with the swarm paused. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-14 14:26 · robert-claude-laptop · none → Queued
<!-- queue:end -->
