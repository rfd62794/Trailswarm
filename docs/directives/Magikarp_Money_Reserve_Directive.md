# Trailswarm: keep the Magikarp money safe - a reserve from Pewter on, a short circle-back after a blackout, and readers that stop counting a skipped goal as reached

**Size:** M. **Assignee:** devin.

**Depends on:** PR #202 (`fix/magikarp-goal-premature`) being merged. This directive builds on its `st["buy_skipped"]` latch in `magikarp_goal_settled` and on the `"skipped": true` field it adds to `goal_frames.jsonl`. Check: `git grep -n "buy_skipped" src/pokeagent/magikarp.py` must print lines. If it prints nothing, stop and write that in the Status row; do not recreate the fix.

**Read first (all in the worktree; if one is missing, stop and say so in the Status row):** `src/pokeagent/magikarp.py`, `src/pokeagent/explorer/economy/budget.py`, `src/pokeagent/explorer/economy/shopping.py`, `src/pokeagent/explorer/behaviours/restock.py`, `src/pokeagent/explorer/planner_magikarp.py`, `src/pokeagent/explorer/behaviours/plan_goal.py` (lines 30-60), `src/pokeagent/explorer/press_goals.py` (lines 55-90), `tests/test_magikarp.py`, `tests/test_hands_off.py`.

## 1. Why this exists

Robert wants the 500-yen Magikarp (the switch-training plan, `Magikarp_Switch_Training_Directive.md`). Three gaps remain after PR #202:

- **Nothing protects the 500 yen.** Money can be spent in Pewter (Poke Balls, Potions) before the agent reaches the Mt Moon Pokemon Center (map 0x44). #202 only stops that spending from *settling* the goal; the money is still gone and the goal is then skipped at 0x44. Every purchase decision reads the existing reserve, which does not know about the Magikarp (section 1.1).
- **A blackout can still cost it.** A blackout halves money in Gen 1. Arriving at 0x44 poor today latches `buy_skipped` for good (`magikarp.py:60-61`), even when the agent is a few steps west of Mt Moon with new money a trainer fight later.
- **Skipped looks like reached.** #202 writes `{"goal": "buy_magikarp", ..., "skipped": true}` to `goal_frames.jsonl`, but readers treat any row as "reached" (section 1.3). `runs/milestones.json` gets the same goal with no flag at all.

### 1.1 Real current code (pasted; you cannot read outside this worktree)

`src/pokeagent/magikarp.py` (branch head 58bb975):

```python
13  MAGIKARP_PRICE = 500                 # the salesman's price in the Mt Moon Pokemon Center (map 0x44)
14  MT_MOON_CENTER = 0x44
17  BUY_STEP_CAP = 600                   # steps in/around the center without buying before the goal is dropped for the run
47  def can_buy(emu) -> bool:
49      return read_money(emu) >= MAGIKARP_PRICE and emu.read(PARTY_COUNT) < 6
52  def magikarp_goal_settled(emu, st: dict, seen: set) -> bool:
57      sp = party_species(emu)
58      if MAGIKARP in sp or GYARADOS in sp:
59          st["had_magikarp"] = True
60      if not st.get("had_magikarp") and not can_buy(emu) and emu.read(0xD35E) == MT_MOON_CENTER:
61          st["buy_skipped"] = True  # sticky: leaving the center must not reopen the goal
62      return bool(st.get("had_magikarp")) or bool(st.get("buy_skipped")) or 0x3B in seen
```

The existing reserve, `src/pokeagent/explorer/economy/budget.py` (the only place a spend limit is computed):

```python
5   FLOOR, FLOOR_PER_BOSS = 300, 100
13  def reserve(goals: dict, money: int, ref_money: int = 0) -> int:
16      money = max(money, ref_money)
17      return FLOOR + FLOOR_PER_BOSS * sum(1 for g in BOSS_GOALS if goals.get(g)) + blackout_cost(money) // 2
19  def spendable(goals: dict, money: int, ref_money: int = 0) -> int:
20      return max(0, money - reserve(goals, money, ref_money))
```

With money 600 and no boss beaten this reserve is `300 + blackout_cost(600) // 2 = 300 + 150 = 450`, below 500: the agent may spend 150 and arrive with 450.

**Purchase decision sites.** Every caller of `budget.reserve` / `budget.spendable` (grep `git grep -n "spendable\|budget.reserve\|shopping_list" src tools`), and each gets the floor from ONE place (the goals dict, 3.2), with no new argument threaded through any of them:

1. `src/pokeagent/explorer/economy/shopping.py:36` `left = budget.spendable(goals, money, ref_money)` in `shopping_list(...)` (lines 30-68). Every item (Poke Ball line 52, heal item 53-60, Antidote 63-66, Escape Rope 67) is capped by `left`. Called by `economy/plan.py:51` (`make_list`, which `trip_plan` at `plan.py:55-62` uses) with `ctx.goals()`.
2. `src/pokeagent/explorer/economy/bundles.py:20` `shopping_list(goals, bag, money, party, stats, ...)` in `candidate_bundles` (lines 14-23): same `goals` dict, so it inherits the floor through (1).
3. `src/pokeagent/explorer/behaviours/restock.py:122,128` inside `_visit` (lines 107-148): `reserve = budget.reserve(ctx.goals(), money, led.ref_money)` then `qty = min(qty, max(0, (read_money(ctx.emu) - reserve) // max(1, price(item))))  # the reserve is never breached`, then `shop.buy(ctx.emu, item, qty)` at line 131 (the only `shop.buy` call in `src/`).
4. `src/pokeagent/knowledge/catch_plan.py:88` `spend = budget.spendable(goals or {}, money or 0)`: how many balls the catch plan may budget for; `goals` is the caller's goals dict, so it inherits the floor too (verify the caller passes `ctx.goals()`: `git grep -n "catch_plan\." src`; if one passes a hand-built dict it simply gets floor 0, which is the old behaviour).
5. `src/pokeagent/explorer/restock.py:12-30`: `MONEY_RESERVE = 300`, `buy_quantity`, `ball_buy_wanted`. Exercised only by `tests/test_team_inventory.py:59-64` (no caller in `src/`). Leave them unchanged; the test must keep passing.

Healing at a Pokemon Center is free and spends no money: it is not a purchase and must stay unaffected. Selling Nuggets (`shop.sell`) is unaffected too.

### 1.2 Map ids (confirmed against `src/pokeagent/atlas/map_names.json`)

```
"2": "PEWTER_CITY"   "14": "ROUTE_3"   "15": "ROUTE_4"   "59": "MT_MOON_1F"   "68": "MT_MOON_POKECENTER"
hex: PEWTER_CITY 0x02, ROUTE_3 0x0E, ROUTE_4 0x0F, MT_MOON_1F 0x3B, MT_MOON_POKECENTER 0x44
Pewter Mart "56" = 0x38 (the only Mart before the cave). goals.py: "to_pewter": 0x02 in seen, "to_route3": 0x0E in seen,
"to_route4": 0x0F in seen, "to_mt_moon": 0x3B in seen. "West of Mt Moon" = maps {0x02, 0x0E, 0x0F} with 0x3B not seen.
```

### 1.3 Readers that count a skipped goal as reached

Writer, `src/pokeagent/explorer/press_goals.py:63-70` (#202): `fh.write(json.dumps({"goal": g, "step": ctx.step, "frame": ctx.frame, **({"skipped": True} if skipped else {})}) + chr(10))`. The same loop then appends `rec = {"run": ctx.run_dir.name, "step": ctx.step}` to `runs/milestones.json` with NO skipped flag (lines 80-87).

Verified against this branch; these read `goal_frames.jsonl` and treat any row as reached:

| File:line | What it does with a skipped row |
|---|---|
| `src/pokeagent/review/hands_off.py:43` | `row = next((r for r in jsonl(path) if r.get("goal") == goal), None)`: a skipped `buy_magikarp` row passes the judge. **Must change.** |
| `src/pokeagent/review/events.py:35-37` | `_goal_events` emits a "goal" event for every row |
| `src/pokeagent/review/diff.py:35-36` | `_goal_times` records a time for every row |
| `src/pokeagent/review/timeline.py:19-20` | `[r.get("goal") for r in data.goal_frames]` (found in review; not in the first list) |
| `src/pokeagent/review/swarm.py:76` | `gf = next((r for r in jsonl(...) if r.get("goal") == stop), None)` |
| `src/pokeagent/evaluation_ab.py:35` | `hit = next((g for g in _lines(...) if g.get("goal") == goal), None)` |
| `tools/seg_ingest.py:110` | `gf = next((r for r in _jl(...) if r["goal"] == stop), None)` (the solve judgement) |
| `tools/milestones_clean.py:45-47` | `reached.setdefault(rec["goal"], int(rec["step"]))` |

These read `runs/milestones.json` (no flag today, so add it in the writer first): `src/pokeagent/novelty/backfill.py:51-55` (`milestone_features`), `src/pokeagent/procedures/mine.py:29-30` (`goal_steps_for`).

Leave alone: `tools/seg_ingest.py:67` (frame/step calibration; a skipped row's frame and step are real) and `tools/swarm_watch.py:105` (counts lines as run progress for stall detection; a skipped goal is progress).

## 2. Scope (items 1-3 and 5 are one PR; item 4 may ship as a separate PR)

1. `src/pokeagent/magikarp_reserve.py` <!-- new: src/pokeagent/magikarp_reserve.py -->: pure functions and constants (3.1).
2. The floor, single source of truth (3.2): `src/pokeagent/explorer/economy/budget.py` only (a per-step module value, set by the deferral module). `check_goals` output does NOT change (the only new goals-dict key is `_buy_deferred` inside the existing plan_step dict literal, 3.3). No purchase caller changes.
3. Circle-back (3.3): new `src/pokeagent/explorer/magikarp_deferral.py` <!-- new: src/pokeagent/explorer/magikarp_deferral.py -->, `src/pokeagent/magikarp.py` (`magikarp_goal_settled`), `explorer/planner_magikarp.py`, and `explorer/behaviours/plan_goal.py` (replace two existing blocks with one-line calls, one call site each, plus one key inside an existing dict literal; it must end at or below its current 300 lines).
4. Skipped readers (3.4), **may ship as a separate PR**: `review/load.py`, the call sites in 1.3, the flag in `press_goals.py`.
5. Tests (3.5): `tests/test_magikarp_reserve.py` <!-- new: tests/test_magikarp_reserve.py -->, additions to `tests/test_magikarp.py` and `tests/test_hands_off.py`.

Size rule, honest version: every NEW module stays under 300 lines. Two touched files are at the limit today: `explorer/behaviours/plan_goal.py` (300 lines) and `tools/seg_ingest.py` (299). Neither may grow: all new logic goes in the new modules; `plan_goal.py` only swaps existing blocks for one-line calls (net fewer lines), and `seg_ingest.py` gets an in-place edit of one existing line with NO new import (inline `not r.get("skipped")`). Check with `wc -l` before and after; if either ends above its starting count, stop and move logic out.

## 3. The work

### 3.1 `magikarp_reserve.py` (pure, no emulator)

```python
MAGIKARP_RESERVE_MARGIN = 100   # yen kept above MAGIKARP_PRICE
CIRCLE_BACK_MAX_PATH = 80       # a trip to 0x44 longer than this many path steps is not worth it
CIRCLE_BACK_STEP_CAP = 1500     # steps with the goal deferred before it settles as skipped
WEST_OF_MT_MOON = frozenset({0x02, 0x0E, 0x0F})   # Pewter, Route 3, Route 4

def reserve_active(st: dict, seen: set) -> bool:
    """Pewter reached (0x02 in seen), no Magikarp owned or ever owned, goal not skipped, Mt Moon 1F (0x3B) not seen."""

def magikarp_floor(st: dict, seen: set) -> int:
    """MAGIKARP_PRICE + MAGIKARP_RESERVE_MARGIN while reserve_active, else 0."""

def should_circle_back(money: int, party_count: int, map_id: int, path_len: int | None) -> bool: ...
```

**Margin 100, justified:** it is the price of the cheapest item the shopping list buys (an Antidote, 100 yen). The purchase loops divide by unit price, so a margin below one item's price can leave the balance exactly on the line after rounding or a price read of 0; 100 keeps one cheap item of slack. It does not try to cover a blackout (that is the circle-back's job). Named constant so a run can tune it.

`reserve_active` depends only on `st` and `seen` (`goals.py:90-94`: `st.setdefault("seen_maps", set())`, `st["had_magikarp"]`, `st["buy_skipped"]`). Once the goal settles by any path (`magikarp_goal_settled` true) the floor is 0 and normal spending resumes. `from_pewter_onward` means `0x02 in seen`.

### 3.2 Using the floor (one source, no new arguments, no new goals keys)

**Do NOT put the floor in the goals dict.** `check_goals` (`goals.py:88-136`) returns only the bool ladder (`dict[str, bool]`); the `"_sprites"` and other `"_"` keys are merged later, only into the dict handed to `plan_step` (`plan_goal.py:132-134`). Extra keys in `check_goals`/`ctx.goals()` output would leak into consumers that treat every truthy value as a reached goal or hash the whole dict (`tools/explore_headless.py:135`, `tools/explore_demo.py:240,245`, `tools/watch.py:143`, `team_hunt.py:110`, `replay_beat.py:42,75`). `ctx.goals()` (`context.py:288`) is the same dict, so it is not safe either.

**Chosen: a per-step module value in `budget`, set by the new deferral module.** The repo already does this for the blackout tax: `plan_goal.py:64` `set_blackout_tax(extras)  # every readiness_for caller sees the learned margins this step` (`explorer/training.py:35`). Same shape here, and it reaches every caller including `catch_plan.py:88`, which only receives a plain goals dict and has no `ctx`:

- `budget.py` gains `_magikarp_floor = 0`, `def set_magikarp_floor(n: int) -> None` and `def magikarp_floor() -> int`. `budget.reserve(goals, money, ref_money)` returns `max(existing, _magikarp_floor)`; `spendable` calls `reserve`, so it follows. Default 0 keeps every existing test unchanged.
- `magikarp_deferral.tick` (3.3) calls `budget.set_magikarp_floor(magikarp_reserve.magikarp_floor(st, seen))` once per step, so the value is current for every purchase decision made after plan_goal in that step. Check the behaviour order (`behaviours/__init__.py`): if a purchase behaviour (restock) can run earlier in the same step, it sees the previous step's floor; one step of lag is acceptable, but say in the report which order you found. `st` is the explorer context and `seen` is `st["seen_maps"]` (`goals.py:94`).
- Reset it in an autouse fixture in `tests/conftest.py` (`budget.set_magikarp_floor(0)` before and after every test), exactly like the existing `_clear_blackout_tax` autouse fixture at `tests/conftest.py:36`; any test that runs a plan_goal step would otherwise leak the floor into later test files.
- This covers callers 1-4 in 1.1 (shopping_list, bundles, `_visit`, catch_plan); do not add a `floor` argument to any of them. `explorer/restock.py` (caller 5) stays as is.
- **Required test:** `check_goals` output has no key starting with `_` and only bool values (this guards the leak above), run against the existing fake emulator in `tests/test_magikarp.py`.

### 3.3 Circle-back

Today (`magikarp.py:60-61`): at 0x44, no Magikarp, `not can_buy` -> `st["buy_skipped"] = True`, permanently. Two existing blocks in `plan_goal.py` would also kill a deferred goal, and the design must handle both:

```python
# plan_goal.py:38-44 (the buy_steps cap; counts on 0x44 AND Route 4 0x0F, which is west of Mt Moon)
        if not goals_now_all["buy_magikarp"] and m in (MT_MOON_CENTER, 0x0F):
            ctx.buy_steps += 1
            if ctx.buy_steps > BUY_STEP_CAP:
                ctx.buy_skipped = True; ctx.center_intent = None
                ctx.log(f"[buy_magikarp: {BUY_STEP_CAP} steps in/around the Mt Moon Pokemon Center without buying - settled for this run]", "res")
                goals_now_all = ctx.goals()
# plan_goal.py:58-61 (keeps the agent inside the center while the goal is open)
        if m == MT_MOON_CENTER and not goals_now_all["buy_magikarp"]:
            ctx.center_intent = "buy_magikarp"  # stay inside until the salesman has been dealt with
        elif ctx.center_intent == "buy_magikarp" and goals_now_all["buy_magikarp"]:
            ctx.center_intent = None  # bought (or no longer possible): the planner may walk out now
```

A deferred goal is open, so without a change the agent would stay in the center (`center_intent`) until `buy_steps > 600` latched `buy_skipped`, long before any 1500 cap, and circle-back would be dead. The two blocks are far apart, so they stay in separate functions with exactly ONE call site each (never the same function twice, or `buy_steps`/`deferred_steps` double-count). In `src/pokeagent/explorer/magikarp_deferral.py`:

- `tick(ctx, m) -> dict`: the counting. It REPLACES block 38-44 in place (so it runs at the same point as today: after `goals_now_all = ctx.goals()`, before the `cut_learner` and `team_ready` blocks and before everything that reads `goals_now_all["buy_magikarp"]`), returns the refreshed `ctx.goals()`, and is called nowhere else: `goals_now_all = magikarp_deferral.tick(ctx, m)`. It also sets the budget floor (3.2).
- `sync_center_intent(ctx, m, goals) -> None`: the intent handling. It REPLACES block 58-61 in place (after `tick`, so it sees the settled state), one call: `magikarp_deferral.sync_center_intent(ctx, m, goals_now_all)`. No counters in it.
- `deferred(ctx) -> bool`: reads `st["buy_deferred"]`; used for the planner (rule 5).

Each call replaces a block, so `plan_goal.py` ends with fewer lines than its current 300. Rules:

1. **Deferring (in `tick`).** At 0x44, no Magikarp, `not can_buy`, `0x3B not in seen`, party has room: set `st["buy_deferred"] = True`; do NOT latch `buy_skipped`. A full party (6) is not fixed by walking: it still latches `buy_skipped` at once.
2. **center_intent (in `sync_center_intent`).** While `buy_deferred`: never set `ctx.center_intent = "buy_magikarp"`, and clear it if set, so the planner walks out of the center. Otherwise the two existing branches apply unchanged.
3. **buy_steps vs deferred_steps (in `tick`).** `buy_steps` (cap `BUY_STEP_CAP` 600, unchanged) counts only while NOT deferred (the active attempt to reach and buy). `deferred_steps` counts every step while `buy_deferred` and `0x3B not in seen`, on any map; past `CIRCLE_BACK_STEP_CAP` latch `buy_skipped` and log it like the existing cap. They never run together, and `deferred_steps` is never reset, so repeated blackouts cannot extend the wait.
4. **Starting the trip (in `tick`).** Each step while deferred, compute `should_circle_back(money, party_count, map_id, path_len)` (3.1) and, when true, set `st["buy_deferred"] = False` and `ctx.buy_steps = 0`: the normal buy attempt resumes (planner walks to 0x44, `buy_steps` counts again with its 600 cap, far above the path bound). `path_len` is `len(WorldGraph(ctx.mem.data.get("maps", {})).path(pos, lambda n: n[0] == MT_MOON_CENTER) or ())` as `explorer/heal_walk.py:83` builds its graph (no path -> `None` -> false). Arriving poor again (another blackout) re-defers via rule 1.
5. **Planner.** Add `"_buy_deferred": magikarp_deferral.deferred(ctx)` INSIDE the existing dict literal at `plan_goal.py:132-134` (a `"_"` key merged only into the `plan_step` argument, like `"_sprites"` and `"_center_intent"`; do not add a line). `planner_magikarp.magikarp_step` returns None at the top while `goals.get("_buy_deferred")`, so the explorer keeps earning money (trainers on Route 3/4) instead of walking into the center poor.
6. **Mt Moon 1F.** Once `0x3B in seen` the goal settles skipped exactly as today (`or 0x3B in seen`, `magikarp.py:62`); `buy_deferred` is ignored from then on and a skipped goal is never re-opened (`buy_skipped` stays sticky).
7. A successful buy (Magikarp in party) sets `had_magikarp` as today; the goal is reached with no `skipped` field.

`magikarp_goal_settled` (`magikarp.py:52-62`) changes only at lines 60-61: poor with room and `0x3B not in seen` sets `st["buy_deferred"] = True` instead of `buy_skipped` (full-party and 0x3B cases as above). The money test for circling back is price + margin, not price alone (Robert's rule). `CIRCLE_BACK_MAX_PATH` and `CIRCLE_BACK_STEP_CAP` are tunable first guesses, like the margin: not measured, a run may retune them.

### 3.4 Skipped readers (may ship as a separate PR)

- `src/pokeagent/review/load.py:111` builds `RunData.goal_frames` from `jsonl(run_dir / "goal_frames.jsonl", skipped)`. Wrap it once: `goal_frames=reached_rows(jsonl(...))`, with `def reached_rows(rows): return [r for r in rows if isinstance(r, dict) and not r.get("skipped")]` defined in the same file. That covers `events.py:35-37`, `diff.py:35-36` and `timeline.py:19-20` (they read `data.goal_frames`).
- Readers that open `goal_frames.jsonl` themselves, each changed at its one line: `review/hands_off.py:43` (import `reached_rows` from `pokeagent.review.load`; a skipped row for the asked goal gives the reason `"goal <name> was skipped (not reached)"`, not "never reached"), `review/swarm.py:76`, `evaluation_ab.py:35` (inline `not g.get("skipped")`), `tools/seg_ingest.py:110` and `tools/milestones_clean.py:45` (inline `not r.get("skipped")`, no new import: seg_ingest is at the 299-line limit).
- Writer: in `press_goals.py` add `"skipped": True` to `rec` when `skipped`, before `hist.setdefault(g, []).append(rec)`. `novelty/backfill.py:55` and `procedures/mine.py:30` ignore entries with `e.get("skipped")`.
- Existing `runs/milestones.json` entries stay as they are. Never rewrite any file under `runs/`.

### 3.5 Tests (synthetic, no ROM, no emulator; fake emulators as `tests/test_magikarp.py` already does)

`tests/test_magikarp_reserve.py`:
- reserve blocks a buy: Pewter seen, money 600, `shopping_list(...)` with the floor returns no Poke Ball line that takes money below 600 (500 + 100); the same call without the floor returns the buy.
- floor comes through `budget`: after `budget.set_magikarp_floor(600)`, `budget.spendable({}, 800)` is 200 (and 0 after `set_magikarp_floor(0)`); `catch_plan` and `candidate_bundles` given a plain goals dict also stay above 600. A fixture resets the floor to 0.
- `check_goals` output has no key starting with `_` and only bool values.
- `tick` is called once per step: with the goal open and not deferred, one `plan_goal` step raises `buy_steps` by exactly 1; deferred, it raises `deferred_steps` by exactly 1 and `buy_steps` by 0.
- floor is 0 once settled: `had_magikarp`, `buy_skipped`, and `0x3B in seen` each give floor 0 and the buy is allowed.
- floor is 0 before Pewter (`0x02 not in seen`).
- circle-back triggers on Route 3 with money restored: `buy_deferred`, map 0x0E, money 700, party 3, path 40 -> true; money 550 -> false; path 81 -> false; party 6 -> false.
- never after Mt Moon 1F: `0x3B in seen` with `buy_deferred` set -> `magikarp_goal_settled` true, no route.
- deferral at 0x44: poor with room does not latch `buy_skipped` and `tick` clears `center_intent`; a full party does latch it.
- `buy_steps` does not count while deferred: more than 600 steps on Route 4 with the goal deferred does not latch `buy_skipped`; it does count once the trip has started (rule 4).
- step cap: `deferred_steps` past `CIRCLE_BACK_STEP_CAP` settles skipped.

`tests/test_hands_off.py`: a `goal_frames.jsonl` row `{"goal": "buy_magikarp", "step": 40, "frame": 1, "skipped": true}` fails with a reason containing `skipped`; the same row without the flag passes. One test for `reached_rows` (drops skipped, keeps normal, ignores non-dicts) and one that `load.py` drops a skipped row from `RunData.goal_frames` (so `review/diff._goal_times` ignores it).

## 4. What NOT to do

- Do not thread a `floor` argument through any purchase caller; the floor lives in `budget` only. Do not touch `shop.py`, the shop menu pressing, or the Pokemon Center/heal behaviours. Healing is free and unaffected.
- Do not change `MAGIKARP_PRICE`, `BUY_STEP_CAP`, or the #202 `0x3B in seen` settle rule. Do not re-open a goal skipped after Mt Moon.
- Do not rewrite `runs/` data, `maps.json`, or any checkpoint. Do not touch `tools/swarm_watch.py` or the calibration loop at `seg_ingest.py:67`.
- Do not change the order of `GOALS` in `goals.py` and do not add a goal.
- Do not replace `budget.reserve` with a new formula: the floor only raises it (`max`).
- Do not run the emulator or `tools/explore_demo.py` (you have no ROM; every real run is Claude's).
- Do not push, merge, or commit to main/master. No broad refactor.

## 5. Verification

Run through `uv run`; confirm the interpreter first (verified 2026-11-12 on this branch: `Python 3.12.12`):

```
uv run python --version
uv run pytest tests/test_magikarp.py tests/test_magikarp_reserve.py tests/test_hands_off.py tests/test_economy.py tests/test_status_care_shopping.py tests/test_team_inventory.py tests/test_review_diff.py tests/test_review_swarm.py -q -p no:cacheprovider
```

Baseline on current main (run by the spec author on the merged branch, the seven existing files above minus `test_magikarp_reserve.py`): `139 passed, 5 skipped, 1 warning in 2.55s`. After the work every test above passes. Also `uv run pytest -q -p no:cacheprovider` over the whole suite if it finishes in your sandbox (say so if it does not): no failures beyond pre-existing skips.

`wc -l src/pokeagent/explorer/behaviours/plan_goal.py tools/seg_ingest.py` shows each at or below 300 / 299.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. No installs, downloads or fetches. Never read outside the working directory. Do not search, glob, or hunt: if something expected is missing, stop and write what in the Status row.
- Test command is `uv run pytest ...` as in section 5. Never bare `python` or `python -m pytest` (a system 3.14 collects different tests).
- No emulator, no ROM, no `runs/`, no `kb/rom_tables.json` (gitignored, absent in a fresh worktree; tests that need them skip).
- Never commit to main/master, never push, never deploy. Work stays on the `directive/<slug>` branch. Only Claude or Robert merges.
- Create no scratch or debug files (deleting is denied in the sandbox). If one is needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row rather than trying another way around it.
- Status row: Done only when every item in section 7 holds; Blocked with the reason otherwise.

## 7. Completion criteria

- [ ] `src/pokeagent/magikarp_reserve.py` exists with the constants, `reserve_active`, `magikarp_floor`, `should_circle_back`.
- [ ] `budget.reserve` reads the module floor set by `tick` and all callers in 1.1 get it with no signature change; with the floor at 0 every existing test is unchanged.
- [ ] A Poke Ball buy that would take money below 600 is blocked in Pewter and allowed once the goal settles (tests).
- [ ] At 0x44 poor and west of Mt Moon the goal stays open; circle-back fires only under all four conditions in 3.3; after `0x3B in seen` or the step cap it settles skipped and never re-opens (tests).
- [ ] (Item 4, may be a separate PR) Skipped rows are ignored by every reader in 1.3; `milestones.json` entries carry `"skipped": true` going forward.
- [ ] The section 5 command passes; `plan_goal.py` not above 300 and `seg_ingest.py` not above 299 lines, no new module over 300; no change outside section 2.
- [ ] Changes committed on the `directive/<slug>` branch; Status row updated.

## 8. Report

Findings first: the `budget.py` lines you changed and the callers you verified get the floor. Then the real output tail of the section 5 pytest command. Then each reader changed (file:line), anything in 1.3 you left alone and why, the final constants, and anything you could not settle (for example, where `ctx` reaches `st`/`seen`). Do not claim real-ROM behaviour works.

## Required from User

Claude runs a real-ROM hands-off check before merge (Devin has no ROM): (1) `uv run python tools/hands_off_check.py` from the bedroom start (cold agent, no map memory); (2) a run from `runs/checkpoints/to_pewter.state` with `--stop-at-goal to_mt_moon`, checking `goal_frames.jsonl` for a bought `buy_magikarp` or a `"skipped": true` row, and `decisions.jsonl` that no Poke Ball or Potion buy takes money below 600 in Pewter. Nothing is needed from Robert.

## Forbidden Actions

- Merge, push, deploy, or touch a protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Edit live config, `runs/`, checkpoints, or `maps.json`.
- Publish a ROM or save state anywhere (hard rule, 2026-11-08).
- Start the emulator or `tools/explore_demo.py`, in a shell or anywhere else.

## Sandbox needs

Read/write inside this worktree only; `uv run pytest` with the existing `.venv`. No network, no installs, no ROM, no access to `runs/` or `kb/rom_tables.json`.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-magikarp-money-reserve-directive |
| Base branch | - |
| Base commit | 779718d27c13bffa91fdd337ac9861b947802eb8 |
| Head commit | f01aca709d21435717c10818a5ccd0e83c3b030e |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-12 07:53 · robert-claude-laptop · none → Queued — Robert asked 2026-11-12 ("Write it up for Devin"); PR #203 merged 9846704 after 3 review rounds
- 2026-11-12 07:54 · robert-claude-laptop · Queued → Approved — lint override: line 222 names kb/rom_tables.json only to forbid using it (gitignored, absent in the worktree); not a dependency
- 2026-11-12 09:54 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-magikarp-money-reserve-directive; lane=default; model=swe-2-high; perm=accept-edits; persona=steady-builder; agent_id=01M7840RDCMYNQNVMGVP0ZY29W
- 2026-11-12 10:06 · dispatcher · launched pid=20300; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-magikarp-money-reserve-directive; provisioned: uv sync --frozen; permission-mode=accept-edits (no `## Sandbox needs` — default deny)
- 2026-11-12 10:27 · devin · In progress → Review — [origin] spent: devin 21 min est. n/a
- 2026-11-12 16:25 · robert-claude-laptop · Review → Done — note: Merged PR #211 (7a939ac) at f01aca7: verify 2584/0; ROM to_pewter->to_mt_moon PASS (Magikarp bought at 0x44 step 3118, Mt Moon 3138); bedroom->beat_brock PASS at 8943/9000 (2 Brock losses, gym hold lifted after 2500-step L9 stall - watch whether the 600-yen floor starves pre-Brock potions); controller fixes 5694902 (ping-pong), f01aca7 (main merge)
<!-- queue:end -->
