# PokeAgent: Lead and wild switch - lead with a member that can hurt the foe, switch out of losing wild fights, never let a trainee faint

**Independent of the save-library directives.** Base: current main.

## Why this exists

Robert, 2026-11-14: "The Agent keeps using low-levelled pokemon in battle until they faint, instead of relying on the swap tactic where more effective."

Claude diagnosed this from `runs/battles.jsonl` (read-only) and the code. Measured, last 5,000 battle records, faints of a member that entered a fight alive: wild WEEDLE L4 x9, trainer KAKUNA L5 x7, wild KAKUNA L5 x7, trainer WEEDLE L4 x6, wild RATTATA L3 x6. Example (run `explore-20261114-140836-23640`, wild fight on map 13): a wild-caught KAKUNA L5 (19 HP, knows only HARDEN) led, chose `FIGHT PKMN` then `HARDEN` about 15 times against a foe with 20 HP while its own HP went 19, 16, 13, 11, 9, 7; a POTION at HP 7, then 12, 10, 8, 6; it fainted (forced `YES` replacement at step 1170). In a trainer fight (`beat_brock`) a KAKUNA L5 chose `FIGHT PKMN`, `HARDEN` 20 times with the foe at 27 HP untouched and fainted.

Mechanics behind it (all file:line against main):

- **The weakest member leads, always.** `src/pokeagent/knowledge/team_plan.py` `ascending_order(levels, fainted)` sorts lowest level first; `src/pokeagent/explorer/behaviours/party_order.py` `want_home` applies it. A Harden-only KAKUNA is the lowest level, so it leads every fight.
- **Only the trainee swaps on turn one.** `src/pokeagent/explorer/behaviours/switch_out.py` `trainee_out` returns a slot only for the training trainee; `team_plan.trainee_slot` (L187-205) accepts a WEEDLE or a KAKUNA that knows POISON STING (`_our_weedle_line`), so a wild KAKUNA is never the trainee and never swaps.
- **Wild fights never get the matchup switch.** `_matchup_pick` in `switch_out.py` returns None unless `bv.kind == 2` (a trainer). `team_plan.switch_choice` is trainer-only and capped at `MAX_SWITCHES_PER_BATTLE = 2`.
- **Heal and flee run before the switch.** `Battle()` runs before `SwitchOut()` (`src/pokeagent/explorer/behaviours/__init__.py` line 59). In `src/pokeagent/explorer/behaviours/battle.py` (lines ~160-225) `want_potion` and `flee` are decided first, so a no-damage mon is potioned or RUN-ed instead of swapped.

## Scope (in this order)

1. `src/pokeagent/knowledge/team_plan.py` - add `can_damage` and `lead_order`; add an incoming-survives check and a wild mode to `switch_choice`; add trainee-safety. Pure functions only.
2. `src/pokeagent/explorer/behaviours/party_order.py` - `want_home` uses `lead_order` when move data is available.
3. `src/pokeagent/explorer/behaviours/switch_out.py` - `_matchup_pick` also runs in wild fights (`bv.kind == 1`), with the wild rules below.
4. `src/pokeagent/explorer/behaviours/battle.py` - rule 5 (no potion/flee for a no-damage member when a healthy switch-in exists).
5. `tests/test_lead_and_wild_switch.py` <!-- new: tests/test_lead_and_wild_switch.py --> - synthetic parties, no ROM.

## The work

Existing signatures to build on (pasted; the worktree cannot be searched):

```
# src/pokeagent/knowledge/team_plan.py
def ascending_order(levels, fainted) -> list[int]:        # lowest level first, fainted last, stable
def next_swap(levels, fainted) -> tuple[int, int] | None:
def trainee_slot(party, named=None, breakers=(), wild=None, kb=None) -> int | None:
def switch_choice(team, active_slot: int, opponent, kb, *, hp_now=None, switches: int = 0,
                  trainee: int | None = None) -> int | None:
SWITCH_HP_TURNS = 2; WEAK_RATIO = 0.5; SWITCH_MIN_HP = 0.25; SWITCH_GAIN = 1.5; MAX_SWITCHES_PER_BATTLE = 2
# src/pokeagent/knowledge/readiness.py
def best_move(att: Combatant, dfn: Combatant, chart: dict, moves: dict) -> tuple[float, str]:
    # (expected damage per turn, move name); (0.0, "") when no move damages
# src/pokeagent/knowledge/party.py: Combatant(name, level, types, hp, stats, moves, dv, sexp); hp is MAX hp
# src/pokeagent/magikarp.py
def switch_candidate(emu, trainee: int | None = None) -> int | None:   # strongest healthy non-trainee, HP >= 25%
```
Existing test to copy the synthetic-table style from: `tests/test_switch_matchup.py` (`SYN` kb tables with `moves`, `type_chart`, `species_by_dex`, helper `_mon(name, level)` building a `Combatant`). `uv run python --version` prints `Python 3.12.12`.

### Rule 1 - lead by usable damage

`team_plan.can_damage(c, kb=None) -> bool`: True when any move of Combatant `c` has power above 0 in the `moves` table (`table(kb, "moves")`, row keys `name`, `power`). A member with no damaging move (a Harden-only KAKUNA) is False. `team_plan.lead_order(levels, fainted, can_dmg) -> list[int]`: like `ascending_order` but sorted by `(fainted, not can_dmg, level)`, so fainted last, then members that cannot hurt a foe, then ascending level. `can_dmg=None` returns `ascending_order(...)` exactly (existing tests unchanged). In `party_order.want_home`, build `can_dmg` from `our_party(ctx.emu)` (from `pokeagent.knowledge.party`) when the move table is loaded; with no ROM data fall back to the old rule. A no-damage member therefore sits at the back, and the lowest-level DAMAGING member (a Weedle, a Rattata) leads. `next_swap` takes an optional `want` list so it can use either ordering; keep its old behaviour for old callers.

### Rule 2 - wild fights get the thin switch

In `switch_out._matchup_pick`, replace `if bv is None or getattr(bv, "kind", None) != 2: return None` with: kind 2 (trainer) as today; kind 1 (wild) uses the wild mode below; anything else None. Wild mode calls `team_plan.switch_choice(..., wild=True)`. In wild mode "thin" means only (a) the foe's best expected hit over `SWITCH_HP_TURNS` turns meets or beats the active member's CURRENT HP, or (b) the active member cannot damage the foe (`best_move(active, foe)[0] == 0`). The weak-ratio test (`our_dmg <= WEAK_RATIO * foe.hp`) is NOT used in wild fights: a wild grind may fight on purpose. The 2-per-battle cap still applies.

### Rule 3 - expected-damage switch with the incoming-survives check

Extend `switch_choice` (keep current positional/keyword behaviour; new keyword `wild: bool = False`): a candidate `c` at current HP `ci` is eligible only when it survives the hit it takes on the switch turn: `best_move(foe, c, chart, moves)[0] < ci` (Gen 1: switching costs a turn and the incoming mon takes the foe's attack). Keep `SWITCH_MIN_HP` and `SWITCH_GAIN`. When the active member cannot damage the foe at all (`our_dmg == 0`) the gain test becomes "candidate damage is above 0".

### Rule 4 - trainee safety

A designated trainee never stays in to faint. In `switch_choice`: when `active_slot == trainee` and its current HP fraction is below `TRAINEE_SAFE_HP = 0.35` (new constant, untuned) and an eligible candidate exists, return that candidate even if the active member is not "thin". The existing rule "never switch the trainee IN" stays. `SwitchOut.applies` already reaches `_matchup_pick` while the trainee is out; if the trainee turn-one swap could not run (`switch_gave_up`), this rule is the backstop.

### Rule 5 - no heal or flee for a no-damage member while a healthy switch exists

In `battle.py`, before `want_potion` and `flee` are used: when the active member cannot damage (all its known moves have power 0, from `table(None, "moves")`) and `magikarp.switch_candidate(ctx.emu, trainee)` returns a slot, set `want_potion = False` and `flee = False` for this step, so `SwitchOut` (next in the behaviour list) swaps it out. When no healthy candidate exists, behaviour is unchanged (potion/flee as today). Do not change `stall_run`, `cave_run`, `train_fight`, or the Harden-only cocoon logic in `src/pokeagent/explorer/behaviours/low_yield.py`.

### Tests (`tests/test_lead_and_wild_switch.py`)

Reuse the `SYN` tables (add a HARDEN row with power 0 and a POISON STING row with power 15) and `_mon`. Required cases: `can_damage` False for a Harden-only KAKUNA, True for a WEEDLE with POISON STING; `lead_order` puts the Kakuna last and the lowest damaging member first, and `lead_order(..., None)` equals `ascending_order`; `switch_choice(..., wild=True)` switches a Harden-only active (foe in range) to a healthy damaging member, does NOT switch a weak-but-damaging member on the weak-ratio test, and switches on the HP-danger test; the incoming-survives check rejects a candidate at 3 HP that the foe one-shots and accepts a healthy one; trainee below 35% HP switches out when not thin; trainee at 60% HP does not; `MAX_SWITCHES_PER_BATTLE` still caps; `_matchup_pick` (follow `tests/test_switch_matchup.py` for the synthetic ctx) returns a pick for `bv.kind == 1` and None for `kind == 0`.

## What NOT to do

- Do not change `ascending_order` semantics for existing callers (`tests/test_party_order_ascending.py` must pass unchanged), the trainee selection `team_plan.trainee_slot`, catch logic (`catch_list.py`, `catch.py`), or `battle_moves.py` / the PP guard (`PP_Zero_Move_Guard_Directive.md` owns it).
- Do not retune `SWITCH_GAIN`, `SWITCH_HP_TURNS`, `WEAK_RATIO`, `SWITCH_MIN_HP`.
- No emulator runs, no ROM, no windows. No real RAM reads in tests; `FakeEmulator` is acceptable where the existing tests use it.
- Do not edit any directive's queue block, and do not touch `runs/`, `baselines/`, `roms/`, or save states.
- Do not state where any game copy came from.

## Verification (exact commands)

```
uv run --frozen pytest -q tests/test_lead_and_wild_switch.py
```
Expected: all pass.

```
uv run --frozen pytest -q tests/test_switch_matchup.py tests/test_party_order_ascending.py tests/test_trainee_gate.py tests/test_training_ctl_roster.py
```
Expected: no new failures. Claude ran this exact command on main while writing the directive; the tail is in the PR description.

```
git diff --stat origin/main -- src/pokeagent
```
Expected: only `team_plan.py`, `party_order.py`, `switch_out.py`, `battle.py`.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- Branch only (`directive/pokeagent-lead-and-wild-switch-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] `can_damage` and `lead_order` exist, the Harden-only KAKUNA sorts behind every damaging member, and `lead_order(..., None)` equals `ascending_order`. <!-- test: tests/test_lead_and_wild_switch.py -->
- [ ] `_matchup_pick` returns a pick in a wild fight when the active member cannot damage or faces a KO within `SWITCH_HP_TURNS`, and returns None for the weak-ratio-only case in a wild fight. <!-- test: tests/test_lead_and_wild_switch.py -->
- [ ] The incoming-survives check rejects a candidate the foe would KO on the switch turn. <!-- test: tests/test_lead_and_wild_switch.py -->
- [ ] A trainee below `TRAINEE_SAFE_HP` switches out when an eligible candidate exists; one above does not. <!-- test: tests/test_lead_and_wild_switch.py -->
- [ ] `battle.py` skips potion and flee for a no-damage active member only when `switch_candidate` finds a healthy switch-in.
- [ ] The four existing test files above still pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, the new constants and their values. Then the check Claude runs afterwards with the ROM (Devin cannot): load a clean state with a Charmeleon, a Weedle and a wild-style Harden-only Kakuna in the party (a state is built from a seed with a patched species), run one headless explorer for a few hundred steps through a wild and a trainer fight, and read `decisions.jsonl` and `runs/battles.jsonl` to confirm the Kakuna no longer leads, a wild-fight switch fires when the lead is losing, and no member below the trainee-safety HP stays in.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The ROM check in the Report section, run by Claude after the verify lane passes. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-lead-and-wild-switch-directive |
| Base branch | - |
| Base commit | 74f62a26b91b5951ead6ea07757b9b07a96d1f82 |
| Head commit | fdd4ecce73b1ce3448ca4b410fdb4d6a0c83f7c6 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-14 14:26 · robert-claude-laptop · none → Queued
- 2026-11-14 14:26 · robert-claude-laptop · Queued → Approved
- 2026-11-14 14:27 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-lead-and-wild-switch-directive; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7DRF1XPF8WBN8DFSW01QJEY
- 2026-11-14 14:32 · dispatcher · launched pid=468; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-lead-and-wild-switch-directive; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (3 declared need(s), repo-scoped only))
- 2026-11-14 14:40 · devin · In progress → Review — Review. New constants: TRAINEE_SAFE_HP=0.35 (others unchanged). team_plan: can_damage + lead_order; switch_choice gains wild=True (thin = foe KOs inside SWITCH_HP_TURNS or our_dmg==0; weak-ratio stays trainer-only), incoming-survives check (best_move(foe,c)<ci), trainee-safety pull below 0.35 HP (skips the damage ask; never-the-trainee-IN and the 2/battle cap unchanged); next_swap takes optional want list. party_order.want_home uses lead_order when the moves table is loaded (ascending_order fallback). switch_out._matchup_pick now runs for kind 1 (wild) and 2 (trainer); None otherwise. battle.py: _active_no_damage + sw_out suppress potion/flee for a no-damage member only when magikarp.switch_candidate finds a healthy switch-in; stall_run/cave_run/train_fight/low_yield untouched. Diff stat vs origin/main (src/pokeagent): battle.py +27, party_order.py +17, switch_out.py +26, team_plan.py +59 - only those 4 files. Tests: `uv run --frozen pytest -q tests/test_lead_and_wild_switch.py` -> 11 passed; `uv run --frozen pytest -q tests/test_switch_matchup.py tests/test_party_order_ascending.py tests/test_trainee_gate.py tests/test_training_ctl_roster.py` -> 51 passed; also test_team_plan.py + test_train_fight.py + test_magikarp.py (45) and battle-step files (68) all green. DEVIATION flagged: tests/test_switch_matchup.py was edited - test_matchup_pick_never_in_a_wild_battle asserted the bug this directive fixes (kind==1 -> None); rewritten as test_matchup_pick_fires_in_a_wild_battle_too asserting the new contract. All other existing tests untouched. ROM check in the Report section is Claude's. [origin] spent: devin 8 min est. n/a
<!-- queue:end -->
