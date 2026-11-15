# PokeAgent: Training Controller and readiness edge cases - table-driven boundary tests over synthetic party fixtures, with any bug found reported, not silently fixed

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Depends on:** `Training_Controller_Slice5_Exit_Hold_Directive.md` (Review), merged first: it creates `src/pokeagent/explorer/training_ctl/exit_rule.py` <!-- new: src/pokeagent/explorer/training_ctl/exit_rule.py --> (the one writer and reader set for the gym-hold and floor flags). Check with `git ls-files src/pokeagent/explorer/training_ctl/exit_rule.py`. If it prints nothing, STOP and write "slice 5a not merged" in the Status row; do not recreate it and do not write the hold tests against the old ad-hoc flags. Slices 2 to 4 are already on main: `src/pokeagent/explorer/training_ctl/target.py`, `src/pokeagent/explorer/training_ctl/sustain.py`, `src/pokeagent/explorer/training_ctl/roster.py`. Slice 5a is in review, so the merged file wins over this directive's description of it; list each difference in the PR description. Base: current main containing slice 5a.

**Read first:** `docs/plans/training-controller-2026-11-13.md`, `docs/directives/Training_Controller_Slice5_Exit_Hold_Directive.md`, `docs/directives/Team_Readiness_Directive.md`, `src/pokeagent/knowledge/team_floor.py`, `src/pokeagent/knowledge/readiness.py`, `src/pokeagent/knowledge/team_plan.py`, `src/pokeagent/explorer/training.py`, `tests/test_team_floor.py`, `tests/test_team_plan.py`, `tests/test_training_ctl_roster.py`.

## Standing rule for synthetic data (Robert, 2026-11-07, verbatim)

"We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system."

Here: invented party fixtures test and drill the Training Controller's pure decisions at their boundaries. They never decide truth. A boundary that passes on a synthetic party is a claim that the live agent behaves the same; Claude confirms on a real save state (the Report names how). A fixture never becomes a checkpoint start, a KNOWLEDGE fact or a threshold change.

## 1. Why this exists

The Training Controller decides when the party is ready for a gym leader, which member to train, and when the gym stays shut. Its inputs are numbers that sit on knife edges: a level that is one under, at or one over a floor, a hold that is on or off, a member that is the trainee or absent. Real failures lived exactly on those edges:

- Seed 12, heal_cerulean to beat_misty, 12000 steps (2026-11-13): beat_misty was not reached with party L8-10 x5 + L25 against a floor of L19 for 2 members; the floor and the hold disagreed for thousands of steps (`docs/directives/Training_Controller_Slice5_Exit_Hold_Directive.md`).
- Misty 2026-11-12: a KAKUNA L4 bench member held a lead L25 outside the gym for 6,000 steps, because a member that could not take part in the fight was counted (`src/pokeagent/knowledge/readiness.py` docstring of `team_readiness`).
- The seed-12 check of slice 3 found `decisions.jsonl` drift when the timing of a hold flag changed by one step (`docs/directives/Training_Controller_Slice5_Exit_Hold_Directive.md`, "Slice 3's lesson").

The existing tests pin a few hand-picked cases each (`tests/test_team_floor.py`, `tests/test_team_readiness.py`, `tests/test_training_ctl_roster.py`). Nobody has swept the boundaries systematically: one level under, at and over each floor; the hold on and off with the stamp fresh, exactly stale and long stale; readiness yes and no against Brock and Misty; an empty party, a full party of six, a fainted lead, a trainee present and absent. This directive writes those sweeps as table-driven unit tests over the pure decision functions, so any boundary that is wrong shows up as one failing row with a name. It changes no behaviour: where a row fails, that is a finding.

## 2. Facts to build on (pasted; the worktree cannot be searched; `uv run python --version` prints `Python 3.12.12`)

```
# src/pokeagent/knowledge/party.py
@dataclass(frozen=True)
class Combatant:  name: str; level: int; types: tuple[str, ...]; hp: int   # hp is MAX hp
                  stats: tuple[int, int, int, int]; moves: tuple[str, ...]; dv: tuple = (); sexp: tuple = ()
def trainer_mon(name: str, level: int, kb: dict | None = None) -> Combatant | None
# src/pokeagent/knowledge/team_floor.py
TEAM_FLOOR_MEMBERS = 2
FLOOR_BY_GOAL = beat_brock 12, beat_misty 19, beat_surge 22, beat_erika 27, beat_koga 41, beat_sabrina 41, beat_blaine 45, beat_giovanni 48, beat_lorelei 54 (a module-level dict of goal name to level)
@dataclass(frozen=True)
class Floor: met: bool; level: int; need: int; have: int; target_slot: int | None; text: str   # text is "" when met
def sendable_slots(party, boss, kb=None) -> list[int]      # non-Magikarp members with a damaging move that hurts at least one boss mon
def check(goal: str, party, boss, kb=None) -> Floor | None  # None: goal has no floor, party or boss empty, or nobody sendable
def ready(nv, floor: Floor | None) -> bool                  # whole-party sim passes AND floor met (floor None: the sim alone)
#   need = min(TEAM_FLOOR_MEMBERS, len(sendable)); have = sendable members with level >= floor level
#   target_slot = the sendable member CLOSEST BELOW the floor (highest level below it, ties lowest slot); text "team floor for beat_misty: need 2 members >= L19, have 1"
# src/pokeagent/knowledge/readiness.py
MARGIN = 0.30; TEAM_GAP = 6; LEAD_HURT = 0.5; TEAM_MIN = 2
@dataclass(frozen=True)
class MemberNeed: slot: int; name: str; level: int; target: int; useful: bool; flips: bool = True
@dataclass(frozen=True)
class TeamReadiness: ready: bool; lead: Readiness | None; members: tuple[MemberNeed, ...]; weakest: MemberNeed | None; text: str
def team_readiness(party: list[Combatant], boss: list[tuple[int, str]], label: str, kb: dict | None = None) -> TeamReadiness | None
#   None: empty party or boss, unknown species, no move table, or only Magikarp. ready needs the lead verdict AND the hurt-lead sim AND TEAM_MIN members (a one-mon party is not ready, weakest None, text says "no second member").
# src/pokeagent/knowledge/team_plan.py
BAND_BELOW = 4
def boss_need(team, boss, kb, label: str = "BOSS") -> Need | None     # Need: ready, team_score, lead_slot, level_by_slot, raise_slot, raise_level, need, weak_slots, text
def level_band(team, need: int) -> dict                                 # slot -> (lo, hi): the strongest member at need, every other within BAND_BELOW of it
def band_breakers(team, band) -> tuple                                  # slots whose level is under their band's lo
def ascending_order(levels, fainted) -> list[int]                       # lowest level first, fainted last, stable
def next_swap(levels, fainted) -> tuple[int, int] | None
def trainee_slot(party, named=None, breakers=(), wild=None, kb=None) -> int | None
#   rule order: a WEEDLE-line member short of the level it evolves and not the strongest wins (lowest level first); else `named` when a non-lead member at least TEAM_GAP under the strongest member's level; else the lowest-level band breaker that survives the wild mon (no wild data: the lowest breaker); else None. MAGIKARP never answers here.
# src/pokeagent/explorer/training.py
def train_member_for(nv, team, floor=None) -> int | None
#   nv not ready: nv.raise_slot, else nv.lead_slot; else floor unmet with a target: floor.target_slot; else team.weakest.slot or None
# src/pokeagent/explorer/training_ctl/roster.py
def trainee_slot(ctx, *, breakers: bool = False) -> int | None   # ctx needs .emu, .train_member (and a team_plan.of(ctx) state for breakers); Magikarp slot wins upstream
def note_faints(ctx) -> int          # monotonic faint counter per ctx.step; rises when members at hp 0 rise, never falls on a heal
# src/pokeagent/explorer/training_ctl/target.py
def wants_training(ctx) -> bool      # a grind episode is live, or 0 < (ctx.gate_lvl or lead_level(emu)) < ctx.train_need
# src/pokeagent/explorer/behaviours/goal_talk.py
HOLD_FRESH = 30                      # steps a readiness verdict stays good
# src/pokeagent/explorer/training_ctl/exit_rule.py (slice 5a; confirm against the merged file)
def publish_hold(ctx, held: bool) -> None     # ctx.gym_hold_seen = (ctx.step, bool(held))
def publish_floor(ctx, unmet: bool) -> None   # ctx.__dict__["floor_unmet"] = bool(unmet)
def floor_unmet(ctx) -> bool
def hold_clear(ctx, fresh: int) -> bool       # a stamp exists, its flag is False, and ctx.step - stamp step <= fresh
def floor_hold(ctx) -> bool                   # floor_unmet(ctx) and the stamped hold flag (False when never stamped)
```
Test helpers that already exist (import them the way `tests/test_team_floor.py` and `tests/test_training_ctl_roster.py` do, as sibling test modules): `from test_team_plan import SYN, _mon` (a synthetic knowledge base and a `Combatant` builder by species name and level) and `from test_magikarp import party_mem` (a FakeEmulator memory dict for a party given as tuples of species id, level, hp and max HP), with `from pokeagent.emulator import FakeEmulator`. Read the top of `tests/test_team_plan.py` first for the species `SYN` holds. `tests/test_team_floor.py` assigns `team_floor.FLOOR_BY_GOAL["beat_misty"]` directly, which leaks into later tests: in the NEW tests use `monkeypatch.setitem` so nothing leaks.

Boss fixtures: the gym leaders' ace levels in the repo comments are Brock Onix 14 and Misty Starmie 21; the floors are 12 and 19. Use invented species names and numbers in your fixture knowledge base (copy `SYN`, never mutate it, add invented rows where a species is missing); do not paste any real cartridge data. A Brock-like boss is a list of (level, species) pairs ending at level 14, a Misty-like boss ends at level 21.

## 3. Scope (in this order)

1. `tests/training_edge_kb.py` <!-- new: tests/training_edge_kb.py --> - fixture support: a copy of `SYN` extended with invented rows so there are a Brock-like and a Misty-like boss, a party builder from compact tuples (species, level, fainted flag), and the boss lists. Test support only; under 120 lines.
2. `tests/test_training_edge_floor.py` <!-- new: tests/test_training_edge_floor.py --> - table-driven boundaries of `team_floor.check` and `team_floor.ready`, and of `training.train_member_for`.
3. `tests/test_training_edge_readiness.py` <!-- new: tests/test_training_edge_readiness.py --> - readiness yes and no against the Brock-like and Misty-like bosses: `readiness.team_readiness` and `team_plan.boss_need`, with party size and fainted-lead boundaries.
4. `tests/test_training_edge_roster.py` <!-- new: tests/test_training_edge_roster.py --> - the trainee: `team_plan.trainee_slot`, `roster.trainee_slot`, `roster.note_faints`, `team_plan.ascending_order` and `team_plan.level_band` with `team_plan.band_breakers`, and `target.wants_training`.
5. `tests/test_training_edge_hold.py` <!-- new: tests/test_training_edge_hold.py --> - the gym-hold and floor flags through `exit_rule`, plus `training.gate_state`.
6. `docs/KNOWLEDGE.md` - two sentences: where the edge-case tables live and the rule "a failing boundary row is a finding; a fix is its own named change".

Nothing under `src/pokeagent/` is edited. No existing test is edited.

## 4. The work

Every test is a `pytest.mark.parametrize` table with an `ids=` list, so a failing row names its case. Rows are plain tuples (invented parties and expected values written in the test); NEVER put a dict literal in backticks in prose or in the directive-style comments (the dispatch preflight reads inline dicts as commands). Each table has a comment stating the rule under test in one line. The party builder takes compact tuples so a row reads like `[("RATTATA", 11), ("PIDGEY", 12, "fainted")]`.

### 4.1 Floor boundaries (`tests/test_training_edge_floor.py`)

For each floor goal in a small set (beat_brock at 12, beat_misty at 19, patched with `monkeypatch.setitem` to the real values so the test states them), with `TEAM_FLOOR_MEMBERS` 2 and sendable members only:
- Level boundaries per member: one under (floor minus 1), at (floor), one over (floor plus 1). The table is the cross product for a two-sendable-member party: (under, under), (under, at), (at, at), (at, over), (over, over), (under, over). Expected `Floor.met`, `have`, `need`, `target_slot` and the exact `text` (empty when met).
- `target_slot` is the sendable member CLOSEST below the floor: rows with two below-floor members at different levels (and equal levels: ties go to the lowest slot), and a row where the only below-floor member is not sendable (cannot damage the boss) so it must NOT be the target and must not count toward `have`.
- Party size: an empty party gives None; a one-sendable-member party has `need` 1 (capped at the sendable count: not held on a floor nothing can fix); a full party of six with exactly two at the floor is met, with exactly one it is not; a Magikarp member never counts toward `have` or as `target_slot`.
- A goal with no floor (for example `to_mt_moon`) gives None; an empty boss gives None.
- `team_floor.ready(nv, floor)` truth table over (sim ready yes or no) by (floor met, unmet, None): four meaningful rows plus the None row, using small stub objects exposing `ready`.
- `training.train_member_for(nv, team, floor)` rows: nv not ready with a `raise_slot` returns it; nv not ready with `raise_slot` None returns `lead_slot`; nv ready, floor unmet with a target returns `target_slot`; nv ready, floor unmet with target None falls through to `team.weakest.slot`; everything ready and `weakest` None returns None. Use `types.SimpleNamespace` stubs for nv, team and floor.

### 4.2 Readiness against Brock and Misty (`tests/test_training_edge_readiness.py`)

- For the Brock-like and the Misty-like boss and a strong and a weak fixture party each (four rows minimum), expected `boss_need(...).ready` and `team_readiness(...).ready` as the fixtures are built to give (build the strong party so the sim passes with margin and the weak party so it clearly fails; assert the values you built them for, and put a comment on each row saying why it passes or fails).
- Boundary of the lead level: a lead one level under, at and one over the level at which the fixture first wins (find the crossing by a loop in a helper at test time, not a magic number, then assert the verdict flips exactly there: ready False at the level below, True at the crossing level). This pins that `assess`'s `required` level is consistent with `ready`.
- Party size: an empty party gives None for both; a one-member party is NOT ready from `team_readiness` and has `weakest` None and the text mentions no second member; a two-member party is the smallest that can be ready; a full party of six works and `members` has six rows in slot order.
- Fainted lead: the strongest member at 0 HP. `team_readiness` and `boss_need` take Combatants (max HP), so a faint is not in their input: assert what that means by calling them with the fainted member REMOVED from the party and with it present, and record the behaviour in a comment; the point is to show where a fainted lead is (not) accounted for, as a finding if the live path would pass a fainted member (read `src/pokeagent/explorer/training.py` `team_for` and `boss_need_for` to see what party they are given; do not guess).
- Magikarp: a party whose only non-Magikarp member count is 0 gives None; a Magikarp below `EVOLVE_LEVEL` fights as itself, at or above it as the Gyarados it becomes (the boundary level comes from `pokeagent.magikarp.EVOLVE_LEVEL`; import it, do not hard-code it).
- A bench member that cannot take part in the fight must not block a ready lead (the Misty 2026-11-12 case): a row with a weak damaging-less bench member and a strong lead is ready.

### 4.3 Trainee, order and band (`tests/test_training_edge_roster.py`)

- `team_plan.trainee_slot(party, named, breakers, wild, kb)` rows: trainee absent (empty party gives None; a party where nobody is named and there are no breakers gives None); `named` one level under the TEAM_GAP boundary (lead level minus 5, not chosen), exactly at it (lead minus 6, chosen) and one over (lead minus 7, chosen); `named` equal to the strongest member's own slot is never chosen (at least TEAM_GAP under the strongest means the strongest never qualifies); `named` out of range (-1, party length) gives None, not an exception; a breaker rule row with `wild` given where the lowest breaker cannot survive the hit (falls through to the next breaker, then None) and a row with no wild data (lowest breaker leads); the Weedle-line rule: a WEEDLE-line member one level under the evolve level is the trainee, at the evolve level it is not, and when it is the strongest member it is not. Read `team_plan.py` lines 174 to 218 first for the exact evolve-level source and use that constant by name.
- Full party (six members) and one-member party for each of the above.
- `roster.trainee_slot(ctx)` with `FakeEmulator(party_mem([...]))`: a Magikarp in the party wins whatever `train_member` says; trainee absent; trainee present as the named weak member; a fainted lead (hp 0 on the strongest slot) with a named weak member; an empty party. Copy the ctx style from `tests/test_training_ctl_roster.py` (`SimpleNamespace` with `emu`, `train_member`, `step`).
- `roster.note_faints(ctx)`: a heal never lowers the counter; a faint adds one; two faints in one step add two; the second call in the SAME step returns the stored value even when the party changed in between (the stamp-per-step rule); a new context starts at 0; the documented blind spot (a revive and a new faint inside one step cancel) is a row that asserts the documented behaviour.
- `team_plan.ascending_order`/`next_swap`: fainted lead (the strongest first slot fainted moves to the end), all fainted (order stays stable), ties keep slot order, one member, empty lists, and `next_swap` is None exactly when the party already stands in order.
- `level_band` and `band_breakers`: a member at `lo` minus 1 (breaker), at `lo` (not), at `lo` plus 1 (not), with `need` at the strongest member's level and below it; an empty team gives an empty band and no breakers; `BAND_BELOW` is used by name.
- `target.wants_training(ctx)`: lead level one under, at and one over `ctx.train_need`; lead level 0 (empty party: never wants training); a live grind episode stamped in the context's grind state wants training regardless of levels. Set `ctx.gate_lvl` explicitly (the function prefers it over reading the emulator) so no RAM read is needed; read `src/pokeagent/explorer/training_ctl/target.py` for the exact attribute names.

### 4.4 Gym hold and floor flags (`tests/test_training_edge_hold.py`)

- Using `exit_rule` on `SimpleNamespace` contexts: `publish_hold` then `hold_clear` over a table of (held flag True or False) by (age 0, `HOLD_FRESH` minus 1, `HOLD_FRESH`, `HOLD_FRESH` plus 1, a very large age) by (stamp present, never stamped): expected `hold_clear` is True only for a stamped False flag whose age is at most `HOLD_FRESH`. Import `HOLD_FRESH` from `pokeagent.explorer.behaviours.goal_talk` by name.
- `floor_hold` over (floor unmet True, False) by (hold stamped True, stamped False, never stamped): True only for unmet and stamped True.
- `publish_floor` coerces to bool and `floor_unmet` of a context that never published is False.
- The plan's invariant, pinned on the pure side: the floor holds without a ledger. With the floor unmet and an empty or absent grind ledger, `floor_hold` is True whenever the hold is stamped True, and no function in this file's scope releases the hold because the ledger is empty. (Slice 5a's own test file `tests/test_training_ctl_exit.py` pins the full plan-goal behaviour; do not duplicate it, do not import its helpers, and do not edit that file.)
- `training.gate_state(ctx, goals, party, nv, team)`: with `training.floor_for` patched through `monkeypatch` to return a stub Floor (met True, met False, None), assert it publishes `floor_unmet` (True only for a stub with met False), returns `(train_member, gate_ready)` consistent with `train_member_for` and `team_floor.ready`, and logs the failing reason once per change (a second identical call logs nothing; a changed text logs again; a met floor resets so a later identical failure logs afresh). Use a ctx stub with `log` collecting calls and `floor_note`.

### 4.5 Findings, not silent fixes

If any row fails, decide which it is before touching anything:
1. A WRONG EXPECTATION in the row (you misread the rule): fix the row after re-reading the code.
2. A REAL BOUNDARY BUG in the code under test: do NOT fix it here. Keep the row, mark it `pytest.mark.xfail(strict=True, reason="BOUNDARY BUG: <one line>")`, keep the other rows of that table passing, and write the finding in the Report with the function, the input row, the expected value, the actual value and the file and line. A bug fix is its own small, named change with its own test, opened by Claude from your Report; it is never folded into this branch, and no file under `src/pokeagent/` may change in this directive (the diff check in section 5 enforces it).
3. A behaviour that is DOCUMENTED but surprising (for example a blind spot the docstring accepts): assert the documented behaviour and mention it under "Surprises" in the Report.

## 5. Verification (exact commands)

```
uv run --frozen pytest -q tests/test_training_edge_floor.py tests/test_training_edge_readiness.py tests/test_training_edge_roster.py tests/test_training_edge_hold.py
```
Expected: all pass, except one strict xfail per genuine boundary bug found (listed in the Report).

```
uv run --frozen pytest -q tests/test_training_ctl_roster.py tests/test_training_ctl_target.py tests/test_training_ctl_sustain.py tests/test_training_ctl_shadow.py tests/test_team_floor.py tests/test_team_readiness.py
```
Expected: no new failures (existing controller and readiness tests, unchanged). Claude ran this exact command on main while writing the directive; the tail was `77 passed, 1 warning`. After slice 5a merges, also run `tests/test_training_ctl_exit.py` and paste its tail.

```
git diff --stat origin/main -- src/pokeagent tools
```
Expected: EMPTY. Only files under `tests/` and `docs/KNOWLEDGE.md` change.

## 6. Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command. Never bare `python`.
- Branch only (`directive/pokeagent-training-readiness-edge-cases-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.
- Synthetic data may train, test and drill but never decides truth: never scored on (evaluation is always organic held-out data), never a checkpoint start, chain best, KNOWLEDGE fact or shared-memory veto without organic confirmation. Every synthetic record carries a provenance tag (here: every fixture builder names itself synthetic in its docstring, and every table row has an id). Reports show organic versus synthetic side by side (here: the Report separates "synthetic boundary rows" from "behaviour confirmed on a real save state", and the second list starts empty). The synthetic share of any training mix is capped by a config constant (not applicable: nothing here trains). ROM-derived data stays local and gitignored, never published; the fixtures here are invented. Never state where a game copy came from.
- Tests never open a window.

## 7. Completion criteria

- [ ] Floor boundaries: under, at and over for each member pairing, the closest-below target rule (including ties and a non-sendable below-floor member), empty, one-sendable and full parties, the Magikarp exclusion, no-floor and empty-boss goals, the `ready` truth table and every `train_member_for` branch. <!-- test: tests/test_training_edge_floor.py -->
- [ ] Readiness against a Brock-like and a Misty-like boss: yes and no rows, the lead-level crossing where the verdict flips, empty, one-member, two-member and full parties, a fainted lead handled as a recorded finding or surprise, Magikarp at the evolve boundary, and the useless-bench-member case. <!-- test: tests/test_training_edge_readiness.py -->
- [ ] Trainee, order and band: `trainee_slot` at the `TEAM_GAP` boundary and the other rules, `roster.trainee_slot` with trainee present, absent, a Magikarp, a fainted lead and an empty party, `note_faints` rows, `ascending_order` and `next_swap` edges, `level_band` and `band_breakers` boundaries, and `wants_training` at the `train_need` boundary. <!-- test: tests/test_training_edge_roster.py -->
- [ ] Hold flags: `hold_clear` across the `HOLD_FRESH` age boundary and stamped or never-stamped, `floor_hold` truth table, bool coercion, the floor-holds-without-a-ledger invariant on the pure side, and `gate_state` publishing and logging once per change. <!-- test: tests/test_training_edge_hold.py -->
- [ ] Every table row has an id; no test uses an inline dict in a backticked directive-style comment; no test opens a window, reads a ROM, a real `runs/` or a save state; `FLOOR_BY_GOAL` is patched with `monkeypatch.setitem`, never assigned.
- [ ] `git diff --stat origin/main -- src/pokeagent tools` is empty; every genuine bug is a strict xfail row plus a Report finding, none is fixed here.
- [ ] The existing test files in section 5 pass unchanged.
- [ ] Status row set to `Review` with the evidence above.

## 8. Report

Diff stat (tests and docs only), test tails (including `tests/test_training_ctl_exit.py` once slice 5a is merged), each difference between this directive's description of slice 5a and the merged file, then three lists: "Findings" (each boundary bug: function, input row, expected, actual, file and line, and a suggested name for the fix change, or "none"), "Surprises" (documented behaviours asserted as they are), and "Confirmed on a real save state" (empty: Claude fills it by replaying two of the boundary rows, a party one level under the Brock floor and a fainted lead, against a real checkpoint with the ROM, which Devin cannot do).

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The real-save-state confirmation in the Report, run by Claude. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
