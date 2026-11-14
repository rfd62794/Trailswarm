# PokeAgent: Training Controller slice 3 (Sustain) - tick is the sole writer of train_route_live; the heal rule lives in one place; step_budget gets the bench-xp and walk-to-grass rows

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/training-controller-2026-11-13.md` (sections 2, 3, 4 item 3, 5 including "Slice 2 result (2026-11-14)", 6). Slices 1 (shadow) and 2 (Target, #250) are merged: `src/pokeagent/explorer/training_ctl/{state,controller,adapters,target}.py`. Base: main at `19fce6c` (#253) or later.

## 1. Why this exists

Seed 12 baseline (heal_cerulean -> beat_misty, 12000 steps): heal trips 7.5% of steps + leave-Pokecenter 5.4%, SHAKE 7.2%, and three owners of "train / heal" (plan_goal, grind_heal, retreat_heal, frontier, the planner). Slice 2 removed the phantom episodes. Real-ROM A/B of slice 2, seeds 12/13/14, 12000 steps, before = main, after = slice 2:

- phantom episode starts 12/11/11 -> 0; leave-Pokecenter 1.9/4.5/7.0% -> 0.9/0.7/0.9%; SHAKE 5.6/8.3/8.4% -> 4.6/5.5/1.3%;
- `route24_xp_per_1k` 199/216/290 -> 180/197/176, which is a METRIC ARTIFACT: `tools/step_budget.py:112` reads `xp_rates.jsonl` map_summary `xp_per_1k_steps` for map 35, computed in `xp_meter.py` over per-party-member window steps, not run steps, so a different time mix moves it. Total xp over all maps was -6%/+3%/+13% (flat-to-up), per-battle xp 111->123, 88->88, 106->120, non-lead party levels flat. The plan's acceptance bar is replaced by bench xp per 1k run steps (this slice builds that row).
- Two cheap wastes seen: every episode now starts ~56 steps from the grass (`goal team_ready: 56 steps to Route 24's grass` in console.log), and one seed-13 episode ended `hurt with no potion` for 81 xp in 759 steps.

This slice makes `tick` the only writer of `train_route_live`, gives the heal rule one owner (`training_ctl/sustain.py`, `heal_now`), and fixes the measuring stick so the real-ROM A/B (Claude's, after merge) can judge it.

## 2. Scope (files, in order)

1. NEW `src/pokeagent/explorer/training_ctl/sustain.py` (< 120 lines) + NEW `tests/test_training_ctl_sustain.py`. Absorbs `explorer/grind_heal.py` and `explorer/after_heal.py`. Do NOT delete them (file deletion is refused in this sandbox and stops the run): leave both files in place, unchanged, with no remaining importer in `src/`; Claude deletes them during review. `sustain.py` is already on this branch (commit 002d4f3): continue from it.
2. `src/pokeagent/explorer/training_ctl/controller.py`: add `tick`. `src/pokeagent/explorer/training_ctl/adapters.py`: add `team_ready_live`. `src/pokeagent/explorer/engine.py`: call `tick` before `selector.choose`.
3. `src/pokeagent/explorer/behaviours/grind_loop.py`: `mark_live` stops writing the flag. `src/pokeagent/explorer/behaviours/plan_goal.py`: the removals below (net <= 0).
4. `src/pokeagent/explorer/behaviours/retreat_heal.py`, `src/pokeagent/explorer/behaviours/frontier.py`: read `heal_now`.
5. `src/pokeagent/explorer/grind_episode.py`: `_end_reason` uses `sustain.hurt_no_potion`.
6. `tools/step_budget.py` + `tests/test_step_budget.py`: bench-xp row, 2nd-member-L9 row, walk-to-grass rows.
7. Test adaptations (named in section 3 step 7): `tests/test_training_v2_slice3.py`, `tests/test_training_v2_slice2.py`, `tests/test_grind_pressure_plan_goal.py`.

Not in scope: `planner.py`, `planner_east.py` (they keep reading `_hp`, `_survives`, `_push_on` from the goals dict; only the producer of those keys moves).

## 3. The work

### Current code (verified on 19fce6c; line numbers are current, the plan's older ones drifted)

`behaviours/plan_goal.py` (exactly 300 lines, the cap; net must be <= 0):
```python
:6   from pokeagent.bandit.hook import heal_push_on, train_need
:16  from pokeagent.explorer import after_heal, party_log, area_grind, grind_episode, magikarp_deferral, par_follow, retalk_memory, train_route
:125 planned = plan_step({**goals_now_all, "_starter": ctx.opts.starter, "_blocked_now": frozenset(ctx.mem.temp_blocked), "_talk_vetoed": retalk_memory.active(ctx), "_declined": set(ctx.declined_balls), "_hp": heal_gate_hp(ctx.emu), "_survives": party_survives(ctx.emu, ctx.view.m), "_push_on": heal_push_on(ctx, goals_now_all, *heal_gate_hp(ctx.emu)), "_parcel_spot": parcel,
:126                      "_level": lead, ...
:129                     ctx.mem.data["maps"], (m, x, y), ctx.facing)
:130 ctx.train_route_live = bool(team_ready_stage and training_live)
:131 if (planned is None or after_heal.leaving(planned, m)) and team_ready_stage and training_live:
:132     planned = train_route.step(ctx.mem.data["maps"], (m, x, y), ctx.mem.temp_blocked, *heal_gate_hp(ctx.emu),
:133                                  survives=party_survives(ctx.emu, ctx.view.m), heading=getattr(ctx, "facing", None)) or planned  # to the grass; keep the planner's exit press if no route yet
...
:233 def _grind_step(ctx, m, x, y, hp, mx):   # staticmethod
:242     return grind_loop.mark_live(ctx, train_route.step(ctx.mem.data["maps"], (m, x, y), ctx.mem.temp_blocked, hp, mx, survives=party_survives(ctx.emu, ctx.view.m), heading=getattr(ctx, "facing", None), **kw))
```
(`training_live = 0 < lead < need` is :120 and `team_ready_stage` is set earlier in `step`; both stay. `party_survives` and `train_route` stay imported: `_grind_step` :242 uses them. `heal_gate_hp` stays imported: :125 and the `_grind_step` calls use it.)

`behaviours/grind_loop.py:26-33` (the second writer today):
```python
def mark_live(ctx, planned):
    """Pass a train_route step through, flagging the run as training. ..."""
    if planned is not None:
        ctx.train_route_live = True
    return planned
```
Readers of `ctx.train_route_live` (do not change them): `behaviours/frontier.py:155` (`train_route.stay_on_route(m, ctx.train_route_live, ep, ...)`), `behaviours/grind_loop.py:39` (`paced_in_training`), `grind_heal.py:22`, `train_target.py:29`, `training_ctl/adapters.py:20`. Field: `explorer/context.py:124` (`train_route_live: bool = False`; STAYS, context.py must not change).

`grind_heal.py` (36 lines, moves into `sustain.py` unchanged in behaviour):
```python
from pokeagent.explorer.perceive import party_needs_heal
from pokeagent.explorer.retreat_risk import PARTY_FLOOR, party_survives
from pokeagent.party_view import read_party_view

def grinding(ctx) -> bool:
    return bool(ctx.train_route_live) or bool((ctx.__dict__.get("_grind_state") or {}).get("episode"))

def needs_heal(ctx, fraction: float) -> bool:
    if not grinding(ctx):
        return party_needs_heal(ctx.emu, fraction)
    # PARTY_FLOOR backstop: party_survives may fall back to a bare 15% fighter test with no KB (review of 84e8023)
    return party_needs_heal(ctx.emu, PARTY_FLOOR) or not party_survives(ctx.emu, ctx.view.m)

def potion_instead(ctx) -> bool:
    from pokeagent.explorer.behaviours.cave_topup import wants_topup
    return grinding(ctx) and not read_party_view(ctx.emu).any_fainted and wants_topup(ctx)
```
`after_heal.py` (15 lines): `from pokeagent.explorer.world import POKECENTER_MAPS` and
```python
def leaving(planned, m: int) -> bool:
    """True for the planner's plain walk-out press inside a Pokecenter (not the nurse, PC or a purchase)."""
    return m in POKECENTER_MAPS and planned is not None and "leaving the Pokecenter" in planned[1]
```
`behaviours/retreat_heal.py`:
```python
:9   from pokeagent.explorer import grind_heal, heal_walk
:40  def _hurt(ctx, party):   # staticmethod
:47      if grind_heal.grinding(ctx):   # grinding: the survival floor decides, not LEAD_GATE / PARTY_GATE (grind_heal)
:48          if not grind_heal.needs_heal(ctx, 0.0):
:49              return False
:50      elif lead >= LEAD_GATE and sum(p.hp for p in party) / mx >= PARTY_GATE:
:51          return False
...
:71  if grind_heal.potion_instead(ctx):
:72      return None   # a Potion beats the walk (outside_use.field_wants): CaveTopUp drinks it, no Pokecenter trip
```
`behaviours/frontier.py`:
```python
:6   from pokeagent.explorer import grind_episode, grind_heal, train_route
:149 weak = grind_heal.needs_heal(ctx, 0.4)  # while grinding: the survival floor, not a fixed 40%
```
`explorer/engine.py`:
```python
:43  self._training = TrainingController()  # slice 1: shadow owner of the training flags (never writes)
:50  decision = self.selector.choose(ctx)
:51  self._training.observe(ctx)  # shadow check of the training flags plan_goal just set
```
`training_ctl/controller.py` has `class TrainingController` with `__init__` (`self.mismatches`, `self._last_logged`) and `observe(ctx) -> TrainingState | None` (never raises); module has `log = logging.getLogger(__name__)`, `RATE_STEPS = 500`. `training_ctl/adapters.py` has `old_flags(ctx)` and `derived(ctx)`; `derived` already computes `team_ready = next((g for g in GOALS if not goals.get(g)), None) == "team_ready"` and `level = trainee_band_level(ctx.emu) if team_ready else lead_level(ctx.emu)`.

`grind_episode.py:232-234` (inside `_end_reason`, imports `heal_items`, `bag_contents`, `party_survives`, `read_party_view`, `party_hp` at top):
```python
hp, mx = party_hp(ctx.emu)
if (mx and not party_survives(ctx.emu, ctx.view.m) or read_party_view(ctx.emu).any_fainted) \
        and not heal_items.heal_count(bag_contents(ctx.emu)):
    return "hurt with no potion"
```
`_try_start` (:175-212) already runs `_end_reason` on the would-be episode first, so an episode NEVER starts hurt-with-no-potion today (it logs `not starting (...): would end at once (hurt with no potion)`). The seed-13 episode that lost 759 steps started healthy and was hurt later; so this item is a pin + dedupe, not a new gate (see step 6).

`tools/step_budget.py` (142 lines): `run_rows(run_dir)` (:102) returns the dict of rows (`reorder_sessions`, `reorder_lines`, `reorder_in_pokecenter`, `episode_starts`, `blackouts`, `route24_xp_per_1k`, `floor_first_step`); helpers `_jsonl(path)`, `floor_progress(levels)`, `episode_starts(console)`; constants `EPISODE_RE = re.compile(r"\[grind episode\] start on (\S+)")`, `STEP_RE = re.compile(r"^--- step (\d+)/\d+\s+map=0x([0-9a-fA-F]+)")`; `ACTIVITIES` has `("walking to grass (goal team_ready)", r"goal team_ready: \d+ steps to .* grass")`; `budget(path)` walks console.log, counting `--- step` headers and `thinking:` lines. `levels.jsonl` row shape (party_log `_write`): `{"step", "frame", "map", "cause", "party": [[species, level, exp, hp, max_hp], ...] (slot order, may reorder), ...}`; `blackouts` appears only on some rows. `bench_xp` has NO row today (`git grep bench tools/step_budget.py` is empty).

### Steps

**Step 1: `training_ctl/sustain.py`.** One frozen dataclass and pure-ish functions (no ctx writes):
```python
@dataclass(frozen=True)
class Sustain:
    grinding: bool      # grind_heal.grinding
    floor_heal: bool    # needs_heal(ctx, 0.0): the survival-floor verdict while grinding
    weak: bool          # needs_heal(ctx, 0.4): frontier's "leave the grass" verdict
    use_potion: bool    # potion_instead
    survives: bool      # party_survives (the planner's _survives)
    push_on: bool       # bandit heal_push_on; False when goals is None
    @property
    def go(self) -> bool: return self.floor_heal and not self.use_potion      # a Pokecenter trip is wanted
    def goal_keys(self) -> dict: return {"_survives": self.survives, "_push_on": self.push_on}
    why: str            # short text for logs: "grinding+floor", "potion", "ok"

def heal_now(ctx, goals: dict | None = None) -> Sustain
```
Move `grinding`, `needs_heal`, `potion_instead` here with identical logic (same imports: `party_needs_heal`, `PARTY_FLOOR`, `party_survives`, `read_party_view`; keep the lazy `cave_topup.wants_topup` import inside `potion_instead`). `heal_now` calls `heal_push_on(ctx, goals, *heal_gate_hp(ctx.emu))` (import `from pokeagent.bandit.hook import heal_push_on`; `heal_gate_hp` from `pokeagent.explorer.perceive`) ONLY when `goals is not None`, else `push_on=False`. It is a QUERY: no memo, no ctx write (so the bandit's `decide`/`clear` side effects run exactly where they run today: once per plan_goal step). Also move `leaving(planned, m)` here and add `to_grass(ctx, planned, pos, live)`:
```python
def to_grass(ctx, planned, pos, live: bool):
    """plan_goal's old :131-133 branch: while the trainee stage trains, take the straight walk to the grass when the planner has no step
    or only its 'leaving the Pokecenter' press. Returns planned unchanged when not live."""
    if live and (planned is None or leaving(planned, pos[0])):
        return train_route.step(ctx.mem.data["maps"], pos, ctx.mem.temp_blocked, *heal_gate_hp(ctx.emu),
                                survives=party_survives(ctx.emu, ctx.view.m), heading=getattr(ctx, "facing", None)) or planned
    return planned
```
Also add `hurt_no_potion(ctx) -> bool` = the exact boolean of `grind_episode.py:232-234` (`(mx and not party_survives(...) or any_fainted) and not heal_items.heal_count(bag_contents(ctx.emu))`, where `hp, mx = party_hp(ctx.emu)`; imports `heal_items` from `pokeagent.explorer.economy`, `bag_contents` from `pokeagent.goals`). `sustain.py` must NOT import `grind_episode` (it reads the `_grind_state` dict, as `grind_heal` does). Then `git rm` `explorer/grind_heal.py` and `explorer/after_heal.py`.

**Step 2: tick.** `adapters.team_ready_live(ctx) -> bool`: `team_ready` (same expression as in `derived`) and `0 < trainee_band_level(ctx.emu) < (ctx.train_need or 0)`; cheap (no `our_party`, no `boss_need_for`). `TrainingController.tick(ctx)`:
```python
def tick(self, ctx) -> None:   # the SOLE writer of ctx.train_route_live; called once per step BEFORE selector.choose
    try:
        stamp = ctx.__dict__.get("grind_walk_step")
        walked = stamp is not None and ctx.step - stamp <= 1          # plan_goal's _grind_step produced a grass walk last step
        ctx.train_route_live = bool(adapters.team_ready_live(ctx) or walked)
    except Exception as e:   # noqa: BLE001  rate-limited like observe; on failure the flag keeps its last value
        ...
```
(use the same `_last_logged` / `RATE_STEPS` rate limit; key `"tick_failed"`.) `engine.py`: add `self._training.tick(ctx)` immediately BEFORE `decision = self.selector.choose(ctx)` (:50); keep `observe` at :51 and fix its comment (it no longer checks "the flags plan_goal just set" for `train_route_live`). `ctx.view` must be valid at that point; the engine test fixtures must show it (if `tick` hits an unrefreshed ctx it just logs and keeps the flag).

**Documented timing change (put it in the Report; do not "fix" it):** before, the flag was set inside plan_goal in the same step (`:130`, and `mark_live` for the gym-hold / grind-latch walk); now it is computed at the start of the step from the previous step's `train_need` and a one-step-old stamp. The plan's risk 2 (moving the writer before behaviours changes flag timing) is exactly this.

**Step 3: grind_loop + plan_goal.**
- `grind_loop.mark_live`: replace `ctx.train_route_live = True` with `ctx.__dict__["grind_walk_step"] = ctx.step` (keep the docstring's history, add one sentence: tick turns the stamp into the flag). Keep returning `planned`.
- plan_goal: (a) DELETE :130. (b) Replace :131-133 (3 lines) with ONE line: `planned = sustain.to_grass(ctx, planned, (m, x, y), bool(team_ready_stage and training_live))`. (c) On :125 replace `"_survives": party_survives(ctx.emu, ctx.view.m), "_push_on": heal_push_on(ctx, goals_now_all, *heal_gate_hp(ctx.emu)),` with `**sustain.heal_now(ctx, goals_now_all).goal_keys(),` (keep `"_hp": heal_gate_hp(ctx.emu)` and every other key, same line). (d) :6 becomes `from pokeagent.bandit.hook import train_need`; :16 drops `after_heal, `; add ONE new import line `from pokeagent.explorer.training_ctl import sustain` (if that makes the file 301 lines, merge it into an existing import line instead). Required: `wc -l` of plan_goal.py <= 300 and `git diff --stat` net <= 0 (expected about -2). `context.py` and `memory.py` must not appear in the diff.

**Step 4: retreat_heal and frontier.** `retreat_heal.py`: import `from pokeagent.explorer.training_ctl import sustain` (drop `grind_heal` from :9); in `_hurt` compute `h = sustain.heal_now(ctx)` once and use `h.grinding` / `sustain.needs_heal(ctx, 0.0)` -> `h.floor_heal` (:47-49); at :71 `if sustain.heal_now(ctx).use_potion:`. `frontier.py`: drop `grind_heal` from :6, `weak = sustain.heal_now(ctx).weak` at :149. Behaviour identical (the same functions, same order).

**Step 5: grind_episode `_end_reason`.** Replace :232-234 (the `party_hp` line stays only if still used below it; check) with `if sustain.hurt_no_potion(ctx): return "hurt with no potion"`; add the import `from pokeagent.explorer.training_ctl import sustain` and drop imports that become unused (`heal_items`, `bag_contents`, `read_party_view`; `party_survives` is also used by tests that monkeypatch `grind_episode.party_survives` at `tests/test_grind_episode.py:400` and `:404`: if you remove it from `grind_episode`, those tests must patch `sustain.party_survives` instead; change nothing else in them). Check with `git grep -n "party_hp\|heal_items\|bag_contents\|read_party_view\|party_survives" src/pokeagent/explorer/grind_episode.py` before dropping any import.

**Step 6: the hurt-no-potion start gate (pin it).** Add to `tests/test_training_ctl_sustain.py` (use `make_ctx`, `use_ledger`, `make_ledger`, `PATCH_MAPS`, `_start` from `tests/test_grind_episode.py`, the same helpers `test_a_fainted_member_is_never_a_survivor_and_still_ends_the_episode` uses at :411-424): (i) hurt (a member at 0 HP via `rr.party_now` monkeypatch) and no potion -> `grind_episode.start(ctx)` is False and the logged why is `would end at once (hurt with no potion)`; (ii) the same party WITH a potion in the bag -> not refused for that reason; (iii) `sustain.hurt_no_potion` equals the old expression on those two cases. Do NOT add a new start rule; if (i) already fails on main, stop and write why in the Status row.

**Step 7: adapt tests (only what the moves force; name each in the Report).**
- `tests/test_training_v2_slice3.py`: line 7 imports `after_heal, grind_heal`; change those uses to `sustain` (`sustain.needs_heal`, `sustain.potion_instead`, `sustain.grinding`, `sustain.leaving`); monkeypatch targets `grind_heal.read_party_view/party_needs_heal/party_survives/needs_heal` (lines 85-124) become the same names on `sustain` (the module imports the same names). No assertion changes.
- `tests/test_training_v2_slice2.py:48-60` (`test_hold_and_grind_latch_walk_marks_training_live`): the `_grind_step` walk now stamps instead of writing the flag: assert `ctx.__dict__.get("grind_walk_step")` is `None` for the None step and set for the real step; add the tick half: with that stamp, `TrainingController().tick(ctx)` makes `ctx.train_route_live` True, and without it (and not team_ready) False. Keep the `monkeypatch.setattr(plan_goal, "party_survives", ...)` line (`_grind_step` still uses it).
- `tests/test_grind_pressure_plan_goal.py:99`: `monkeypatch.setattr(plan_goal, "heal_push_on", ...)` becomes `monkeypatch.setattr(sustain, "heal_push_on", ...)`; lines 41 and 53 patch `plan_goal.party_survives` for `_grind_step` (still valid); if a test there also drives the planner `_survives` key, also patch `sustain.party_survives`.
- `tests/test_bandit.py:289` (`seen["_push_on"] is False`) must pass UNCHANGED (the key names are kept on purpose).
- `tests/test_training_ctl_shadow.py` must pass; if the writer move forces a change, make the smallest one and say which assertion and why in the Report.

**Step 8: `tools/step_budget.py` rows** (pure readers; add tests to `tests/test_step_budget.py` with small fabricated `levels.jsonl` / `console.log` in `tmp_path`):
- `bench_xp_per_1k_run_steps` (float, 1 decimal): from `levels.jsonl`, for consecutive rows match party members by SPECIES (slots reorder; a species present once in both rows; skip any species whose count differs between the two rows), sum the positive exp deltas per species over the run; the species with the largest total is the lead and is excluded; bench xp = the sum of the rest; divide by the run's steps (last `step` in `levels.jsonl`, or the console `--- step` header count when there are no rows) times 1000. No rows -> 0.0. Also emit `bench_xp_total` (int).
- `second_member_l9_step` (int | None): the first row `step` at which at least two party members have level >= 9; `None` when never. (Slot-keyed `floor_first_step` stays; reorders make it unreliable.)
- `walk_to_grass_lines` and `walk_to_grass_after_episode_start`: the first is the existing activity count (keep the existing `ACTIVITIES` row untouched); the second counts `goal team_ready: N steps to ... grass` thinking lines that occur between a `[grind episode] start on` console line and the first `BATTLE` thinking line after it (or the next episode start), tracked with the `--- step` headers. Also `walk_to_grass_per_episode` = that count / number of episode starts (0.0 when none). Fabricate a console.log with two episodes in the test (one with a 56-line walk, one with a 3-line walk) and assert both numbers.
- Render the new rows with the existing `render`; do not change `route24_xp_per_1k` (keep it, but its docstring/comment must say it is per-member-window steps and not a run-step rate; the plan no longer gates on it).

## 4. What NOT to do

- Do not touch `planner.py` or `planner_east.py` (the plan says their heal branches "read heal_now()": here they keep reading `_hp`/`_survives`/`_push_on` and `heal_now(...).goal_keys()` produces those keys, so their ~27 gate tests stay valid).
- Do not touch Roster (`trainee_gate`, `magikarp.trainee_slot_for`, `party_order`, `switch_out`), Exit (`grind.py`, `GrindBudget`, `ctx.grind`, `gym_hold_seen`, `floor_unmet`, `gate_lifted`/`lifted_need`), the loop guard (`center_visit`, `LoopGuard`), Mart/restock, `grind/points.py`, ledger files, `bandit/hook.py`.
- No lines added to `explorer/context.py` or `explorer/memory.py`; plan_goal.py <= 300 lines and net <= 0. Do not add a field to `ExplorerContext`; the stamp lives in `ctx.__dict__`.
- Do not memoize `heal_now` and do not call `heal_push_on` from `tick` (the bandit's decide/clear must run only where it runs today).
- Do not invent a new "do not start" rule for episodes (step 6 pins the existing one).
- No ROM runs, no `tools/explore_demo.py`, no `runs/` access. The seed A/B is Claude's after merge.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

**Baseline first** (unmodified base):
```
uv run pytest -q -p no:cacheprovider tests/test_retreat_heal.py tests/test_frontier_patrol.py tests/test_early_training_gate.py tests/test_step_budget.py tests/test_training_ctl_shadow.py tests/test_training_ctl_target.py tests/test_training_v2_slice3.py tests/test_training_v2_slice2.py tests/test_grind_pressure_plan_goal.py tests/test_grind_episode.py tests/test_bandit.py
```
Expected: 0 failed (Claude ran the three named gate files on `19fce6c`: `27 passed`; this whole command: `143 passed`). If the baseline is not 0 failed, stop and write the failing ids in the Status row.

After your changes, the same command must give 0 failed (the count grows by your new tests; none removed).

Structure checks:
```
wc -l src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py src/pokeagent/explorer/training_ctl/sustain.py src/pokeagent/explorer/training_ctl/controller.py
git diff --stat origin/main -- src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py src/pokeagent/explorer/memory.py
git grep -n "grind_heal\|after_heal" -- src tests tools
git grep -n "train_route_live *=" -- src
```
Expected: plan_goal <= 300 and net <= 0; context.py 300 and not in the diff; memory.py not in the diff; sustain.py and controller.py < 120; no `grind_heal`/`after_heal` hits (docstrings in history comments excepted: none should remain); the only `train_route_live =` write in `src` is in `training_ctl/controller.py` (plus the dataclass field default at `context.py:124`, which is a declaration, and `adapters.py`'s `TrainingState(train_route_live=...)` keyword arguments, which are not ctx writes).

New tests, `tests/test_training_ctl_sustain.py` (plus the step_budget tests):
- `test_heal_now_matches_the_old_grind_heal_verdicts`: the three scenarios of `tests/test_training_v2_slice3.py` (survivable fighter at 30% while grinding -> `weak` and `floor_heal` False; unsurvivable -> True; fainted member -> `floor_heal` True and `use_potion` False).
- `test_goal_keys_feed_the_planner`: `heal_now(ctx, goals).goal_keys()` has exactly `_survives` and `_push_on`; with `ctx.bandit is None` `_push_on` is False; `heal_now(ctx)` (no goals) never calls `heal_push_on` (monkeypatch it to raise).
- `test_leaving_and_to_grass`: `leaving` as before; `to_grass` returns `planned` unchanged when not live, replaces a None / "leaving the Pokecenter" step with `train_route.step` (monkeypatched) when live, keeps `planned` when `train_route.step` returns None.
- `test_tick_is_the_sole_writer`: `team_ready_live` True -> tick sets the flag True; False and no stamp -> False; stamp at `ctx.step - 1` -> True, at `ctx.step - 5` -> False; an exception inside tick (ctx without `view`) leaves the flag and does not raise.
- `test_engine_ticks_before_choose`: a stub selector whose `choose` records `ctx.train_route_live`; the engine step with `team_ready_live` monkeypatched True shows the flag already True inside `choose`.
- The step 6 tests, and `test_sustain_does_not_import_grind_episode` (`"grind_episode" not in` its import lines via `inspect.getsource`).
- Fresh-process import check as a test (no `python -c` in this run): `subprocess.run([sys.executable, "-c", "import pokeagent.explorer.training_ctl.sustain, pokeagent.explorer.behaviours.plan_goal, pokeagent.explorer.grind_episode, pokeagent.explorer.behaviours.retreat_heal, pokeagent.explorer.behaviours.frontier"], capture_output=True, text=True)` asserts `returncode == 0`, and the same with `import pokeagent.explorer.grind_episode` alone and `import pokeagent.explorer.training_ctl.sustain` alone (an import cycle hides in a warm process). If an ImportError appears, make the heavy import in `sustain.py` lazy (as `cave_topup` already is) and say so in the Report; do not refactor further.

Full suite once at the end:
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed, skips unchanged from base (record the base count; never use `-n`).

```
git status --short
```
Expected: only files from section 2 (plus the two deletions).

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt for missing things: if something named here is missing or a cited shape differs, stop and write why in the Status row.
- Use `uv run` and Python 3.12 only; never bare `python`, and never `python -c` (put every check in a test).
- Create no scratch or debug files; if you need one, put it under `.devin-scratch/` and leave it there (deleting is denied).
- Never commit to main/master, never push to main, never deploy, never merge. Commit as you go on your branch and push it.
- No ROM runs, no `tools/explore_demo.py`, no `runs/` access; never touch ROM files.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Set the Status to `Review` only when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `TrainingController.tick` is called before `selector.choose` and is the only writer of `ctx.train_route_live` (`mark_live` stamps `ctx.__dict__["grind_walk_step"]`; plan_goal :130 gone). <!-- test: tests/test_training_ctl_sustain.py::test_tick_is_the_sole_writer -->
- [ ] `training_ctl/sustain.py` exists (< 120 lines) with `heal_now`, `to_grass`, `leaving`, `hurt_no_potion`; no module under `src/` imports `grind_heal` or `after_heal` (Claude deletes both files in review; a test asserts no importer); retreat_heal, frontier and plan_goal read `heal_now`. <!-- test: tests/test_training_ctl_sustain.py -->
- [ ] An episode never starts hurt with no potion, pinned by test; `_end_reason` uses `sustain.hurt_no_potion`. <!-- test: tests/test_training_ctl_sustain.py -->
- [ ] `tools/step_budget.py` reports `bench_xp_per_1k_run_steps`, `second_member_l9_step`, `walk_to_grass_after_episode_start`, `walk_to_grass_per_episode`. <!-- test: tests/test_step_budget.py -->
- [ ] plan_goal.py <= 300 lines and net <= 0; context.py and memory.py not in the diff; `planner.py`/`planner_east.py` untouched.
- [ ] Gate tests and the full suite: 0 failed.

## 8. Report

Findings first: what changed per file; the exact `wc -l` numbers; each test you adapted in step 7 and why; the timing change of the flag (before: same-step in plan_goal; now: start of step, previous-step `train_need`, one-step-old stamp) and any shadow-test change it forced; whether `hurt_no_potion` test (i) passed on the unmodified base (it should: the start gate already exists). Then real output tails: the baseline gate run, the new gate run, the structure checks, the full-suite line. State plainly that no ROM was used. The real-ROM A/B (seeds 12/13/14, 12000 steps from heal_cerulean) is Claude's after merge and judges: bench xp per 1k run steps not worse than baseline on each seed, 2nd party slot to L9 not later, SHAKE <= 7.2%, heal + leave-PC < 12.9%, walk-to-grass per episode (about 56 steps baseline) reported.

## Required from User

Nothing for the build. After merge, Claude runs the seed A/B on the laptop.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/training-controller-2026-11-13.md)
- Read(src/pokeagent/explorer/behaviours/plan_goal.py)
- Read(src/pokeagent/explorer/behaviours/retreat_heal.py)
- Read(src/pokeagent/explorer/behaviours/frontier.py)
- Read(src/pokeagent/explorer/behaviours/grind_loop.py)
- Read(src/pokeagent/explorer/grind_episode.py)
- Read(src/pokeagent/explorer/training_ctl/controller.py)
- Read(src/pokeagent/explorer/training_ctl/adapters.py)
- Read(src/pokeagent/explorer/engine.py)
- Read(tools/step_budget.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(wc)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Review |
| Assigned to | devin |
| Branch | directive/pokeagent-training-controller-slice3-sustai-06d7ec |
| Base branch | directive/pokeagent-training-controller-slice3-sustai-06d7ec |
| Base commit | a29c18da27f19dcee68b7aa11704de7c1ad96bdc |
| Head commit | 1ea401f35b2a31d5bdc5f9ab1c68a6c8515875d4 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-14 00:50 · robert-claude-laptop · none → Queued — Robert approved the Training Controller plan and slices; #255 merged.
- 2026-11-14 00:50 · robert-claude-laptop · Queued → Approved — lint override: behaviours/plan_goal.py, behaviours/grind_loop.py, behaviours/frontier.py and training_ctl/adapters.py are shorthand for existing files under src/pokeagent/explorer/ (the directive states paths are under that root); training_ctl/sustain.py is the new module this directive creates.
- 2026-11-14 01:07 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice3-sustai-06d7ec; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7CAPM3Q69ZVMGK6HW4K8E53
- 2026-11-14 01:14 · dispatcher · launched pid=23180; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice3-sustai-06d7ec; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (15 declared need(s); 10 external))
- 2026-11-14 01:23 · devin · In progress → Blocked — Refused: `git rm src/pokeagent/explorer/grind_heal.py src/pokeagent/explorer/after_heal.py` - directive step 1 requires deleting these two files, but file deletion is refused in every form this sandbox permits (git rm denied by a user deny rule; no del/Remove-Item/git variant is in the allowed command set). sustain.py was written and is committed+pushed on the branch; all other work is unblocked but the deletion gate makes Review impossible as written.
- 2026-11-14 01:25 · robert-claude-laptop · Blocked → Queued — Directive fixed (#256): Devin no longer deletes files; Claude removes grind_heal.py/after_heal.py in review. Branch has sustain.py (002d4f3) merged with main (64ff940); continue from it.
- 2026-11-14 01:25 · robert-claude-laptop · Queued → Approved — lint override: behaviours/*.py and training_ctl/adapters.py are shorthand for existing files under src/pokeagent/explorer/; training_ctl/sustain.py already exists on the base branch (002d4f3).
- 2026-11-14 01:25 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice3-sustai-06d7ec; lane=default; model=swe-2-high; perm=smart; persona=steady-builder; agent_id=01M7CBQ6MSEFX41SFJDTYDG6NM
- 2026-11-14 01:29 · dispatcher · launched pid=19340; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-training-controller-slice3-sustai-06d7ec; provisioned: uv sync --frozen; permission-mode=smart (`## Sandbox needs` declared (15 declared need(s); 10 external))
- 2026-11-14 01:41 · devin · In progress → Review — [origin] spent: devin 20 min est. n/a
<!-- queue:end -->
