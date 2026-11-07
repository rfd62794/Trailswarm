# PokeAgent: battle log fidelity - outcome, battle map and party on every record; fresh fingerprints on new checkpoints; verify wLastBlackoutMap

**Read first:** `src/pokeagent/explorer/party_log.py` (`PartyLog.start_battle`, `end_battle`), the battle-end block of
`src/pokeagent/explorer/behaviours/battle.py` (search for `battle_outcome(` and `runs/battles.jsonl`; about lines 225-260),
`src/pokeagent/explorer/grind.py` (`battle_outcome`), `src/pokeagent/explorer/press_goals.py`, `src/pokeagent/statefp.py`,
`docs/KNOWLEDGE.md` sections "RAM" and "Battle and level logs", `tests/test_xp_logging.py`, `tests/test_economy.py`,
`tests/test_inferred_goals_not_recorded.py`. If any of these is missing, stop and write that in the Status row.
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

From `runs/battles.jsonl` on 2026-11-07 (16,192 lines; analysis in `docs/superpowers/specs/2026-11-07-save-state-ledger.md`,
section "Rival / captain note"): 309 blackouts on the S.S. Anne maps, and the log is wrong about them in four ways.

1. A blackout is written `fled: true`. Cause (read the code): `battle.py` computes `"fled": not won and hp_end > 0`, but `hp_end` is
   read AFTER the warp, when the Pokecenter has healed the party, so every blackout has `hp_end > 0` and looks like a flee. The
   readers that detect a blackout as `won is False and not fled` (`explorer/economy/atlas.py`, `explorer/economy/hp_stats.py`) and
   `PartyLog.blackouts` (`if not won and not fled`) therefore under-count blackouts.
2. `map` is the map the run is on at the END of the battle, which for a blackout is the respawn town (Cerulean, 3), not the map the
   battle was fought on. Atlas consumers key on `map`, so ship fights are attributed to Cerulean.
3. 79 of the 309 blackouts have no party record at all (no `party_before` / `party_after`); `end_battle` returns `{}` on any error and
   the record is then written without party data. (The cause of the 79 is not established; make the failure visible, see 3.2.)
4. `rival_ss_anne` has no battle-won flag: its goal is `unverified` (no ROM-verified event flag), so nothing records that the rival fight
   was won, and the record does not say which trainer or stage a fight belonged to.

Old readers that must keep working: `tools/review_runs.py`, `tools/ab.py`, the stall dossiers (`tools/stalls.py`, `tools/replay_stall.py`),
`explorer/economy/*`, `grind/*`, `tools/xp_backfill.py`, `tools/grind_report.py`. They read the existing keys; keep every existing key.

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

1. `explorer/grind.py`: a pure `outcome_of(*, trainer, won, moved_away, party_count) -> str` returning `"won" | "lost" | "fled" | "blackout"`.
2. `explorer/party_log.py` + `explorer/behaviours/battle.py`: the record gains `outcome`, `battle_map`, `end_map`, `stage`, `trainer`, and a party
   snapshot on every record; `fled` and the `blackouts` counter become correct.
3. `explorer/press_goals.py`: stamp a fingerprint beside every new goal checkpoint.
4. `src/pokeagent/data/ram_map.json`, `src/pokeagent/data/ram_names.json`, `docs/KNOWLEDGE.md`: mark 0xD719 verified with evidence; document the new battle fields.
5. Tests: `tests/test_battle_log_fidelity.py`, plus one case for the stamp in `tests/test_inferred_goals_not_recorded.py`'s style in the same new file.

## 3. The work

### 3.1 `outcome_of` (in `grind.py`, next to `battle_outcome`)

```python
def outcome_of(*, trainer: bool, won: bool, moved_away: bool, party_count: int) -> str:
    # won -> "won"; a loss that warped us away -> "blackout"; no party left standing yet no warp -> "blackout" too (party_count == 0);
    # a wild battle that ended with us alive, not won -> "fled"; a trainer battle that ended with us alive and not won -> "lost"
```

Gen 1 has no other way to lose than a blackout, so `"lost"` should be rare (a trainer fight that ended neither in a win nor a warp,
e.g. a script that moved us); keep it so a surprise shows up in the data instead of being folded into another label.

### 3.2 The record (`battle.py`, battle-end block) and `party_log.py`

Compute `outcome = outcome_of(...)` from the same `trainer`, `won`, `moved_away` and `ctx.emu.read(0xD163)` values already used by
`battle_outcome`. Before `ctx.trainer_npc` is cleared, capture `trainer_info` from it (the dict `MapMemory.mark_trainer` returns; copy
only the keys `pic`, `x`, `y` that exist, plus the map id) or `None` when `ctx.trainer_npc` is None. Then write, in addition to every key
that exists today:

| key | value |
|---|---|
| `outcome` | `"won" \| "lost" \| "fled" \| "blackout"` from `outcome_of` |
| `battle_map` | `ctx.battle_pos[0]` (the map the battle started on); fall back to `m` when `ctx.battle_pos` is None |
| `end_map` | `m` (where the run stands after the battle: the respawn town for a blackout) |
| `map` | now `battle_map` (this is the fix for evidence item 2; for a win or a flee it equals the old value) |
| `fled` | now `outcome == "fled"` (the fix for item 1; this is the ONE deliberate change to an existing key's value) |
| `stage` | `training.stage_goal(ctx.goals())` (e.g. `"rival_ss_anne"`), or `None` on any error; import inside the function |
| `trainer` | `trainer_info` (`{"map","x","y","pic"}`) or `None` |
| `party_before`, `party_after` | present on EVERY record (see below) |
| `party_error` | only when the party snapshot failed: the exception's `repr` (so a missing party is visible, not silent) |

Party on every record: in `PartyLog.end_battle`, build `party_before` from `self.before` (the snapshot taken at battle start) and
`party_after` from the RAM snapshot independently, each in its own `try`; if the `after` read fails, still return `party_before` and
`party_error`; if `self.before` is None use the `after` snapshot for both (as today). `end_battle`'s signature gets `fled` from the
corrected value, so `PartyLog.blackouts` counts blackouts correctly. `end_battle` must still never raise.
`party_after` is read after the warp, so for a blackout it shows the healed party; do not "fix" that, and say so in the KNOWLEDGE.md note
(the HP at the moment of loss is the last `turns[-1].hp_you`).

Readers: keep all existing keys. Do not rename `won`, `kind`, `hp_end`, `run`, `turns`, `presses`, `start`, `end`, `enemy`, `you`,
`enemy_species`. The economy ledger call `ledger.of(ctx).battle(before, after, won, fled)` receives the corrected `fled`.
If an existing test fails because of the corrected `fled`/`map`, do NOT edit that test to make it pass: stop and write the test name and
the assertion in the Status row (the overseer decides).

`rival_ss_anne` and "battle-won flag": do NOT invent a RAM event flag (none is verified). The record `{"outcome": "won", "stage": "rival_ss_anne",
"trainer": {...}}` is the won-record until a ROM-verified flag exists. Say that in the KNOWLEDGE.md note and keep `rival_ss_anne` `unverified`.
The trainer class byte (`wTrainerClass`, pokered 0xD031) is a candidate for a later directive; it is UNVERIFIED, so do not read or use it here.

### 3.3 Fresh fingerprints on new checkpoints (`press_goals.py`, small)

In `record_goals`, inside the existing checkpoint `try:` and right after the `write_completed(...)` line, add

```python
try:
    from pokeagent import statefp
    statefp.stamp(ctx.emu, cp / f"{g}.state", ctx.run_dir.name)
except Exception:  # noqa: BLE001  (a stamp failure must never lose the checkpoint)
    pass
```

(`statefp.stamp(emu, state, source_run)` is best effort already; the inner try is belt and braces.) The stamp must come AFTER `write_completed`
and use the final state path `cp / f"{g}.state"`.

### 3.4 RAM map and docs (0xD719 `wLastBlackoutMap`)

- `src/pokeagent/data/ram_map.json` is a JSON array with one object per line (`pokeagent.ram_lookup.load_map` already reads an optional `evidence` key); the `wLastBlackoutMap` line is
  `{"name": "wLastBlackoutMap", "addr": "0xD719", "size": 1, "encoding": "u8", "region": "player", "verified": false, "source": "pokered.sym (pret/pokered, symbols branch)", "sym": "wLastBlackoutMap"},`
  Change `"verified": false` to `"verified": true` and add `"evidence": "<text>"` to that object. Keep the line valid JSON and the file's other lines byte-identical.
- `src/pokeagent/data/ram_names.json` is a pretty-printed list; its entry is
  `{"name": "wLastBlackoutMap", "addr": "0xD719", "size": 1, "encoding": "u8", "verified": false, "source": "pokered.sym (pret, symbols branch)", "note": "", "sym": "wLastBlackoutMap"}`.
  Set `"verified": true` and put the same text in `"note"`. Do not touch any other entry. Check how `src/pokeagent/names.py` loads the file
  (it reads `ram_names.json` through importlib resources; do not break the shape) and run the tests that touch it.
- The evidence text (use it verbatim, one line): `2026-11-07: read from 229 save states with one headless emulator: all 49 leg states on Vermilion and ship maps read 5 (Vermilion) after the Pokecenter heal; ship checkpoints saved before the heal read 3 (Cerulean); values seen 0,1,2,3,5,15. Spec docs/superpowers/specs/2026-11-07-save-state-ledger.md.`
- `docs/KNOWLEDGE.md`: add one row to the RAM table (after the `0xD35E` row): `| 0xD719 | wLastBlackoutMap | map id of the town a blackout returns to (the last Pokecenter healed at); 5 = Vermilion | 2026-11-07: ` + the same evidence text + ` |`.
  In "Battle and level logs", add a short paragraph listing the new battle-record keys from the table in 3.2, saying `fled` and `map` changed meaning
  for blackouts from this date (records before it have `fled: true` on blackouts and the respawn town in `map`; readers that need history should
  prefer `outcome` when present).

## 4. What NOT to do

- Do not modify `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`.
- Do not remove or rename any existing battle-record key; do not edit `runs/battles.jsonl` or any other file under `runs/`.
- Do not add a RAM read for a trainer class or an event flag; do not mark any goal verified.
- Do not touch the other `ram_map.json` / `ram_names.json` entries; do not reformat those files.
- Do not change `battle_outcome` or `record_battle_result` (another directive edits `record_battle_result` and one line of `battle.py` near
  `record_battle_result(ctx, ...)`; leave that line alone and edit only the record-building block after it).
- No module over 300 lines; no new dependencies.

## 5. Verification

- `uv run pytest -q tests/test_battle_log_fidelity.py` - new tests:
  1. `outcome_of`: win -> `won`; trainer loss with warp -> `blackout`; wild alive not won -> `fled`; trainer alive not won no warp -> `lost`; `party_count == 0` -> `blackout`.
  2. `PartyLog.end_battle` with a `FakeEmulator` ctx (as in `tests/test_economy.py` lines ~220-230): a blackout (`won=False, fled=False`) increments
     `log.blackouts`, returns `party_before` and `party_after`; when the `after` snapshot raises (monkeypatch `snapshot`), the result still has
     `party_before` and a `party_error`; it never raises.
  3. The battle-end record block (extract the dict-building into a small pure helper in `party_log.py` or `battle.py` if the block is not
     testable as is, e.g. `build_record(bl, *, outcome, battle_map, end_map, ...)`): a blackout gives `outcome == "blackout"`, `fled is False`,
     `map == battle_map != end_map`; a win keeps `map == end_map`; all legacy keys are still present.
  4. `press_goals.record_goals` (copy the setup of `tests/test_inferred_goals_not_recorded.py::test_inferred_unverified_goals_get_no_record`,
     but use a `FakeEmulator`) leaves `runs/checkpoints/<goal>.state.fp.json` next to the state, and a `statefp.stamp` that raises (monkeypatch) still
     leaves the `.state` and the milestone.
  5. `json.loads` of the whole `src/pokeagent/data/ram_map.json` text works, and the `wLastBlackoutMap` entries in both data files are `verified: true`
     (`pokeagent.ram_lookup` is the reader for `ram_map.json`; for `ram_names.json` load it with `json`).
- `uv run pytest -q` green; paste the before/after tails.
- Do NOT run `uv run pokeagent ...`.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-battle-log-fidelity-directive`. Never commit to `main`; never push; never deploy. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 7. Completion criteria

- [ ] `outcome_of`; record has `outcome`, `battle_map`, `end_map`, `stage`, `trainer`, party on every record (`party_error` on failure); `fled`/`map` corrected; legacy keys all present
- [ ] `press_goals` stamps `<goal>.state` after `write_completed`, never fatally
- [ ] 0xD719 `verified: true` with the evidence text in both data files; the KNOWLEDGE.md row and battle-fields paragraph
- [ ] `tests/test_battle_log_fidelity.py` passes; `uv run pytest -q` green (paste the tail); `git diff --stat main` pasted
- [ ] Status row moved to Review with the branch name

## 8. Report

Findings first: test tails (before/after), `git diff --stat`, which existing tests (if any) disagreed with the corrected `fled`/`map` (names and assertions),
how the pure record helper is wired, the sample record JSON for a blackout built in the tests, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-battle-log-fidelity-directive |
| Base branch | - |
| Base commit | c0d89df1460cce93c4fbefad92ccb875bcc57382 |
| Head commit | 4e2e8ecdfafe287fc739923224cb91e64d5de6b1 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 12:15 · robert-claude-laptop · none → Draft — Claude 2026-11-07: battle log fidelity + checkpoint stamp + 0xD719 verified
- 2026-11-07 12:16 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; lint_override candidate: dispatch-path-missing on gitignored runs/battles.jsonl evidence path
- 2026-11-07 12:23 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing on the gitignored evidence path runs/battles.jsonl; known false positive
- 2026-11-07 12:23 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-battle-log-fidelity-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VGK973P9BJYJZ10VE74T14
- 2026-11-07 12:29 · dispatcher · launched pid=2856; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-battle-log-fidelity-directive; provisioned: uv sync --frozen
- 2026-11-07 12:38 · devin · In progress → Review — Findings: outcome_of() added in grind.py; battle.py gains build_record() (pure helper doing bl.update with all legacy keys + outcome/battle_map/end_map/stage/trainer) and computes outcome from the same trainer/won/moved_away/0xD163 values as battle_outcome; trainer_info captured before ctx.trainer_npc is cleared; PartyLog.end_battle rebuilt so before/after snapshots are independent (party_error=repr(exc) on failure, money still booked, blackouts counted outside the party try, never raises). fled is now outcome=='fled' and map is now battle_map - NO existing test disagreed with the corrected fled/map. press_goals stamps a statefp fingerprint beside every new checkpoint after write_completed, inside its own try. 0xD719 marked verified in ram_map.json (evidence) + ram_names.json (note) with the verbatim text; KNOWLEDGE.md got the RAM row and the battle-fields paragraph. NOT LITERAL (one forced deviation): the directive's verbatim `from pokeagent import statefp` inside explorer/press_goals.py fails the repo's own layering gate test_explorer_package_layering_and_size (explorer/ may import only whitelisted pokeagent.* layers; statefp is not one). Routed the identical call through new checkpoint_goals.stamp_fingerprint (allowed layer; checkpoint_goals already wraps statefp) - same args, same never-fatal placement. Also: mark_trainer entries keep position in `last`, not x/y keys, so trainer_info fills x/y from `last` to match the documented {map,x,y,pic} shape; battle_outcome's call line is byte-identical (0xD163 read a second time for outcome_of); KNOWLEDGE.md row written literally as specified (`2026-11-07: ` + verbatim evidence text, which itself starts with the date, so the cell shows the date twice). Tests: before 1407 passed/36 skipped (75.6s); after 1417 passed/36 skipped (81.6s); tests/test_battle_log_fidelity.py 10 passed. git diff --stat vs base c0d89df: KNOWLEDGE.md +11, Battle_Log_Fidelity_Directive.md 6 (dispatcher queue rows), checkpoint_goals.py +6, ram_map.json 1 line, ram_names.json 4, battle.py +30/-6, grind.py +12, party_log.py +46/-10, press_goals.py +6/-2, test_battle_log_fidelity.py +165. Sample blackout record built by the tests (asserted fields): {"start":3,"kind":2,"enemy_species":165,"turns":[],"end":15,"won":false,"map":97,"presses":12,"fled":false,"outcome":"blackout","battle_map":97,"end_map":3,"stage":"beat_brock","trainer":{"map":97,"pic":55,"x":10,"y":7},"party_before":[[153,5,135,20,20]],"party_after":[[153,5,135,20,20]],"money_before":0,"money_after":0,"potions_before":null}. [origin] spent: devin 9 min est. n/a
<!-- queue:end -->
