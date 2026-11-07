# PokeAgent: state ledger, part 2 - `statelog.select` and the `pokeagent states` CLI

**Read first:** `docs/superpowers/specs/2026-11-07-save-state-ledger.md` (merged in PR #131; section "Proposed: the ledger").
Then `src/pokeagent/statefp.py`, `src/pokeagent/checkpoint_goals.py` (`read_respawn`, `respawn_behind`, `SHIP_GOALS`,
`BEHIND_VERMILION`), `src/pokeagent/legs/states.py`, `src/pokeagent/legs/attach.py`, `tools/seg_store.py` (`ckpt`, `refusal`,
`ckpt_valid`), `tools/stamp_states.py`, `tests/test_state_fingerprint.py`. If any of these is missing, stop and write that in the Status row.
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

On 2026-11-07 the swarm ran the S.S. Anne captain segment from `runs/checkpoints/ss_anne_captain@63.state`, a state whose
blackout respawn was Cerulean (map 3) with the party at 6/79 HP: 309 ship blackouts went back across the map. The same tile
existed as `runs/legs/states/99_13_6.state` with respawn Vermilion (5) and the party at 79/79, and nothing could choose it
because states were picked by file name or mtime. PR #131 shipped the fingerprint sidecar (`statefp.py`), stamped every leg
state, and made `seg_store.refusal` refuse a ship-stage checkpoint that respawns behind Vermilion. What is still missing is
the part that CHOOSES: a pure-JSON ledger with a `select` function, wired into the two consumers, plus an operator CLI.

The exact fingerprint sidecar (`<state>.fp.json`, copied from the live `runs/checkpoints/to_vermilion.state.fp.json`, which
your worktree does not have; keys are sorted, `v` is 1):

```json
{"badges": 2, "bag_slots": 11, "frames": 0, "heal_items": 0, "map": 5, "money": 11258, "party": [[133, 12, 0, 27], [179, 29, 6, 79]], "respawn": 3, "v": 1, "x": 18, "y": 31}
```

Meaning: `map` = wCurMap, `x`/`y` = tile, `respawn` = wLastBlackoutMap (map id of the Pokecenter town a blackout returns to;
0 Pallet, 1 Viridian, 2 Pewter, 3 Cerulean, 5 Vermilion), `badges` = badge count, `money` = decoded BCD (-1 if the bytes are not
BCD), `party` = rows of `[species, level, hp, max_hp]`, `heal_items` = potions-class items carried, `bag_slots`, `frames`
(present only when the emulator exposes an int `frames`), and optional `source_run`. Any key can be absent: `statefp` is best
effort. A state with no sidecar reads as `None` from `statefp.read(path)`.

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

## 2. Scope (in order)

1. New module `src/pokeagent/statelog.py` (the ledger; reads JSON, never touches an emulator, never imports pyboy).
2. New module `src/pokeagent/statescmd.py` (the CLI handlers) and a small hook in `src/pokeagent/cli.py`.
3. The seam in `tools/seg_store.py::ckpt` and `src/pokeagent/legs/attach.py::plan` (+ the flag `--drill-min-hp` in `attach.add_args`
   and its pass-through in the explore scripts that call `attach.plan`; find them with `git grep -n "attach.plan" -- tools src`).
4. Tests: `tests/test_statelog.py`.
5. One edit in `docs/superpowers/specs/2026-11-07-save-state-ledger.md`: change the heading "Proposed: the ledger (two small modules)" to
   "Shipped: the ledger (select + CLI)" and name the two modules. Nothing else in docs.

## 3. The work

### 3.1 `statelog.py`

```python
@dataclass(frozen=True)
class Entry:
    path: Path            # the .state file
    fp: dict              # statefp.read(path) or {} when there is no sidecar
    mtime: float          # path.stat().st_mtime
    stem: str             # key: the file name up to the first dot or the at-sign (checkpoint variants like <goal>-at-sign-63.state, <goal>.best.state,
                          #      and leg rotations like 99_13_6.1.state all share the stem of their base name: goal or M_X_Y).
                          # Implementation: re.split(r"[.@]", path.name)[0]

@dataclass(frozen=True)
class Want:
    stem: str | None = None              # entry.stem must equal this (a checkpoint name or a leg key "M_X_Y")
    map: int | None = None               # entry.fp["map"] must equal this
    respawn_ahead_of: int | None = None  # entry.fp["respawn"] must be AT OR PAST this town (see RESPAWN_RANK)
    min_hp: float = 0.0                  # statefp.party_hp_fraction(fp) >= min_hp
    min_lead_level: int = 0              # fp["party"][0][1] >= this
    min_heal_items: int = 0              # fp["heal_items"] >= this
    strongest: bool = False              # rank by party power first (boss stages)
```

- `RESPAWN_RANK = {0: 0, 1: 1, 2: 2, 3: 3, 5: 4}`; any other map id ranks 5 (a later town: Lavender, Celadon, ...; a documented
  simplification, say so in the docstring). The respawn filter is `rank(fp["respawn"]) >= rank(want.respawn_ahead_of)`, so passing 5
  accepts Vermilion and later towns and rejects Pallet..Cerulean. A missing `respawn` key fails the filter.
- `entries(directory) -> list[Entry]`: every `*.state` directly in `directory` (not recursive), sorted by name. Missing directory = `[]`.
- `status(entry) -> "fresh" | "stale" | "retired"`: `retired` when `entry.path.parent.name == "retired"`; `stale` when `entry.fp` is empty
  or `entry.fp.get("v", 0) < statefp.VERSION`; else `fresh`.
- `select(entries, want) -> Entry | None`: drop every entry that is not `fresh`; apply `want`'s hard filters (an entry whose fingerprint
  lacks a key a filter needs FAILS that filter; never guess); then rank by `(power if want.strongest else 0, mtime)` descending,
  where `power = sum(level * hp / max_hp for each party row with max_hp > 0)`. Return the first, or `None` (None is the signal
  to use the old path).
- `pick(directory, want) -> Path | None`: `entries` then `select`, returning the path.
- `retire(path, why, retired_dir=Path("runs/retired")) -> Path`: move the state, its `.fp.json` and its goals sidecar
  (`checkpoint_goals.sidecar(path)`, when it exists) into `retired_dir` with `os.replace` (a rename; never delete, never
  copy-then-remove), create the dir, and append one line `<UTC ISO time>\t<name>\t<why>` to `retired_dir/RETIRED.log`. Raise
  `ValueError` on an empty `why`.
- `bad(entry) -> str | None`: the reason a state is bad, used by `list --bad` and `check`: no sidecar, stale `v`, or (stem in
  `checkpoint_goals.SHIP_GOALS` and respawn in `checkpoint_goals.BEHIND_VERMILION`). Otherwise `None`.

### 3.2 `statescmd.py` and `cli.py`

`cli.py` already has `from pokeagent.world.app import add_parser as _add_world` (around line 210) as the precedent. Do the same:
`from pokeagent.statescmd import add_parser as _add_states` and call it where `_add_world` is called. No logic in `cli.py`.

`pokeagent states <sub> [--dir D ...]`; default dirs are `runs/checkpoints` and `runs/legs/states` (a repeatable `--dir`
overrides). Handlers return an int exit code and take parsed args so tests call them without a process:

- `list [--map M] [--bad]`: one row per state: name, map, x,y, respawn, party (`species Llevel`), HP% (`party_hp_fraction`), money, `source_run`,
  status; `--bad` shows only states for which `statelog.bad` returns a reason, and prints the reason. A state with no sidecar shows `?` columns.
- `check`: prints the bad states, exits 1 when there is any ship state (stem in `SHIP_GOALS`, or fp map in `pokeagent.explorer.world.SHIP_MAPS`) with
  respawn in `BEHIND_VERMILION` or a missing/stale sidecar; exits 0 otherwise. Non-ship states without a sidecar are listed but do not fail.
- `restamp [--force] [--dry-run]`: delegates to `tools/stamp_states.py` (`main([...])`). Import it by inserting the repo's `tools/` dir on
  `sys.path` inside the handler (`Path(__file__).resolve().parents[2] / "tools"`); do not copy its code. It needs the ROM, so
  tests exercise only `--dry-run`.
- `retire PATH --why TEXT`: calls `statelog.retire`; prints where it went.

### 3.3 The seam (the old path stays as the fallback)

- `tools/seg_store.py::ckpt(root, name)`: after the `bedroom` branch, compute
  `want = Want(stem=name.split("@", 1)[0], respawn_ahead_of=5 if base in cg.SHIP_GOALS else None)` (base = `name.split("@", 1)[0]`) and try
  `statelog.pick(root / "runs" / "checkpoints", want)` first; return it when it is not None. When it IS None, run the existing code
  unchanged (the `found` list and the `respawn_behind` selection). Keep the signature and return type.
  `select` only returns `fresh` entries, so a checkpoint with no sidecar is never chosen by the new path and falls through to the
  old one: that is intended. Do not change `refusal` or `ckpt_valid`.
- `src/pokeagent/legs/attach.py::plan(...)`: add keyword `min_hp: float = 0.0`. For `drill_leg` (when `explicit_state` is not given),
  after the old `state = S.newest(...)`, try `statelog.pick(sd, Want(stem=f"{m}_{x}_{y}", min_hp=min_hp))` using the spec's
  `map` and `entry`, and let it replace `state` only when it returns a path; for `drill_grind`, the same with `Want(map=drill_grind, min_hp=min_hp)`
  replacing `S.newest_on_map`. Without a qualifying stamped state the old path result stands. `add_args` gets
  `--drill-min-hp` (float, default 0.0, "only start the drill from a state whose party HP fraction is at least this"); the explore
  scripts that call `attach.plan` pass `min_hp=args.drill_min_hp`.

## 4. What NOT to do

- Do not modify `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`, `statefp.py`, `legs/states.py`, or `checkpoint_goals.py`.
- Do not add a database or a central ledger file; the sidecars are the ledger.
- Do not delete anything anywhere in `retire` (rename only). Do not add fingerprint keys or bump `statefp.VERSION`.
- `statelog.py` must not import `pyboy`, `pokeagent.emulator`, or anything under `pokeagent.explorer` (only `statescmd.py` may import
  `pokeagent.explorer.world` for `SHIP_MAPS`). Never run `restamp` without `--dry-run`; there is no ROM.
- No module over 300 lines. Existing tests must stay green unedited.

## 5. Verification

- `uv run pytest -q tests/test_statelog.py` - new tests, with `FakeEmulator` + `statefp.stamp` + `tmp_path` (build states by
  `emu.save_state(p); statefp.stamp(emu, p)`, set `os.utime` to control age):
  1. `select` returns the same-stem state with respawn 5 over a newer one with respawn 3 when `respawn_ahead_of=5`.
  2. `min_hp` excludes a 6/79 party and admits 79/79; a missing key fails the filter.
  3. `strongest=True` prefers the higher `sum(level*hp/max_hp)` over a newer weaker one; among equals the newest wins.
  4. no sidecar / `v` 0 -> `stale` -> never selected; `select` over an empty or fully filtered list returns `None`.
  5. `retire` moves state + sidecar + goals sidecar, appends the log line, refuses an empty `why`, and the files are gone from the old dir.
  6. `seg_store.ckpt` returns the stamped good state when one exists and the old choice when none qualifies (a `tmp_path` root with
     `runs/checkpoints/`); `attach.plan` with `min_hp` picks a healthy rotation over an unhealthy base file and falls back when none qualifies.
  7. CLI: `states list --bad --dir <tmp>`, `states check` exit codes 1 and 0, `states retire`, `states restamp --dry-run` (call the handlers directly).
- `uv run pytest -q` green. Paste the before/after tails.
- Do NOT run `uv run pokeagent ...`. (Controller check afterwards, on the live checkout: `pokeagent states check`.)

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-state-ledger-select-directive`. Never commit to `main`; never push; never deploy. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 7. Completion criteria

- [ ] `statelog.py` (Entry, Want, entries, status, select, pick, retire, bad) and `statescmd.py` with list/check/restamp/retire, hooked into `cli.py`
- [ ] `tools/seg_store.ckpt` and `legs/attach.plan` use `select` first and fall back to the old path when it returns None
- [ ] `tests/test_statelog.py` covers the seven cases in section 5; `uv run pytest -q` green (paste the tail)
- [ ] No file in the "must not modify" lists changed (paste `git diff --stat main`)
- [ ] Status row moved to Review with the branch name

## 8. Report

Findings first: test tails (before/after), `git diff --stat`, line counts of the two new modules, exactly where each consumer calls
`select`, the `RESPAWN_RANK` simplification, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-state-ledger-select-directive |
| Base branch | - |
| Base commit | f89cce1990cccd0db71c274a10dc5a3b58825009 |
| Head commit | f3e63564ccbd9b3bae8dd6e88f641fd3d83084c6 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 12:15 · robert-claude-laptop · none → Draft — Claude 2026-11-07: ledger part 2 from the merged spec
- 2026-11-07 12:16 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override candidate: dispatch-path-missing on new test file and gitignored runs/ evidence path (greenfield)
- 2026-11-07 12:21 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing on greenfield files (tests/test_statelog.py) and gitignored evidence paths (runs/checkpoints/*.fp.json); known false positive
- 2026-11-07 12:21 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-state-ledger-select-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VGEY0J9T6GMN03W7TCWA4T
- 2026-11-07 12:29 · dispatcher · launched pid=1268; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-state-ledger-select-directive; provisioned: uv sync --frozen
- 2026-11-07 13:04 · devin-overseer (delegated) · In progress → Review — under delegate.envelope [origin] spent: devin 0 min est. n/a
<!-- queue:end -->
