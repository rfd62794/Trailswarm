# Go-Explore for PokeAgent: an archive of returnable cells (2026-11-14)

Status: design draft, no code. Needs Robert's approval of this doc before any slice starts. Phase 2 of Go-Explore
(robustify / distil into a policy) is out of scope; see the last section. Paths are under `src/pokeagent/` unless shown.
Limits (house rules): new modules < ~120 lines with their own tests; explorer files <= 300 lines; no lines added to
`explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`. Loop guard untouched.

## 1. Why

Seed 12, heal_cerulean -> beat_misty, 12000 steps (see `docs/plans/training-controller-2026-11-13.md` section 1): 46% of steps
went to training trips pinned to maps the agent never reached (VIRIDIAN_FOREST), beat_misty was not reached, and SHAKE (the
loop guard) took 7.2% of steps. One long run keeps paying for its own earlier mistakes: a bad trip is never undone.
Go-Explore fixes the structure, not the brain: remember every distinct place the agent has really been, go back to a good one
exactly, and spend a bounded budget exploring from there. A bad branch costs one budget, not the rest of the run.

## 2. Ground truth in the code (what we reuse)

- **Exact return is cheap.** `PyBoyEmulator.save_state` / `load_state` (`emulator.py:156`, `:160`; `load_state` also runs
  `check_state_game`). `tools/explore_demo.py:126` already does `emu.tick(60); emu.load_state(Path(a.state)); emu.tick(30)`.
  `explore_demo.py:108-109` seeds Python's `random` from `--seed`. `--stop-at-goal` (`explore_demo.py:79`, honoured in
  `explorer/press_goals.py:94` after the milestone is persisted) and `--steps` already bound a run.
- **Cell features exist.** `novelty/features.py:32` `read_snapshot(emu)` gives map, x, y, 320 bytes of event flags
  (`FLAGS_ADDR 0xD747`, `:11`), bag, party (species, level, exp, moves), hp. `features()` (`:54`) emits `t:`, `m:`, `w:`,
  `f:`, `i:`, `so:`, `ss:`, `mv:` keys with weights (`:14`, map 5.0 > flag 3.0 > item 2.0 > ... > tile 0.1).
  `NoveltyTracker.rarity` (`novelty/tracker.py:38`) is already `1/sqrt(1 + count)` over the swarm table (`runs/novelty.json`).
- **States carry provenance.** `statefp.fingerprint` (`statefp.py:28`) stores map, x, y, respawn, badges, money, party,
  frames, `source_run`; `statefp.stamp` (`:92`) writes the sidecar `<state>.fp.json`; lineage is `organic` / `synthetic` /
  `promoted` (`lineage.py:17`), read by `statefp.lineage` (`statefp.py:78`). Goals reached ride in `<state>.goals.json`
  (`checkpoint_goals.py:25,35,69`). A real checkpoint (`runs/checkpoints/beat_brock.state`) is 178,108 bytes; sidecars are
  ~170-275 bytes. The fingerprint does NOT store event flags, so a cell's flag count must come from `read_snapshot` at harvest time.
- **Eval plumbing exists.** `evaluation_ab.extract_metrics` (`evaluation_ab.py:29`) reads `decisions.jsonl` and
  `goal_frames.jsonl` for solved/steps/stalls/blackouts; `summarize` (`:68`) does the A/B; `tools/step_budget.py` gives the
  activity table and SHAKE share (`step_budget.py:21-31`); runs are deterministic (identical 12000-step runs seen).
- **Surprise to design around:** a loaded state restores the emulator, not the explorer. `ctx` and `MapMemory` are built fresh
  per process (`explore_demo.py:150-165`), `maps.json` is shared via `--maps`, and `NoveltyTracker.observe` treats its first
  read as a baseline where nothing is a find (`tracker.py:47-50`). Every return starts a cold `ctx`. This is the main
  detachment risk (D1). Also: `tools/explore_demo.py` is 391 lines, already over the 300-line rule.

## 3. Decisions

### D1. Explore policy from a returned cell
**Recommend: the existing explorer behaviours** (`explore_demo` as the inner loop), not random actions. The brain already
handles text boxes, menus, battles and heals; a random action stream would stall in dialog and the first battle (assumption,
not measured here). Reuse also keeps "a result" meaning "the agent's own play", so the A/B steps are comparable.
**Rejected: random actions (classic Go-Explore).** Needs a new action filter for text and battle state, throws the brain away.
Derailment / detachment risk: (a) a cold `ctx` loses in-run plans (training sessions, grind episodes, a pinned `train_route`);
that is partly the point (it drops the Viridian Forest trip) but the first steps after a return re-derive state from RAM;
(b) the goal ladder comes from RAM/flags and `goals.json`, so `--state` plus `seed_initial_goals` (`explorer/engine.py:49`) is
the supported entry; (c) the loop guard still fires in a bad cell and is left alone: a cell whose budget ends in SHAKE scores
low, it is not patched. Mitigation: per-return seed varies (`--seed = base + return_index`) so a cell is not replayed identically.

### D2. Cell representation
Key, all from one `read_snapshot` (no new RAM reads):
`(map_id, x // 4, y // 4, goals_reached_count, flag_popcount // 4, party_level_bucket)`.
- map + 4x4 tile block: coarse position, so nearby tiles are one cell.
- `goals_reached_count`: ladder goals reached (`ctx.goal_steps` live; `goals.json` sidecar on disk). A count, not a bitmask:
  the ladder is ordered (`goals.py:20`). **Unknown:** whether a bitmask is needed if branches reach goals in different orders.
- `flag_popcount // 4`: popcount of the 320 flag bytes, bucketed so one story flag does not split a cell but real progress
  does. **Unknown:** how many of the 2560 bits flip from non-story causes (trainer, NPC); measure in slice 1.
- `party_level_bucket`: `(max level // 5, party size)`, so a healthy L16 team and an L8 team at one door are different cells
  (the Misty floor problem).
Size estimate: ~40 visited maps x ~20 blocks x ~3 progress/level states = ~2,400 cells upper bound over many runs; one 12k-step
run likely finds a few hundred (**unmeasured**; slice 1 reports the real count offline). Rejected: exact (map, x, y), ~10x
more cells and it floods selection with tiles of one corridor.

### D3. Selection and cell score
`w(c) = progress(c) * rarity(c)`.
- `rarity(c) = 1 / sqrt(n_seen(c) + 1)`, `n_seen` = times the archive chose c (count rule; same shape as `tracker.py:38-40`).
- `progress(c) = 1 + goals_reached_count + min(5, novelty_bonus)`, `novelty_bonus` = sum of `features.weight()` (`features.py:74`)
  of keys first seen in the run that produced c; the cap stops one flag burst dominating. Plus `+1` while c's map is on the route
  to the current stage goal (existing map graph, no new planner).
- Sampling: weighted random from a seeded `random.Random(base_seed)`; deterministic.
Cell **score** (which state represents a cell): more goals reached, then fewer total emulator steps to get there; ties by
higher party HP fraction (`statefp.party_hp_fraction`, `statefp.py:108`). A better state replaces the stored one; `n_seen`
is kept. Rejected: pure novelty selection (ignores the stage goal, drifts into dead branches like the Forest trip).

### D4. Archive storage
`runs/goexplore/<run-id>/` (gitignored `runs/`): `archive.json` (key, state file, score, steps, n_seen, parent, lineage) and
`cells/<id>.state` + `.fp.json` / `.goals.json` via `statefp.stamp`. State = 178,108 bytes (measured). Worst case 2,400 cells x
~175 KB = ~420 MB; cap at 1,000 cells (~175 MB). Eviction when full: drop the lowest `w(c)` cell whose children are all gone,
never the best-score cell of any `goals_reached_count`, never one on the path to the current frontier. `archive.json` is
written atomically (tmp + `os.replace`, as `statefp.py:51-54`). States and ROMs are never pushed.

### D5. Where it plugs in
New package `src/pokeagent/goexplore/`, each file < ~120 lines with tests: `cell.py` (key from Snapshot), `archive.py` (cells,
score, replace), `select.py` (weights, seeded sampling), `store.py` (layout, eviction, atomic write), `budget.py` (steps per
return, stop rules), `runner.py` (one iteration; the only module touching an emulator or subprocess). Driver
`tools/go_explore.py` launches `tools/explore_demo.py` as a subprocess per return
(`--state <cell> --steps N --headless --seed S --stop-at-goal G`) and reads the finished run's `decisions.jsonl` /
`goal_frames.jsonl`. **Harvesting needs mid-run states.** **Unknown (verify in slice 3):** whether a periodic-save hook exists;
if not, a new `explorer/cell_dump.py` writes states every K steps, with <= 3 added lines in `explore_demo.py` (a flag).
Nothing is wired into `explorer/engine.py`; non-Go-Explore runs stay byte-identical.

### D6. Laptop limits
16 GB RAM, one heavy job at a time, one core per emulator: one return at a time, sequential, `--headless`. Default 600 steps per
return (`budget.py`, a flag). Process start + state load per return is ~2 s (**unmeasured**), small against 600 steps. The archive
in RAM is metadata only. `archive.json` is the full state, so a killed driver resumes from disk. Peak disk ~175 MB (D4).

### D7. Evaluation
A/B on seed 12 and seed 13, same stage (heal_cerulean -> beat_misty), **equal total emulator steps** (12000: plain
`explore_demo` vs Go-Explore, returns summed). Deterministic, one run per arm per seed; repeat only if ambiguous. Metrics:
1. distinct cells (D2 key; the plain arm computed offline from its snapshot stream);
2. milestone reached (beat_misty in `goal_frames.jsonl`) via `evaluation_ab.extract_metrics`;
3. steps-to-milestone (total across returns);
4. novelty discoveries per 1k steps (`runs/discoveries.jsonl`, `novelty/discoveries.py`);
5. SHAKE share and blackouts (`tools/step_budget.py`; must not rise).
Pass: more distinct cells at equal steps AND (milestone reached OR floor progress not worse). Cells alone is "interesting",
not "pass". Also: D8 holds and 0 failed tests.

### D8. Staying organic
The hard rule: a result counts only when proven organically, never from state-surgery states. Return-states are states a run
wrote (`save_state` mid-run, seeded from an organic checkpoint), so they are organic by construction, but the rule is enforced,
not assumed: the driver refuses a start state whose `statefp.lineage` is not `organic` or `promoted`; it stamps every cell
`lineage=organic` with `parent` (the chain walkable as in `lineage._descends_from`, `lineage.py:67`); no `edit_class` edit is
ever applied. A milestone is reported with its full cell chain and per-return seeds, and the organic check re-plays that chain
once from the original start before the milestone counts. **Unknown:** whether the replay is bit-exact (determinism is
observed for whole runs; a reload resets `random`, so the replay needs the logged seeds).

## 4. Slices (each mergeable, tested, gated)

1. **Offline cell census (no emulator).** `goexplore/cell.py` + a census tool over existing run logs; real cell counts for old
   seed 12/13 runs. Settles the D2 unknowns. Tests: bucketing, monotone goals count.
2. **Archive, select, store** (pure, `FakeEmulator` at `emulator.py:216`). Tests: score replace rule, seeded selection
   determinism, eviction never drops best-per-count, atomic write.
3. **Cell harvest.** `explorer/cell_dump.py` + the flag. Tests: dump on FakeEmulator; non-Go-Explore `decisions.jsonl` byte-identical to main.
4. **Driver + runner.** `tools/go_explore.py`, `runner.py`, `budget.py`. One real smoke return of `--steps 50`
   (the only ROM use in this slice, on the laptop).
5. **A/B (D7)** on seeds 12 and 13; results go in a dated note under `docs/plans/`.

Every slice: independent review, verify record for the pinned head sha, lint, full suite 0 failed (hard rule), merge commit
(not squash). Slice 5 needs Robert's read of the numbers.

## 5. What NOT to do

- No PPO, no torch, no learned policy here.
- Never publish ROMs or states (cells live in gitignored `runs/`).
- Do not touch the loop guard (`explorer/behaviours/guards.py`); a cell that SHAKEs just scores low.
- Do not change explorer decisions in non-Go-Explore runs; slice 3 proves byte-identical output.
- No lines in `explorer/context.py`, `explorer/memory.py`, `explorer/behaviours/plan_goal.py`; no wiring into `engine.py` first.
- No state surgery or `edit_class` edits to make a cell "better".
- One emulator process at a time; no full-suite or ROM runs outside a gated slice.

## 6. Phase 2 (future note only)

After the archive reaches the milestone, "robustify" means distilling the cell chain into a stable policy: the plain explorer
reaching the milestone from the start with no returns. Not planned here; the chains and per-return seeds from D8 are the data
it would need, which is why D4 and D8 keep them.
