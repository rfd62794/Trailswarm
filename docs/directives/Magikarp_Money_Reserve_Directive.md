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

**Purchase decision sites (the only three; `shop.buy` is called from one place):**

1. `src/pokeagent/explorer/economy/shopping.py:36` `left = budget.spendable(goals, money, ref_money)` in `shopping_list(...)` (lines 30-68). Every item (Poke Ball line 52, heal item 53-60, Antidote 63-66, Escape Rope 67) is capped by `left`. `trip_plan` (`economy/plan.py:55-62`) and `plan.make_list` (`plan.py:50-52`) call it, passing `ref_money=ledger.of(ctx).reserve_ref(ctx.step)`.
2. `src/pokeagent/explorer/behaviours/restock.py:122,128` inside `_visit` (lines 107-148): `reserve = budget.reserve(ctx.goals(), money, led.ref_money)` then `qty = min(qty, max(0, (read_money(ctx.emu) - reserve) // max(1, price(item))))  # the reserve is never breached`, then `shop.buy(ctx.emu, item, qty)` at line 131 (the only `shop.buy` call in `src/`).
3. `src/pokeagent/explorer/restock.py:12-30`: `BALL_ID, BALL_MIN, BALL_BUY, MONEY_RESERVE = 0x04, 5, 10, 300`, `buy_quantity` (`(money - MONEY_RESERVE) // ball_price()`) and `ball_buy_wanted` (`money >= ball_price() * BALL_BUY + MONEY_RESERVE`). These decide *whether to walk to a Mart*; they use a flat 300 and never the budget module. Route them through the same floor so the agent does not walk to a Mart that will then buy nothing.

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

## 2. Scope (one PR, in order)

1. `src/pokeagent/magikarp_reserve.py` <!-- new: src/pokeagent/magikarp_reserve.py -->: pure functions and constants (3.1).
2. Wire the floor into the three purchase sites (3.2): `economy/budget.py`, `economy/shopping.py`, `economy/plan.py`, `behaviours/restock.py`, `explorer/restock.py`. No change to `shop.py`.
3. Circle-back (3.3): `src/pokeagent/magikarp.py` (`magikarp_goal_settled`), `explorer/planner_magikarp.py`, one call line in `explorer/behaviours/plan_goal.py`.
4. Skipped readers (3.4): `src/pokeagent/review/load.py` (one helper), the call sites in 1.3, and the flag in `press_goals.py`.
5. Tests (3.5): `tests/test_magikarp_reserve.py` <!-- new: tests/test_magikarp_reserve.py -->, additions to `tests/test_magikarp.py` and `tests/test_hands_off.py`.

Size rule: every new module and every file you touch stays under 300 lines (`behaviours/restock.py` and `plan_goal.py` are close: add a call line at most; logic goes in the new module).

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

### 3.2 Using the floor

- `budget.reserve(goals, money, ref_money)` gains `floor: int = 0` and returns `max(existing, floor)`; `spendable` passes it through. Default 0 keeps every existing test valid.
- `plan.make_list` computes the floor once and passes it to `shopping.shopping_list` (new keyword, default 0). Find where `ctx` holds `st`/`seen` with `git grep -n "seen_maps" src/pokeagent`; if it is not reachable from `ctx` in two reads, stop and write that in the Status row rather than adding a global.
- `behaviours/restock.py:122`: pass the same floor into `budget.reserve(...)`; the `qty` clamp at line 128 then enforces it. No other edit in that file.
- `explorer/restock.py`: `ball_buy_wanted` and `buy_quantity` take `floor=0` and use `max(MONEY_RESERVE, floor)`. Callers: `git grep -n "ball_buy_wanted\|buy_quantity" src tests`; pass the floor where the caller has it, else leave the default and say so in the Report.

### 3.3 Circle-back

Today (`magikarp.py:60-61`): at 0x44, no Magikarp, `not can_buy` -> `st["buy_skipped"] = True`, permanently. Change to:

1. At 0x44, `not can_buy(emu)`, no Magikarp, `0x3B not in seen`, and the party has room: set `st["buy_deferred"] = True` and `st.setdefault("deferred_steps", 0)`; do NOT latch `buy_skipped`. A full party (6) is not fixed by walking, so it still latches `buy_skipped` at once.
2. While `buy_deferred` and `0x3B not in seen` the goal stays open. `deferred_steps` += 1 per step (one call line in `plan_goal.py` beside the `ctx.buy_steps` counter at lines 39-44; logic in the new module). Past `CIRCLE_BACK_STEP_CAP` latch `buy_skipped` (settles skipped, log line shaped like the existing cap's).
3. Route back only when ALL hold: map in `WEST_OF_MT_MOON`; `money >= MAGIKARP_PRICE + MAGIKARP_RESERVE_MARGIN`; party count < 6; `len(g.path(pos, lambda n: n[0] == MT_MOON_CENTER)) <= CIRCLE_BACK_MAX_PATH`. That is the pure `should_circle_back`. `planner_magikarp.magikarp_step` (already walks to 0x44, lines 23-34) returns None while `buy_deferred` and `should_circle_back` is false, so the explorer keeps earning money (trainers on Route 3/4) instead of walking into the center poor again.
4. Once `0x3B in seen` the goal settles skipped exactly as today (`or 0x3B in seen`, line 62). A goal skipped after Mt Moon is never re-opened: `buy_deferred` is ignored once `0x3B in seen`, and `buy_skipped` stays sticky.
5. A successful buy (Magikarp in party) sets `had_magikarp` as today; the goal is reached with no `skipped` field.

The money test for circling back is price + margin, not price alone (Robert's rule).

### 3.4 Skipped readers

- `src/pokeagent/review/load.py`: add `def reached_rows(rows): return [r for r in rows if isinstance(r, dict) and not r.get("skipped")]`, imported by the others (`tools/` files import `pokeagent`; verify with `git grep -n "^from pokeagent\|^import pokeagent" tools/seg_ingest.py tools/milestones_clean.py`).
- Apply it at each row of the 1.3 table: hands_off.py:43, events.py:35, diff.py:35, timeline.py:19, swarm.py:76, evaluation_ab.py:35, seg_ingest.py:110, milestones_clean.py:45. For `hands_off.py`, a skipped row for the asked goal gives the reason `"goal <name> was skipped (not reached)"`, not "never reached".
- Writer: in `press_goals.py` add `"skipped": True` to `rec` when `skipped`, before `hist.setdefault(g, []).append(rec)`. `backfill.py:55` and `mine.py:30` ignore entries with `e.get("skipped")`.
- Existing `runs/milestones.json` entries stay as they are. Never rewrite any file under `runs/`.

### 3.5 Tests (synthetic, no ROM, no emulator; fake emulators as `tests/test_magikarp.py` already does)

`tests/test_magikarp_reserve.py`:
- reserve blocks a buy: Pewter seen, money 600, `shopping_list(...)` with the floor returns no Poke Ball line that takes money below 600 (500 + 100); the same call without the floor returns the buy.
- floor is 0 once settled: `had_magikarp`, `buy_skipped`, and `0x3B in seen` each give floor 0 and the buy is allowed.
- floor is 0 before Pewter (`0x02 not in seen`).
- circle-back triggers on Route 3 with money restored: `buy_deferred`, map 0x0E, money 700, party 3, path 40 -> true; money 550 -> false; path 81 -> false; party 6 -> false.
- never after Mt Moon 1F: `0x3B in seen` with `buy_deferred` set -> `magikarp_goal_settled` true, no route.
- deferral at 0x44: poor with room does not latch `buy_skipped`; a full party does.
- step cap: `deferred_steps` past `CIRCLE_BACK_STEP_CAP` settles skipped.

`tests/test_hands_off.py`: a `goal_frames.jsonl` row `{"goal": "buy_magikarp", "step": 40, "frame": 1, "skipped": true}` fails with a reason containing `skipped`; the same row without the flag passes. One test for `reached_rows` (drops skipped, keeps normal, ignores non-dicts) and one that `review/diff._goal_times` ignores a skipped row.

## 4. What NOT to do

- Do not touch `shop.py`, the shop menu pressing, or the Pokemon Center/heal behaviours. Healing is free and unaffected.
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
uv run pytest tests/test_magikarp.py tests/test_magikarp_reserve.py tests/test_hands_off.py tests/test_economy.py tests/test_status_care_shopping.py tests/test_review_diff.py tests/test_review_swarm.py -q -p no:cacheprovider
```

Baseline on branch head 58bb975 for the subset that exists today (`tests/test_magikarp.py tests/test_hands_off.py tests/test_economy.py tests/test_status_care_shopping.py`, run by the spec author): `104 passed, 2 skipped, 1 warning in 2.51s`. After the work every test above passes. Also `uv run pytest -q -p no:cacheprovider` over the whole suite if it finishes in your sandbox (say so if it does not): no failures beyond pre-existing skips.

`git grep -n "reached_rows" src tools` shows each reader in 3.4 using it.

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
- [ ] The three purchase sites in 1.1 use the floor; with the floor at 0 every existing test is unchanged.
- [ ] A Poke Ball buy that would take money below 600 is blocked in Pewter and allowed once the goal settles (tests).
- [ ] At 0x44 poor and west of Mt Moon the goal stays open; circle-back fires only under all four conditions in 3.3; after `0x3B in seen` or the step cap it settles skipped and never re-opens (tests).
- [ ] Skipped rows are ignored by every reader in 1.3's table; `milestones.json` entries carry `"skipped": true` going forward.
- [ ] The section 5 command passes; no touched file newly over 300 lines; no change outside section 2.
- [ ] Changes committed on the `directive/<slug>` branch; Status row updated.

## 8. Report

Findings first: for each of the three purchase sites, the line you changed. Then the real output tail of the section 5 pytest command. Then each reader changed (file:line), anything in 1.3 you left alone and why, the final constants, and anything you could not settle (for example, where `ctx` reaches `st`/`seen`). Do not claim real-ROM behaviour works.

## Required from User

Claude runs a real-ROM hands-off check before merge (Devin has no ROM): (1) `uv run python tools/hands_off_check.py` from the bedroom start (cold agent, no map memory); (2) a run from `runs/checkpoints/to_pewter.state` with `--stop-at-goal to_mt_moon`, checking `goal_frames.jsonl` for a bought `buy_magikarp` or a `"skipped": true` row, and `decisions.jsonl` that no Poke Ball or Potion buy takes money below 600 in Pewter. Nothing is needed from Robert.

## Forbidden Actions

- Merge, push, deploy, or touch a protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Edit live config, `runs/`, checkpoints, or `maps.json`.
- Publish a ROM or save state anywhere (hard rule, 2026-11-08).
- Start the emulator or `tools/explore_demo.py`, in a shell or anywhere else.

## Sandbox needs

Read/write inside this worktree only; `uv run pytest` with the existing `.venv`. No network, no installs, no ROM, no access to `runs/` or `kb/rom_tables.json`.
