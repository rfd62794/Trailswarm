# PokeAgent: Bandit switch decision point - let the behaviour bandit accept or decline the rule-based switch, with its own short episodes and an A/B report against the control slots

**Depends on `Lead_And_Wild_Switch_Directive.md` merged** (its fix round is running: it gives `team_plan.switch_choice` the wild mode and trainee safety, adds `can_damage` and `TRAINEE_SAFE_HP`, and makes `src/pokeagent/explorer/behaviours/switch_out.py` consult the matchup switch in wild fights too, which is what makes this decision point worth having). If `git grep -n "TRAINEE_SAFE_HP" -- src/pokeagent` finds nothing at the start of the run, stop and write that in the Status row; do not recreate it. Base: a main that contains that directive. **Coordinate with** `Battle_Stat_Stage_And_Enemy_Moves_Directive.md` and `Battle_Status_Conditions_Directive.md` (queued; they change what `switch_choice` proposes and edit `_matchup_pick` / `_foe` in `switch_out.py`; this directive changes only `matchup_pick`, the cache wrapper around `_matchup_pick`, so whichever merges second rebases trivially).

## Why this exists

Robert, 2026-11-05 (the design of record): reinforcement learning picks behaviours, never buttons; the Explorer stays the backbone. The behaviour bandit (`src/pokeagent/bandit/`) already holds three decision points, and Robert's perception-and-learning inventory (2026-11-14) found the new switch logic has no learner behind it: the rule-based switch (`team_plan.switch_choice`) is a pile of untuned constants (`SWITCH_GAIN`, `SWITCH_HP_TURNS`, `WEAK_RATIO`, `SWITCH_MIN_HP`) and the only way to learn whether it helps is to let some runs decline it and compare.

Facts, read on origin/main 01b7fd6:

- `src/pokeagent/bandit/points.py:6`: `ARMS = wild_battle (fight, flee), heal (heal_now, push_on), train (grind, skip)`; `context_key(point, stage, map_id, hp, mx, gap)` (L17-18) builds `point|stage|map|hp bucket|gap bucket`; the shared helpers `hp_bucket` and `gap_bucket` sit above it.
- `src/pokeagent/bandit/driver.py`: `BanditDriver.decide(point, tag, key, default)` (L32-45) returns the held arm while `tag` is unchanged, else a Thompson draw from `table.choose` (which returns the DEFAULT arm until the default has `MIN_N = 5` samples in that context, `table.py`), and opens an `Episode`; `after_press(ctx, rec, tossed)` (L58-) feeds every press record to every open episode and closes the ones that report done. `driver.tag(rec)` stamps `driver` and `arm` on decision lines only when the bandit is on (`src/pokeagent/explorer/engine.py:87-88`).
- `src/pokeagent/bandit/reward.py:7-9`: `PRESS, GOAL, STALL, BLACKOUT, TOSS = -0.01, 1.0, -2.0, -3.0, -5.0`; `NOVELTY_SCALE, NOVELTY_CAP = 0.1, 0.5`; `MAX_PRESSES = 300`. An `Episode` ends on a goal or after 300 presses. A switch decision is made and resolved inside one battle (tens of presses), so a goal-or-300-presses episode would bury the signal under unrelated rewards.
- `src/pokeagent/bandit/hook.py`: the pattern to copy. `wild_flee(ctx, rule_flee)` returns the rule's answer when `ctx.bandit is None`, applies a shield first (`FIGHT_FLOOR = 0.25`: below it no decision, no episode), calls `drv.decide(...)`, and catches every exception (`_safe`) so a bandit error never stops a run.
- `src/pokeagent/explorer/behaviours/switch_out.py:61-71` `matchup_pick(ctx)` caches `_matchup_pick(ctx)` (the `(slot, why)` the rule proposes, or None) per step and battle in `team_plan.of(ctx)`; `SwitchOut.applies` (L136-) and `_matchup_step` (L189-) both read it, and a switch already underway (`st["matchup"]`) is never re-asked, so declining happens BEFORE the menu presses start.
- Battle records: `src/pokeagent/explorer/behaviours/battle.py` writes one line per battle to `runs/battles.jsonl` (`build_record`, L57-, and the `party_log` merge at L279) with `run`, `won`, `outcome`, `stage`, `matchup_switches` and `party_before` / `party_after` rows of [species, level, exp, hp, max_hp] (`src/pokeagent/explorer/party_log.py`). Those records exist for EVERY run, bandit or control, so faints per battle can be compared without the bandit's own logging.
- `tools/swarm.py` `--bandit` and `--bandit-share` (L214, L218) run the bandit in that share of the slots with `--bandit` and leave the rest as controls (`bandit_slots`, L146-148; `Launcher._bandit_args`, L94-98); `tools/swarm_continuous.py:266` `_merge_bandit` folds each agent's delta into `runs/bandit.json`. Nothing in this directive changes the swarm.

## Scope (in this order)

1. `src/pokeagent/bandit/points.py` - `ARMS["switch"] = (stay, switch)` and the pure `switch_eligible`.
2. `src/pokeagent/bandit/switch_reward.py` <!-- new: src/pokeagent/bandit/switch_reward.py --> - the switch episode and its reward constants. Under 130 lines.
3. `src/pokeagent/bandit/driver.py` - `after_press` lets an episode observe the context (net growth under 8 lines).
4. `src/pokeagent/bandit/hook.py` - `switch_pick(ctx, pick)`.
5. `src/pokeagent/explorer/behaviours/switch_out.py` - `matchup_pick` runs the pick through the hook (net growth under 6 lines).
6. `src/pokeagent/bandit/compare.py` <!-- new: src/pokeagent/bandit/compare.py --> - the bandit-versus-control comparison, pure over files. Under 150 lines.
7. `tools/bandit_report.py` <!-- new: tools/bandit_report.py --> - a read-only CLI that prints the report line. Under 80 lines.
8. Tests: `tests/test_bandit_switch.py`, `tests/test_switch_reward.py`, `tests/test_bandit_compare.py` <!-- new: tests/test_bandit_switch.py --> <!-- new: tests/test_switch_reward.py --> <!-- new: tests/test_bandit_compare.py -->.

## The work

Existing signatures, pasted (the worktree cannot be searched; `uv run python --version` prints `Python 3.12.12`):

```
# src/pokeagent/bandit/points.py
ARMS = wild_battle (fight, flee), heal (heal_now, push_on), train (grind, skip)       # a dict point -> tuple of arm names
def hp_bucket(hp, mx) -> int; def gap_bucket(gap) -> str
def context_key(point, stage, map_id, hp, mx, gap) -> str
# src/pokeagent/bandit/driver.py
class BanditDriver: decide(point, tag, key: Callable[[], str], default) -> str;  clear(point);  after_press(ctx, rec, tossed) -> list[dict]
    sticky: point -> (tag, arm, Episode);  open: list[Episode];  _close(ep) records ep.reward into the shared cells and the run delta
# src/pokeagent/bandit/reward.py
@dataclass class Episode: point, key, arm, default, presses=0, reward=0.0, stalled=False, done=False, novelty=0.0;  add(rec) -> bool (True when it just ended)
# src/pokeagent/bandit/hook.py
FIGHT_FLOOR = 0.25
def wild_flee(ctx, rule_flee: bool) -> bool;  def _safe(ctx, name, exc) -> None
# src/pokeagent/explorer/behaviours/switch_out.py
def matchup_pick(ctx) -> tuple[int, str] | None      # (slot, why), cached on (step, battle)
def _matchup_pick(ctx) -> tuple[int, str] | None
# src/pokeagent/explorer/behaviours/battle.py: BattleView(kind, hp, mx, run_line, species, my_sp, my_lvl, e_lvl, want_potion, cur, threat) is ctx.bv
# src/pokeagent/explorer/context.py is at 300 lines: add no field to ExplorerContext. Keep every new run-state in the driver or in team_plan.of(ctx) (a plain dict).
```
Style to copy for the fake context and driver tests: `tests/test_bandit.py` (`test_wild_fight_arm_overrides_a_weak_flee` L244, `test_fight_floor_shield_below_25_percent` L331, `test_hooks_pass_the_explorer_answer_through_when_off` L197).

### 1. The decision point

`ARMS["switch"] = ("stay", "switch")`. The DEFAULT arm is "switch": the hook is consulted only when the rule-based `switch_choice` has already proposed a switch, so the unvisited-context behaviour (`table.choose` answers the default until it has `MIN_N` samples) is exactly the rule-based behaviour today. The bandit can only DECLINE a proposed switch; it never invents one, never picks the target slot and never presses a button (the existing menu machinery performs the switch).

Context key: `context_key` called with the point "switch", the stage, the map, the active HP pair and the level gap with `hp, mx` the ACTIVE member's current and max HP, `gap` the active member's level minus the foe's (`ctx.bv.my_lvl - ctx.bv.e_lvl`), `stage` from `goal_stage(ctx.goals())` as `wild_flee` does, the map `ctx.view.m`. Tag for `decide`: the pair (`ctx.battles`, matchup switches already made this battle from `ctx.battle_log`), so the arm is held within one decision and re-drawn after a completed switch.

Pure eligibility, `points.switch_eligible(hp, mx, can_damage, is_trainee) -> bool`: False (the bandit is not consulted; the rule's pick stands; no episode) when the active member's HP fraction is below `STAY_FLOOR` (use `team_plan.TRAINEE_SAFE_HP`, the in-flight directive's constant, imported, not copied), when the active member cannot damage the foe (`can_damage`: use the in-flight directive's helper from wherever `git grep -n "def can_damage" -- src/pokeagent` finds it), or when the active member is the designated trainee (`explorer.training_ctl.roster.trainee_slot(ctx)` equals the active slot). These are the shield: safety and no-damage rules are not the bandit's call, exactly as `FIGHT_FLOOR` shields `wild_flee`.

### 2. hook.switch_pick

```
def switch_pick(ctx, pick: tuple[int, str] | None) -> tuple[int, str] | None
```
`pick` is the rule's `(slot, why)` or None. Returns `pick` unchanged when `ctx.bandit is None`, when `pick` is None, when the shield says not eligible, and on any exception (`_safe`). Otherwise `arm = drv.decide("switch", tag, key, "switch")`; when the arm is "stay" return None (this step's `matchup_pick` is None, so `SwitchOut` does not apply and the fight goes on), else return `pick`. The first time a (battle, switch-count) tag is seen, stamp the open episode with the proposed target slot and the active slot (`ep.target`, `ep.active`) so the reward can find them. Leave the rule string unchanged (the engine already stamps `driver` and `arm` on decision lines via `driver.tag`).

### 3. The switch episode and its reward (switch_reward.py)

A `SwitchEpisode` (a subclass of `reward.Episode`) that closes at the END OF THE BATTLE (`ctx.battles` moves on, or `ctx.in_battle` is false), or after `SWITCH_MAX_PRESSES = 600`, never on a goal. It has `observe(ctx, rec) -> bool` (called by the driver on every press) that tracks, from the party view (`pokeagent.party_view.read_party_view`, which is memoised per frame, so the call is cheap): whether the switch landed (`active_slot` equals `target`), the incoming member's HP and whether it is still alive `SURVIVE_PRESSES = 8` presses after the swap landed (a turn is a handful of presses; named, untuned), whether the member that was active at decision time fainted, whether the battle was won (`ctx.battles_won` rose), and a blackout event. It never reads the emulator itself beyond `read_party_view`.

Reward constants (NEW, in `switch_reward.py`; the constants in `reward.py` are not changed and not redefined, `BLACKOUT` is imported):

```
SWITCH_COST = -0.05        # per switch executed: small, so flapping is discouraged but one needed switch is cheap
SURVIVE_WIN = 1.0          # arm "switch": the incoming member lived SURVIVE_PRESSES presses after landing AND the battle was won
STAY_FAINT = -2.0          # arm "stay": the member that was active at the decision fainted before the battle ended
STAY_WIN = 1.0             # arm "stay": that member never fainted AND the battle was won (symmetric with SURVIVE_WIN so the stay arm can earn, see below)
(an executed switch that fails the survive test, or a lost battle, earns neither bonus; a blackout adds reward.BLACKOUT)
```
`STAY_WIN` goes beyond the brief (which lists the switch bonus and the stay penalty only): without a positive path for "stay" the stay arm could never beat the 0 prior and the table would be one-sided. It is a single named constant, flagged in the Report for Robert to veto. The total is the sum of the applicable terms; there is no per-press cost and no goal reward.

`driver.after_press`: for each open episode, if it has an `observe` method call `ep.observe(ctx, r)` instead of `ep.add(r)` for press records, but still feed it event records (the `blackout` event reaches `SwitchEpisode.add`, which adds `BLACKOUT`); existing episodes are unchanged.

### 4. Wiring

`switch_out.matchup_pick`: where it caches `_matchup_pick(ctx)`, wrap it: `st["mu_pick"] = switch_pick(ctx, _matchup_pick(ctx))` (import from `pokeagent.bandit.hook`; `bandit` is already on the explorer import allow-list in `tests/test_explorer_behaviours.py`). Nothing else in `switch_out.py` changes.

### 5. The report line (compare.py and tools/bandit_report.py)

`compare.py` is pure over files and takes a root path (tests pass `tmp_path`): `runs/<run>/decisions.jsonl` (a run is a BANDIT run when any press line carries a `driver` key, else a CONTROL run; read at most the first 200 lines), `runs/battles.jsonl`, `runs/<run>/goal_frames.jsonl` (one line per goal reached) and `runs/bandit.json` (cells keyed `switch|...`, arm -> [n, sum, sumsq]). It returns a record and a one-line string. Per group (bandit, control): runs, battles, faints per 100 battles (a faint = a `party_before` row with HP above 0 whose `party_after` row, same index, has HP 0), switches per 100 battles (sum of `matchup_switches`), goals per 10,000 presses (goal lines over press lines). Plus the switch arms from the shared table: for the "stay" and "switch" arms, summed n and mean reward over all `switch|` cells. Line format:

```
switch point: bandit 7 runs / 212 battles / faints 4.2 per 100 / switches 9.0 per 100 / goals 1.9 per 10k presses | control 7 runs / 198 battles / faints 5.6 / switches 11.1 / goals 1.7 | arms: switch n=120 mean +0.31, stay n=34 mean +0.12 | advisory: fewer than 50 battles per group, no verdict
```
The word after "advisory:" is "no verdict" until BOTH groups have at least `MIN_BATTLES = 50` battles, then "bandit lower faints" / "bandit higher faints" / "no difference" by a plain rate comparison with a margin of 10 percent of the control rate; it never claims significance. Controls and bandit runs share a swarm, so the comparison is only meaningful over runs of the same time window: accept `--since <ISO date or run-name prefix>` and `--stage <goal>` filters (a battle record carries `stage`). `tools/bandit_report.py` parses `--runs-dir` (default `runs`), `--since`, `--stage`, prints the line and exits 0; it opens files read-only and never writes.

### Tests

- `tests/test_bandit_switch.py`: with `ctx.bandit` None `switch_pick` returns the rule's pick for any input; the shield (HP fraction below the floor, an active member that cannot damage, the trainee) returns the rule's pick and opens no episode; an unvisited context answers "switch" (the pick passes through); a context where "stay" has been seeded with strong evidence (build the cells like `tests/test_bandit.py::test_strong_evidence_moves_off_the_default_and_weak_evidence_does_not`) returns None; the same (battle, count) tag holds the arm across steps and a new count re-draws; an exception inside the hook returns the pick and logs `[bandit switch skipped: ...]`; `matchup_pick` returns None when the arm is "stay" and the pick when "switch" (a fake ctx like `test_wild_fight_arm_overrides_a_weak_flee`).
- `tests/test_switch_reward.py`: drive a `SwitchEpisode` with a scripted sequence of fake context observations: switch landed, incoming alive 8 presses later, battle won gives `SWITCH_COST + SURVIVE_WIN`; switch landed, incoming fainted early, battle won gives `SWITCH_COST` only; stay, active faints gives `STAY_FAINT`; stay, no faint, battle won gives `STAY_WIN`; a blackout event adds the unchanged `reward.BLACKOUT`; the episode closes at battle end and at `SWITCH_MAX_PRESSES`; assert the constants in `reward.py` still equal -0.01, 1.0, -2.0, -3.0, -5.0 and that wild_battle, heal and train episodes behave as before (the existing `tests/test_bandit.py` reward tests must pass unchanged).
- `tests/test_bandit_compare.py`: build two fake run dirs (one with `driver` keys on press lines, one without), a battles.jsonl with `party_before` and `party_after` rows (one faint in one group, none in the other), goal_frames lines and a `bandit.json` with `switch|` cells in `tmp_path`; assert the counts, the rates, the exact line, "no verdict" below 50 battles and a verdict above it, and that the files are byte-identical afterwards (read-only).

## What NOT to do

- Do not change any existing reward constant, `table.py` (`MIN_N`, `PRIOR_N`, `ALT_MARGIN` ...), the three existing decision points, `driver.decide`'s signature, the swarm (`tools/swarm.py`, `tools/swarm_continuous.py`), or `src/pokeagent/explorer/engine.py`.
- Do not let the bandit choose the target slot, press anything, override the shield, or consult the point when no switch was proposed. RL picks behaviours, never buttons (Robert, 2026-11-05).
- Do not edit `team_plan.switch_choice` or any switch constant, and do not add a field to `ExplorerContext` (`context.py` is at its 300-line cap); do not edit `src/pokeagent/explorer/behaviours/battle.py` (299 of 300 lines).
- Do not read or write the real `runs/` (a swarm is running): the report and every test use `tmp_path`. Do not start a swarm, a run, or an emulator.
- Do not claim the bandit helps. The report line is advisory, from synthetic or organic counts as they come; no code, comment or PR text may call a synthetic pass proof.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_bandit_switch.py tests/test_switch_reward.py tests/test_bandit_compare.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_bandit.py tests/test_ab.py tests/test_switch_matchup.py tests/test_explorer_behaviours.py tests/test_layers.py
```
Expected: no new failures. Claude ran this exact command on origin/main 01b7fd6 while writing the directive: `81 passed, 1 warning in 2.22s`.

```
git diff --stat origin/main -- src/pokeagent tools
```
Expected: `points.py`, `switch_reward.py`, `driver.py`, `hook.py`, `compare.py`, `switch_out.py`, and `tools/bandit_report.py` only.

## Completion criteria

- [ ] `ARMS["switch"]` exists with default "switch"; `switch_pick` passes the rule's pick through when the bandit is off, when no pick exists, when the shield applies, in an unvisited context and on any exception, and returns None only for a "stay" arm. <!-- test: tests/test_bandit_switch.py -->
- [ ] `matchup_pick` returns None on "stay" and the pick on "switch", and a switch already underway is never re-asked. <!-- test: tests/test_bandit_switch.py -->
- [ ] `SwitchEpisode` pays `SWITCH_COST`, `SURVIVE_WIN`, `STAY_FAINT`, `STAY_WIN` and the unchanged `BLACKOUT` exactly as above, closes at battle end or `SWITCH_MAX_PRESSES`, and the existing reward constants and episode tests are unchanged. <!-- test: tests/test_switch_reward.py -->
- [ ] `compare` and `tools/bandit_report.py` print the line above from fixture runs, say "no verdict" below 50 battles per group, and leave every input file byte-identical. <!-- test: tests/test_bandit_compare.py -->
- [ ] The existing test files in the second verification command pass unchanged, and both size and layering tests stay green.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, every new constant and value (`STAY_FLOOR` source, `SWITCH_COST`, `SURVIVE_WIN`, `STAY_FAINT`, `STAY_WIN`, `SURVIVE_PRESSES`, `SWITCH_MAX_PRESSES`, `MIN_BATTLES`), and the `STAY_WIN` deviation called out for Robert. Then the organic confirmation Claude runs afterwards (Devin cannot; a swarm is running, so Claude schedules it): start the swarm with `--continuous --bandit --bandit-share 0.5` so half the slots decide and half are controls on the same checkpoints, let it collect at least 50 battles per group, run `uv run python tools/bandit_report.py --since <start>`, and read `decisions.jsonl` lines carrying `arm=switch=stay` to confirm a declined switch really leaves the fight going and the episode closes at battle end. Until both groups pass `MIN_BATTLES` the point stays on the rule default (the table answers "switch" in every unvisited context), so merging this changes no behaviour by itself; whether the bandit improves faints or goal rate is Robert's call on the organic report, not on any test here.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command (`uv run python --version` prints `Python 3.12.12`); never bare `python`.
- Branch only (`directive/pokeagent-bandit-switch-decision-point-directive`); commit as you go; never commit to or push main; never merge.
- Standing rule for synthetic data (Robert, 2026-11-07, verbatim): "We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system." Every test here is synthetic (FakeEmulator memory or plain tables); a green run is a claim. The Report names the organic confirmation Claude runs afterwards, and the code, comments and PR text never describe a synthetic pass as proof.
- No ROM data is committed (no ROM bytes, no extracted tables, no save states); tests never open a window or send input; no emulator runs.
- SOLID and KISS: every NEW module stays under 150 lines and does one job; an explorer file never passes 300 lines (`tests/test_explorer_behaviours.py::test_explorer_package_layering_and_size` enforces it, and its import allow-list: explorer code may import only the listed `pokeagent.*` layers, `knowledge`, `bandit`, `party_view`, `ramstructs`, `ram_symbols` among them); `tests/test_layers.py` forbids package code importing `tools`. No `global` statements in package code (cache with a dict or `functools.lru_cache`).
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not read or write anything under `runs/` (a swarm is running), `baselines/` or `roms/`; do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The organic check named in the Report section, run by Claude with the ROM after the verify lane passes (a swarm is running; Claude schedules it). Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
