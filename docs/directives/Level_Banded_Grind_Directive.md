# Trailswarm: level-banded grinding - a weaker Pokemon grinds in an area it can fight alone, near a Pokecenter, and keeps all the XP

**Size:** M. **Assignee:** devin.

**Depends on:** nothing on open work. Checked against origin/main (2026-11-12): the in-progress `Party_View_Directive.md` touches one line of `explorer/grind_episode.py` (its line 273: `_end_reason`, the `hp / mx < MIN_HP_FRACTION` check, adds `or any_fainted`); it does not touch `grind/`, `switch_out.py`, `party_order.py` or `bring_out.py`, and `Party_View_Migration_Constants_Directive.md` is about address constants. This directive edits `_try_start` and `_finish` in `grind_episode.py`, not `_end_reason`: if the Party_View branch is merged first, rebase and keep both; do not touch its line.

**Read first (all in the worktree; if one is missing, stop and say so in the Status row; do not search):** `src/pokeagent/grind/points.py`, `src/pokeagent/grind/points_io.py`, `src/pokeagent/grind/stage_maps.py`, `src/pokeagent/explorer/grind_episode.py` (lines 172-210, 255-270), `src/pokeagent/explorer/behaviours/switch_out.py` (lines 31-45, 134-150), `src/pokeagent/knowledge/readiness.py` (lines 17, 84-120), `src/pokeagent/knowledge/area_resistance.py` (lines 52-70), `tests/test_grind_points.py`, `tests/test_grind_episode.py`.

## 1. Why this exists

Settled with Robert, 2026-11-12: give a weaker Pokemon a real chance to fight and earn full XP in an area sensible for its level and not too far away. Today a trainee under the stage need is trained by the switch trick (send it in, swap it out on turn one), which is half XP at best, and `choose()` never asks whether the trainee could win the fights itself.

Gen 1 facts the design rests on: there is NO level-difference XP scaling; XP per kill = `base_exp * enemy_level / 7` (x1.5 for a trainer), split equally among the Pokemon that took part (`grind/xpmath.py:25-27`). Full XP therefore means the trainee fights the whole battle alone.

## 2. Current code (pasted; you cannot read outside this worktree)

`src/pokeagent/grind/points.py` (288 lines; origin/main 3215258):

```python
28  MIN_MEASURED = 2              # episodes before measured xp/min beats the prior in choose()
29  HOP_STEPS = 32                # steps a map crossing costs when only map ids are known
30  FAR_TRAVEL = 10_000           # "unreachable": dwarfs any real travel term
31  BAND_LO, BAND_HI = -2, 6      # default band around the top wild level
51      episodes: dict = field(default_factory=dict)  # {"run@step": [xp_per_min, blackouts, provenance]}
172 def _best(ledger, lvl, current_map, maps, blocked, only_maps, use_band):
        for p in ledger.points.values():
            lo, hi = p.level_band
            if use_band and not lo <= lvl <= hi: continue
            if only_maps is not None and (p.map_id not in only_maps or travel_steps(maps, current_map, p.map_id) >= FAR_TRAVEL): continue
            if blocked and ... and not _reachable(maps, current_map, p.map_id, blocked): continue
            xp = p.xp_per_min_measured if (p.n_measured >= MIN_MEASURED and p.xp_per_min_measured is not None) else p.xp_per_min_prior
            score = xp - travel_steps(maps, current_map, p.map_id) / atlas.STEPS_PER_MIN - p.blackout_rate * atlas.BLACKOUT_STEPS
            key = (-score, p.map_id)
            if best is None or key < best[0]: best = (key, p)
        return best
190 def choose(ledger, party_levels, need_level, current_map, mem=None,
           trainee_slot=None, blocked=frozenset(), only_maps=None) -> GrindPoint | None:
        # lvl = party_levels[trainee_slot] else lead; None when need_level - lvl <= 0
        best = _best(ledger, lvl, current_map, maps, blocked, only_maps, True)
        if best is None and only_maps is not None:  # a stage list with nothing in band: low XP beats no XP
            best = _best(ledger, lvl, current_map, maps, blocked, only_maps, False)
        return best[1] if best else None
78  def _recompute(p)   # xp_per_min_measured = mean of every episode's v[0]; blackout_rate = mean of v[1]
89  def episode_result(p, xp_gained, steps, blackouts, provenance="organic", ep_id=None, now=None)
        # p.episodes[ep_id] = [rate, blackouts, prov]; _recompute(p)
```

`src/pokeagent/grind/points_io.py:34-37`: `band_of(species)` returns `(hi + BAND_LO, hi + BAND_HI)` where `hi = max(t[2] for t in species)` (the top wild level), else `DEFAULT_BAND = (0, 100)`. `points.py` `merge_point` copies each episode value as `list(v)`, so extra trailing list elements survive a merge.

`src/pokeagent/grind/stage_maps.py` (whole file): `PRE_BROCK = frozenset({0x0C, 0x0D, 0x21, 0x33})` (Route 1, Route 2, Route 22, Viridian Forest); `BY_STAGE = {"beat_brock": PRE_BROCK}`; `allowed(stage)` returns it or None.

`src/pokeagent/explorer/grind_episode.py:198-200`, inside `_try_start` (line 172; episode dict `ep` has keys slot, need, battles0, blackouts0, start_step; `levels, slot = _levels(ctx), _slot(ctx)`, `lvl = _lvl_of(...)`):

```python
pt = gp.choose(_ledger(ctx, st), levels or [lvl], need, (ctx.view.m, ctx.view.x, ctx.view.y), ctx.mem,
               trainee_slot=slot, blocked=story_blockers.blocked_tiles(ctx),
               only_maps=stage_maps.allowed(getattr(ctx, "stage_goal", None)))
# then ep.update(point=pt, start_xp=..., maps={pt.map_id, pt.center_map} - {None}, id=f"{run}@{step}", provenance=...)
```

`_finish` (line 255) folds the result at line 266: `pt = gp.episode_result(pt, xp, max(1, steps), blk, provenance=ep["provenance"], ep_id=ep["id"])`. Episode caps: `explorer/grind.py:10-13` `GRIND_BATTLES = 25`, `GRIND_STEPS = 2500`, `GRIND_BLACKOUTS = 2`. `train_route.py:15` `MIN_HP_FRACTION = 0.5` (under it the heal behaviours decide).

Matchup estimator already in the repo (signatures verbatim):

```python
# src/pokeagent/knowledge/readiness.py
17  MARGIN = 0.30             # remaining HP fraction wanted on the mons that fought
84  def duel(a: Combatant, ahp: float, b: Combatant, bhp: float, chart: dict, moves: dict) -> tuple[float, float]
99  def fight(ours: list[Combatant], theirs: list[Combatant], chart: dict, moves: dict) -> float
    # >= 0: every enemy down, HP fraction left on the mons that fought; < 0: we lose
# src/pokeagent/knowledge/party.py
50  def trainer_mon(name: str, level: int, kb: dict | None = None) -> Combatant | None   # ROM stats, DV 8, learnset moves
58  def our_party(emu, kb: dict | None = None) -> list[Combatant]   # skips members with no ROM row, so indices can shift
# src/pokeagent/knowledge/area_resistance.py:52-56 builds the inputs this way (copy it, do not import its privates):
#   chart = {(a, d): e for a, d, e in table(kb, "type_chart")};  moves = table(kb, "moves")   # table from knowledge.kb
```

Encounter table (already drained from the ROM): `src/pokeagent/knowledge/encounters.py:34` `species_on(map_id, kb=None) -> {species: (min_level, max_level, chance_per_encounter)}` for a map's grass; `encounters.py:15` `slot_chances()` = the 10 grass slots' probabilities (51,51,39,25,25,25,13,13,11,3 of 256). The raw rows are `table(kb, "wild_by_map")[str(map_id)]["grass"]` = `[[level, "SPECIES"], ...]` (`grind/points_io.py:26-32` reads the same). `GrindPoint.species` is `[[species, min, max]]`. `GrindPoint.center_map` and `center_cost_frames` are often empty; `explorer/world.py:25` `POKECENTER_MAPS` lists every Pokecenter map; `points.travel_steps(maps, current, map_id)` (line 140) gives a BFS step count or `HOP_STEPS` per map crossing from a bare map id, `FAR_TRAVEL` when unknown.

Fight mode today. `explorer/behaviours/party_order.py:90-115` `want_home`: for a non-Magikarp trainee, `brk = team_plan.of(ctx).get("breakers")`, and `if brk and 0 < lead_level(ctx.emu) < (ctx.train_need or 0)` the lowest band breaker leads (`"exp rotation: the lowest band breaker leads the grind"`). Then `switch_out.py:31` `trainee_out(ctx) -> int | None` returns the trainee's slot when it is the mon out, and `SwitchOut.applies` (line 134-139) and `.step` (line 141) call it, then `switch_candidate(ctx.emu, t)` and the SWITCH menu presses swap it out on turn one (`switch_train`: half XP, ~6 presses). `trainee_out` is called only from those two places (verified with grep).

## 3. Scope

New small modules (every one under 300 lines; the size/layering test `tests/test_explorer_behaviours.py:257` covers `src/pokeagent/explorer` only, but `points.py` states its own 300 ceiling):

1. `src/pokeagent/grind/solo_viable.py` <!-- new: src/pokeagent/grind/solo_viable.py -->: solo-viability and the nurse cost (4.1, 4.2).
2. `src/pokeagent/grind/xp_buckets.py` <!-- new: src/pokeagent/grind/xp_buckets.py -->: bucketed measured xp/min (4.4).

May grow (and only by the listed amount): `grind/points.py` (288; capped at +10 so it stays at or under 300; no automated size guard covers `grind/`, so you must report `wc -l` for it); `explorer/grind_episode.py` (284; at most +12); `explorer/behaviours/switch_out.py` (218; at most +8). Do not grow any other file. Check `wc -l` before and after.

## 4. The work

### 4.1 Solo-viability (pure, `grind/solo_viable.py`)

```python
SOLO_MIN_WIN = 0.95   # chance-weighted share of encounters the trainee wins alone
SOLO_MARGIN = 0.30    # mean HP fraction left after those fights (= readiness.MARGIN)

def encounter_mix(kb, map_id) -> list[tuple[str, int, float]]:  # [(species, level, weight)], weights sum to 1
def solo_verdict(trainee: Combatant, kb, map_id) -> tuple[float, float] | None:  # (win_rate, mean_hp_left) or None
def is_solo_viable(trainee: Combatant | None, kb, map_id) -> bool
```

`encounter_mix`: from the raw `wild_by_map` slots and `slot_chances()`, one row per grass slot `i`: `(species, level, slot_chances()[i])` with the slot's own exact level, taken from `table(kb, "wild_by_map")[str(map_id)]["grass"]` (rows `[level, species]`, the same iteration `encounters.species_on` does); rows for the same species and level are summed. No min/max splitting. `solo_verdict`: for each mix row, `foe = trainer_mon(species, level, kb)`, `r = readiness.fight([trainee], [foe], chart, moves)`; a win is `r >= 0`; `win_rate` = weights of wins, `mean_hp_left` = weight-averaged `r` over wins (0 when no wins). Return None when the mix is empty, `moves` is empty, or any `trainer_mon` is None: **missing data means NOT viable (return None / False), never a guess, never "viable by default"**. `is_solo_viable` = verdict present and `win_rate >= SOLO_MIN_WIN` and `mean_hp_left >= SOLO_MARGIN`. A Magikarp (only SPLASH) loses every duel (`best_move` damage 0), so it is never viable: add that as a test, it keeps the Magikarp plan on the switch trick.

**Why these first values:** `SOLO_MARGIN` reuses `readiness.MARGIN` (0.30), the HP the repo already demands on the mons that fought before a boss, so no new number to defend. `SOLO_MIN_WIN = 0.95` is above the atlas prior `PRIOR_WIN = 0.92` (`grind/atlas.py:37`) on purpose: a solo trainee that loses 1 fight in 12 blacks out inside one `GRIND_BATTLES = 25` session. Both are named constants for a run to tune; do not make them config.

### 4.2 `choose()` for a trainee that is not the fighter

"Not the fighter" = `trainee_slot` is given and `party_levels[trainee_slot]` is below the top party level. All the new logic lives in `solo_viable.py` / `xp_buckets.py`; `points.py` gets only a hook: keyword-only `rank=None` on `choose` and `_best` (a callable `rank(point, score) -> sort key or None`, None = point not eligible for the preference), used as `key = rank(p, score) if rank else (-score, p.map_id)`, plus `xp = xp_buckets.measured_for(...)` in place of the measured-xp line (4.4) and the `trainee_level` kwarg of `episode_result`. `solo_viable.make_rank(viable, nurse_steps, maps, current_map, ...)` builds the closure with the preference key, the nurse penalty and the travel cap below. `rank=None` = today's behaviour exactly (every existing test unchanged). `grind_episode` computes `viable` (`{map_id: (win_rate, mean_hp_left)}` via `solo_verdict`) and `nurse_steps` and passes `rank=make_rank(...)`.

- **Preference:** the rank key becomes `(not viable[map], -score, map_id)` so any solo-viable point beats any non-viable one; ties and non-viable points are ordered by today's score, unchanged.
- **Nurse cost (new term, in `solo_viable.nurse_penalty`):** `round_trip = 2 * nurse_steps` (nearest `POKECENTER_MAPS` map by `travel_steps(maps, point_map, center)`, else `center_cost_frames / frames_per_step`, else `FAR_TRAVEL` = no known nurse); `battles_per_min = atlas.STEPS_PER_MIN / atlas.PRIOR_BATTLE_STEPS`; `heals_per_min = battles_per_min * (1 - mean_hp_left) / (1 - train_route.MIN_HP_FRACTION)` (a heal is wanted each time the trainee drops under half); penalty = `xp_per_min * min(1, heals_per_min * round_trip / atlas.STEPS_PER_MIN)` (the fraction of grinding time spent walking to the nurse, so it is in xp/min units). `solo_viable.py` may not import `explorer`; it takes plain numbers and a `maps` dict.
- **Hard travel cap:** `MAX_TRAVEL_STEPS = 320` (10 map crossings at `HOP_STEPS = 32`, about an eighth of `GRIND_STEPS = 2500`). A point whose `travel_steps` from here exceeds it is not eligible for the solo preference.
- **Kept:** the `only_maps` stage allow-list (`stage_maps.PRE_BROCK` is untouched) and the band fallback (`use_band=False` retry). If no point survives the cap and preference rules, the result is exactly today's `_best(...)` answer, so a trainee never gets "no point fits" where it would have got one before.

`grind_episode._try_start` computes `viable`/`nurse` for the points in `only_maps` (or all points) with `our_party(ctx.emu, ROM_KB)[...]` for the trainee (guard: if `len(our_party(...)) != len(read_party(...))` the indices are not aligned, so skip the new logic and call `choose` as today) and passes them. It stores `ep["solo"] = viable.get(pt.map_id, False)` and `ep["lvl0"] = lvl`, and logs the verdict (win rate, HP left) in the existing `[grind episode] start` line.

### 4.3 Fighting mode: one hook

When `ep["solo"]` is true the trainee leads and stays in; otherwise today's switch-in behaviour. The lead part already works (`want_home` exp rotation puts the breaker at slot 0). The ONE hook is `switch_out.trainee_out` (called by both `applies` and `step`, so no other change): after it computes `t`, `return None` when `grind_episode.active(ctx)` has `ep.get("solo")` and the trainee's current HP fraction is at least `team_plan.SWITCH_MIN_HP` (0.25, `knowledge/team_plan.py:27`, the same floor `switch_candidate` uses for a switch-in). Below it the switch-out runs as today (a safety net, so a lost solo fight still hands over). That 0.25 net is the ONLY in-battle guard for a mis-estimated solo fight (route trainers fought on the way, a trainee that starts the battle hurt, a crit streak). If `switch_candidate` then finds nobody fit to send in, the trainee stays in and fights on (accepted: the existing no-candidate path, `switch_out.py` ~170, already does exactly that). To make the net rarely needed, add a start gate (my call, justified): the estimate assumes a full-HP start and a fight can cost up to `1 - SOLO_MARGIN` = 70% of HP, so a trainee that enters a battle under `SOLO_START_HP = 0.6` (named, tunable) cannot be trusted to finish it. On the first hook call of a battle (`SwitchOut.applies` runs on turn one) latch it in the episode dict, not on `ctx` (context.py is at its ceiling): `ep["solo_battle"] = (ctx.battles, hp_fraction >= SOLO_START_HP)`. The trainee stays in only when the latch for this `ctx.battles` is True AND the current HP fraction is at least 0.25; otherwise the switch trick runs as today. `grind_episode._end_reason` already ends an episode on 'hurt with no potion', and the heal behaviours take over under `train_route.MIN_HP_FRACTION` (0.5). No change to `party_order.py` or `bring_out.py`.

### 4.4 Measured xp/min by trainee level bucket (`grind/xp_buckets.py`)

```python
BUCKET = 5   # levels per bucket: L5-9, L10-14, ...
def bucket_of(level: int | None) -> int | None:   # None -> None (the default bucket)
def measured_for(p, level) -> tuple[float, int] | None   # (mean xp/min, n) for the trainee's bucket, else the default bucket, else None
```

Ledger format is additive: an episode value gains an optional 4th element, the trainee level bucket: `[xp_per_min, blackouts, provenance, bucket]`. A 3-element value (every existing ledger and swarm table) belongs to the default bucket (`None`). `episode_result(..., trainee_level=None)` appends `bucket_of(trainee_level)` when given. `_recompute` and `xp_per_min_measured` stay as they are (all-bucket mean) so the swarm merge and every other reader are untouched; `SCHEMA` stays 1. In `_best`, measured xp = `measured_for(p, lvl)` when its n is at least `MIN_MEASURED`, else the existing unbucketed rule, else the prior. `_finish` passes `trainee_level=ep["lvl0"]` (use `.get`, an episode started before this change has none). `from_dict` already keeps `list(v)`, so loading an old file is a no-op; a test must prove it.

## 5. What NOT to do

- Do not change `stage_maps.PRE_BROCK`, `BAND_LO`/`BAND_HI`, `MIN_MEASURED`, the episode caps, or `readiness.py`/`team_plan.py` (the estimator is used, not edited).
- Do not rename or reorder `choose`'s existing parameters; the new ones are keyword-only with None defaults.
- Do not touch `party_order.py`, `bring_out.py`, the switch menu presses, or the Magikarp switch-training plan: a Magikarp stays on switch-in (4.1).
- Do not add a config file, a new goal, or a ledger schema bump. Do not rewrite `runs/grind_points.json`.
- Do not run the emulator, `tools/explore_demo.py`, or anything needing the ROM tables; the tests pass an explicit synthetic `kb`.
- Do not push, merge, or commit to main/master. No broad refactor, no file over 300 lines.

## 6. Tests (synthetic kb and ledgers; no ROM, no emulator)

New `tests/test_solo_viable.py` and `tests/test_xp_buckets.py` (plus two additions to `tests/test_grind_points.py` and one to `tests/test_grind_episode.py`). Build the kb as `tests/test_switch_matchup.py:11-34` does (`SYN` dict with `moves`, `type_chart`, `species_by_dex`, `learnsets`, plus a `wild_by_map`).

1. `test_encounter_mix_weights_sum_to_one_and_split_levels`: weights sum to 1.0; a map with slots `[3,"WEEDLE"],[5,"WEEDLE"],[4,"PIDGEY"]` (and the rest) yields each slot's own level weighted by its `slot_chances()[i]`, with no row at an unlisted level.
2. `test_strong_trainee_is_viable_on_a_weak_map`: a L12 CHARMELEON vs a map of L3-5 WEEDLE: verdict win_rate 1.0, `is_solo_viable` True.
3. `test_weak_trainee_is_not_viable_where_it_loses`: a L4 trainee vs L8-10 mons: `is_solo_viable` False.
4. `test_missing_data_is_not_viable`: empty `moves`, an unknown species, an empty map row, and `trainee=None` all give False/None (never True).
5. `test_magikarp_is_never_viable`: a SPLASH-only trainee is False on the easiest map.
6. `test_threshold_boundaries`: patch `SOLO_MIN_WIN`/`SOLO_MARGIN`; a verdict just under each is False, just at/over is True.
7. `test_choose_prefers_viable_point_over_higher_score`: two in-band points, the lower-score one viable: it is chosen; flip `viable` and the higher score wins.
8. `test_choose_without_viable_is_unchanged`: `viable=None, nurse=None` returns exactly what the old tests expect (the existing `test_grind_points.py` cases pass unmodified).
9. `test_nurse_penalty_scales_with_distance_and_hp_loss`: farther nurse or lower `mean_hp_left` gives a larger penalty; penalty never exceeds `xp_per_min`; no known nurse gives the cap.
10. `test_travel_cap_excludes_far_viable_point_and_falls_back`: a viable point at `MAX_TRAVEL_STEPS + 1` is not preferred; when it is the only point the answer is today's `_best` answer.
11. `test_stage_allow_list_and_band_fallback_still_hold`: a viable point outside `only_maps` is never chosen; the `use_band=False` fallback still fires (mirror `test_grind_points.py:145,158`).
12. `test_bucket_of_and_measured_for`: L9 -> 5, L10 -> 10, None -> None; the trainee's bucket wins when it has `MIN_MEASURED` episodes, else the default bucket.
13. `test_old_ledger_loads_into_default_bucket`: a saved 3-element episode file round-trips through `GrindLedger.load` and `save` byte-for-byte in that element; `xp_per_min_measured` equals the old mean.
14. `test_merge_keeps_bucket_and_stays_idempotent`: `merge_point` of a 4-element episode keeps the bucket; merging twice changes nothing.
15. `test_episode_start_records_solo_and_level` (in `test_grind_episode.py`): the started `ep` has `solo` and `lvl0`.
16. `test_trainee_out_stays_in_when_solo` (new, same file or `test_switch_matchup.py` style with a patched ctx): `trainee_out` is None with `ep["solo"]` true, a battle that started at 0.6+ HP and current HP at or above 0.25; it returns the slot when current HP is under 0.25, when the battle started under 0.6 (latch False), and when `solo` is false/absent.

## 7. Verification

Interpreter confirmed on this branch (2026-11-12): `uv run python --version` prints `Python 3.12.12`. Baseline on origin/main 3215258, real output:

```
uv run pytest tests/test_grind_points.py tests/test_grind_episode.py tests/test_switch_matchup.py tests/test_party_order_matchup.py tests/test_explorer_behaviours.py -q
81 passed, 1 warning in 1.97s
```

After the work, the same command plus the new files must pass with no failures and no fewer than 81 + the new tests:

```
uv run pytest tests/test_solo_viable.py tests/test_xp_buckets.py tests/test_grind_points.py tests/test_grind_episode.py tests/test_switch_matchup.py tests/test_party_order_matchup.py tests/test_explorer_behaviours.py -q
```

`wc -l src/pokeagent/grind/points.py src/pokeagent/explorer/grind_episode.py src/pokeagent/explorer/behaviours/switch_out.py src/pokeagent/grind/solo_viable.py src/pokeagent/grind/xp_buckets.py`: each file at or under 300 and within its allowance in section 3.

## 8. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. No installs, downloads or fetches. Never read outside the working directory. Do not search, glob, or hunt: if something expected is missing, stop and write what in the Status row.
- Test command is `uv run pytest ...` as in section 7. Never bare `python` or `python -m pytest`.
- Never commit to main/master, never push, never deploy. Work stays on the `directive/<slug>` branch. Only Claude or Robert merges.
- Create no scratch or debug files (deleting is denied in the sandbox); if one is needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row rather than trying another way around it.
- Status row: Done only when every item in section 9 holds; Blocked with the reason otherwise.

## 9. Completion criteria

- [ ] `grind/solo_viable.py` and `grind/xp_buckets.py` exist with the constants and functions in 4.1, 4.2, 4.4; missing data answers not-viable.
- [ ] `choose()` with the new arguments prefers a solo-viable point, applies the nurse penalty and `MAX_TRAVEL_STEPS`, keeps the allow-list and band fallback; with both new arguments None every existing test passes unmodified.
- [ ] `trainee_out` is the only fight-mode hook; a solo episode does not switch the trainee out above 0.25 HP.
- [ ] A 3-element ledger loads and saves unchanged; new episodes carry the bucket; the swarm merge is idempotent.
- [ ] The section 7 command passes; no file over 300 lines or over its allowance; no change outside section 3.
- [ ] Committed on the `directive/<slug>` branch; Status row updated.

## 10. Report

Findings first: the `choose` and `_best` lines you changed and the hook line. Then the real output tail of the section 7 pytest command and the `wc -l` table. Then the final constants, any test you could not write as specified, and anything unsettled (for example, how `grind_episode` reaches the ROM kb without a new import). Do not claim real-ROM behaviour works.

## Required from User

Claude runs a real-ROM hands-off check before merge (Devin has no ROM): a run from `baselines/bedroom.state` to `beat_brock`, and a run from `runs/checkpoints/to_pewter.state` to `to_mt_moon`. Claude compares the grind episodes' xp/min (`runs/legs/grind_drills.jsonl`) and the switch counts (`switch_train` lines in the decision log) against today's runs, and checks that the pre-Brock allow-list still holds. Nothing is needed from Robert.

## Forbidden Actions

- Merge, push, deploy, or touch a protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Edit live config, `runs/`, checkpoints, or `maps.json`.
- Publish a ROM or save state anywhere (hard rule, 2026-11-08).
- Start the emulator or `tools/explore_demo.py`, in a shell or anywhere else.

## Sandbox needs

Read/write inside this worktree only; `uv run pytest` with the existing `.venv`. No network, no installs, no ROM, no access to `runs/`.
