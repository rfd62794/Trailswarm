# PokeAgent: Cut learner and capabilities - get a Cut-capable party member, then make the Cut-gated chain selectable from RAM

**Depends on:** PR #141 (`feat/hm01-cut-recognition`) merged to main. It adds the `party_move` detector (`campaign.party_knows_move(emu, move_id)`), the goals `hm01_cut`
(event flag 0xD803 bit 0) and `cut_taught` (CUT = move id 15), `behaviours/goal_talk.py`, and the teach trigger in `item_policies/policy.py`
(`hm01_cut and not cut_taught` appends the `cut` need; `hm_teach.stranded_hms` names the case "HM held, nobody can learn it"). If `party_knows_move` or `cut_taught` is missing
from your worktree, stop and write that in the Status row. **Do not list the tree recursively**; use `git ls-files`.

**Read first:** `src/pokeagent/campaign.py` (`agent_capabilities`, `reachable`, `campaign_reachable`, `selectable`, `evaluate`), `src/pokeagent/data/campaign.json`,
`src/pokeagent/goals.py`, `src/pokeagent/explorer/catch_list.py` (`catch_wanted`, `hm_table`, `upcoming_needs`), `src/pokeagent/explorer/behaviours/catch.py`,
`src/pokeagent/knowledge/encounters.py` (`where_to_catch`, `species_on`), `src/pokeagent/knowledge/hm_compat.py`, `src/pokeagent/explorer/behaviours/goal_talk.py` (the walk-and-act sibling to copy the shape of),
`src/pokeagent/explorer/behaviours/frontier.py` (the grass-seeking `training` flag), `docs/superpowers/specs/2026-11-07-unlock-layer.md` (section 1 is the capability design; this PR does only that part),
`tests/test_campaign.py`, `tests/test_goal_talk.py`.

## 1. Why this exists

PR #141 recognises HM01 and tries to teach Cut, and its author listed two follow-ups that this directive closes:
(a) With a Squirtle-line lead and a Magikarp the party has nobody that can learn Cut (`kb/hm_compat.json`: the Squirtle line and Magikarp cannot; Bulbasaur, Charmander, Oddish, Paras, Bellsprout,
Sandshrew lines can), so the teach trigger logs "no party member can learn it" and nothing acquires a learner. The catch list already says "wanted: can learn CUT" once a Cut species appears in a fight
(`catch_list.catch_wanted`), but nothing sends the agent to a place where one appears: that path is unproven.
(b) `campaign.agent_capabilities()` is env-only (`POKEAGENT_CAPS`), so every goal behind `needs: ["cut"]` (`vermilion_gym_entry` onward) stays unselectable for the segment picker even after `cut_taught` is true.

## 2. Facts (verified on the live checkout 2026-11-07; pasted because you cannot read `kb/` or `runs/` in the worktree)

**Cut-compatible species** (`kb/hm_compat.json` key `hms.cut`, generated from the ROM's BaseStats TM/HM bitfield, 26 species): BEEDRILL, BELLSPROUT, BULBASAUR, CHARIZARD, CHARMANDER, CHARMELEON,
FARFETCH?D, GLOOM, IVYSAUR, KINGLER, KRABBY, LICKITUNG, ODDISH, PARAS, PARASECT, PINSIR, SANDSHREW, SANDSLASH, SCYTHER, TANGELA, TENTACOOL, TENTACRUEL, VENUSAUR, VICTREEBEL, VILEPLUME, WEEPINBELL.
Not in it: the Squirtle line, MAGIKARP, GYARADOS, DIGLETT, DUGTRIO.

**Wild grass tables, Red** (`kb/rom_tables.json` `wild_by_map`, via `pokeagent.knowledge.encounters.where_to_catch`; `*` = Cut-compatible; the 10 slots have chances 51,51,39,25,25,25,13,13,11,3 of 256):

| map | name | grass rate | slots (level species) | Cut species: levels, chance per encounter |
|---|---|---|---|---|
| 0x10 (16) | Route 5 | 15 | ODDISH 13*, PIDGEY 13, PIDGEY 15, MANKEY 10, MANKEY 12, ODDISH 15*, ODDISH 16*, PIDGEY 16, MANKEY 14, MANKEY 16 | ODDISH L13-16, 34.8% |
| **0x11 (17)** | **Route 6** | 15 | identical to Route 5 | **ODDISH L13-16, 34.8%** |
| 0x12 (18) | Route 7 | 15 | PIDGEY 19, ODDISH 19*, MANKEY 17, ODDISH 22*, PIDGEY 22, MANKEY 18, GROWLITHE 18, GROWLITHE 20, MANKEY 19, MANKEY 20 | ODDISH L19-22 |
| 0x16 (22) | Route 11 | 15 | EKANS 14, SPEAROW 15, EKANS 12, DROWZEE 9, SPEAROW 13, DROWZEE 13, EKANS 15, SPEAROW 17, DROWZEE 11, DROWZEE 15 | none |
| 0x23 (35) | Route 24 | 25 | WEEDLE 7, KAKUNA 8, PIDGEY 12, ODDISH 12*, ODDISH 13*, ABRA 10, ODDISH 14*, PIDGEY 13, ABRA 8, ABRA 12 | ODDISH L12-14, 24.6% |
| 0x24 (36) | Route 25 | 15 | WEEDLE 8, KAKUNA 9, PIDGEY 13, ODDISH 12*, ODDISH 13*, ABRA 12, ODDISH 14*, ABRA 10, METAPOD 7, CATERPIE 8 | ODDISH L12-14, 24.6% |
| 0x3E (62) | Diglett's Cave | - | the drained table has no row for it (cave rows were not drained) | Diglett and Dugtrio are not Cut-compatible anyway |

Answer for Red from Vermilion (where `hm01_cut` is met, the S.S. Anne): **Oddish on Route 6 (map 0x11)**, directly north of Vermilion, which the agent has just walked, L13-16, about 35% per grass encounter.
Route 5 gives the same Oddish. `species_internal` ids: ODDISH = 185 (`name_of_internal`), MAGIKARP = 133.
Other facts: `agent_capabilities()` today is `frozenset(c.strip() for c in os.environ.get("POKEAGENT_CAPS", "").split(",") if c.strip())`; `seg_store._selectable(caps)` is `lru_cache`d on the frozenset;
`seg_store.selectable_goals()` calls `agent_capabilities()`; `tools/overnight.py` (the `selectable(g)` calls near lines 116 and 128), `tools/swarm.py` (near line 74) and `tools/status.py` call `campaign.selectable(g)` with no
capabilities argument, so they pick up whatever `agent_capabilities()` returns. The goal `needs` tags in `campaign.json` that mention `cut` start at `vermilion_gym_entry` (after `bicycle`).
`kb/` is gitignored and absent in your worktree: every test uses a fixture encounter table and a fixture HM table (pass dicts in; both `catch_list.hm_table` and `encounters.where_to_catch` take or can be given the data).

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

## 3. Scope (one PR, in order)

1. Capabilities from RAM and from the curriculum's own evidence: new small `src/pokeagent/unlocks.py` and `campaign.agent_capabilities(emu=None, root=None)`.
2. Learner acquisition: pure `knowledge/cut_learner.py` (pick the nearest Cut-capable wild species and map), the `cut_learner` ladder goal (between `hm01_cut` and `cut_taught`) with a settle rule, a small behaviour that takes the agent to the target map's grass, and the catch list reading the target.
3. Docs: one bullet in `docs/ROADMAP.md` "Open decisions for Robert" (no code).
4. Tests: `tests/test_unlocks.py`, `tests/test_cut_learner.py`.

## 4. The work

### 4.1 Capabilities (`unlocks.py`, `campaign.py`)

- `unlocks.capabilities(emu) -> frozenset[str]`: `{"cut"}` iff `campaign.party_knows_move(emu, 15)`; nothing else in this PR (surf/strength/flash/bike are the unlock-layer spec's later steps; do not add them). It never raises (a failing read returns the empty set).
- `campaign.agent_capabilities(emu=None, root=None)`: the union of (a) the existing env override (`POKEAGENT_CAPS`, unchanged, so tests keep working), (b) `unlocks.capabilities(emu)` when an emulator is given,
  (c) the curriculum's evidence: `"cut"` when `<root>/runs/checkpoints/cut_taught.state` exists (the checkpoint `press_goals.record_goals` writes the moment the `cut_taught` detector fires in a run; `root` defaults to the repository root,
  `Path(__file__).resolve().parents[2]`). (c) is what makes the segment picker see the capability, because the picker has no emulator.
- Callers keep working with no arguments. The segment picker and campaign gating read it through exactly these functions (named from the repo): `tools/seg_store.py::selectable_goals` (which feeds `_selectable`, cached per capability set, so a new set re-computes), `campaign.selectable` / `campaign.campaign_reachable` / `campaign.reachable` (which default `capabilities=None` to `agent_capabilities()`), and through them `tools/overnight.py`, `tools/swarm.py` and `tools/status.py`. You do not need to edit those callers; add a test that proves the effect (4.4 test 2).
- Only Cut-gated goals unlock: `vermilion_gym_entry` has `needs: ["cut"]` but the chain also contains `beat_surge` (`needs: ["cut", "puzzle"]`), `to_cinnabar`-class goals (`surf`) and others; the chain-reachability logic stays as it is, so the picker unlocks exactly the prefix of the chain whose `needs` are covered.

### 4.2 The learner goal and its target

New pure module `src/pokeagent/knowledge/cut_learner.py`:

```python
LEARNER_STEP_CAP = 6000      # steps on the stage without a Cut-capable member before the goal is settled for this run (named; tune from runs)

@dataclass(frozen=True)
class LearnerTarget:
    map: int; name: str; species: str; levels: tuple[int, int]; chance: float; rate: int

def cut_capable(party_names, hm: dict | None) -> bool
    # any party species name is in hm["cut"] (the kb/hm_compat table); hm None/empty -> False
def pick_target(here_map: int, known_maps, hm: dict, wild_by_map: dict, distance=None) -> LearnerTarget | None
    # candidates: every map in wild_by_map whose GRASS table holds a Cut-compatible species; weight = species chance per encounter x grass rate;
    # prefer maps in known_maps (the learned world, runs/maps.json keys) and the smallest distance(here_map, map) (default: abs difference of the map ids; the caller may pass a graph-path length);
    # ties: higher weight, then lower map id. None when there is no candidate (e.g. no tables).
```

Exact expected result on the Red table pasted above, with `here_map = 5` (Vermilion) and `known_maps` containing 0x10 and 0x11: Route 6 (0x11), species ODDISH, levels (13, 16), chance 0.348 (use `encounters.where_to_catch(species)` / `slot_chances()` for the arithmetic; do not hard-code 0.348). Water-only species (Tentacool, Krabby, Kingler) are NOT candidates in v1 (they need Surf): grass only.

The goal `cut_learner` (campaign.json): `{"id": "cut_learner", "name": "A party member that can learn CUT", "after": "hm01_cut", "detector": {"special": "cut_learner"}, "special": true, "needs": [], "note": "hand-coded in goals.py; settled when a Cut-compatible species is in the party, Cut is already known, the tables are unavailable, or the step cap is spent"}`;
`cut_taught`'s `after` becomes `cut_learner`. The hand-coded detector in `goals.py` (next to `buy_magikarp`; mirror `magikarp.magikarp_goal_settled` and, if the Team Readiness PR has merged, `gyarados_goal_settled`):
`cut_learner_settled(emu, st, kb)` is True when: `st` already recorded it (sticky `had_cut_learner`), or `cut_capable(party_names(emu), hm_table())`, or the party knows Cut (`party_knows_move(emu, 15)`), or `hm_table()` is empty (no ROM data: cannot judge, never block),
or `st.get("cut_learner_skipped")`. `plan_goal.py` counts steps while `hm01_cut` is met and `cut_learner` is the next unmet goal (mirror the `buy_steps` / `buy_skipped` block at the top of `PlanGoal.step`; new context fields `cut_learner_steps: int`, `cut_learner_skipped: bool`) and sets the skip with a log line once `LEARNER_STEP_CAP` is exceeded,
so the stage can NEVER block the route. Party species names come from `kb` `name_of_internal` via `explorer.kb.ROM_KB` (the same lookup `catch.py` uses); with no `ROM_KB` the goal is settled.

### 4.3 Getting the agent to the grass, and the catch list

- `ctx.learner_target: LearnerTarget | None` (new context field). A tiny behaviour `src/pokeagent/explorer/behaviours/learner_hunt.py` (sibling of `goal_talk.py`, same shape: `applies` / `step`, registered next to `GoalTalk` in `behaviours/__init__.py` after the planner and before `frontier`): applies when `hm01_cut` is met, `cut_learner` is unmet, not skipped, not battling, no text box. On first application compute
  `pick_target(...)` with `known_maps` from `ctx.mem.data["maps"]` and store it (logged once: `[cut_learner: ODDISH on Route 6 (0x11), L13-16, 35%/encounter]`). Not on the target map: walk the learned graph to any tile of it
  (`WorldGraph(ctx.mem.data["maps"]).path((m, x, y), lambda n: n[0] == target.map)`, the same call `planner.py` uses; no route known -> return None and let exploration go on). On the target map: set `ctx.hunt_grass = True` and return None; `frontier.py` reads it as one more reason for grass seeking (a single added term in its existing `training` expression where it chooses `grass="seek"`). The existing `Catch` behaviour then does the rest, because `catch_list.catch_wanted` already answers "can learn CUT" for a Cut species when `cut` is in `upcoming_needs(goals)` (true while any later goal lists the capability) and nobody in the party covers it.
  When the Poke Ball count is 0 the behaviour does nothing new (the existing restock logic buys balls; do not add shopping). Clear `ctx.hunt_grass` when the goal is settled.
- Catch list: add `catch_list.catch_target_map(goals, party, hm, wild_by_map, here_map, known_maps) -> LearnerTarget | None` (thin wrapper: None unless `cut` is the first upcoming need that nobody covers; else `pick_target(...)`). `learner_hunt` uses it, so the "target map" lives with the catch list's other rules. No change to `catch_wanted` or to `catch.py`'s throwing logic (no new catch mechanics).
- After the catch the existing teach trigger fires (`hm01_cut and not cut_taught` -> `hm_teach`), and `cut_taught` follows. Do not edit `goal_talk.py` or `hm_teach.py`.

### 4.4 Docs

`docs/ROADMAP.md`, section "Open decisions for Robert": append one bullet: `- Starter policy and Cut: Bulbasaur and Charmander lines can learn CUT (kb/hm_compat.json); the Squirtle line cannot, so a Squirtle run must catch a Cut-capable species (the cut_learner goal does this: Oddish on Route 6, ~35% per encounter). Fixing the starter would remove that detour; the choice is Robert's.` No code change for the starter.

## 5. What NOT to do

- No new catch mechanics (throwing, weakening, ball buying stay as they are). No cut-tree / walk-grid / tile work (that is the unlock-layer spec, later steps). No edits to `goal_talk.py` or `hm_teach.py`. No starter-policy code.
- Do not edit `ship_gate.py`, `planner.py`, `planner_east.py`, `planner_checkpoint.py`.
- Do not add capabilities other than `cut`; do not change any goal's `needs`; do not change `POKEAGENT_CAPS` semantics.
- No emulator runs, no `uv run pokeagent ...`; no ROM or `kb/` in the worktree. No new dependencies; each module under 300 lines.

## 6. Verification

- `uv run pytest -q tests/test_unlocks.py tests/test_cut_learner.py` - new tests (fixtures, no `kb/`):
  1. `unlocks.capabilities`: a `FakeEmulator` party where a member knows move 15 (use the offsets of `tests/test_campaign.py::test_party_move_detector_reads_every_member_and_slot`) -> `{"cut"}`; nobody knows it -> empty; a bench slot past the party count does not count.
  2. `agent_capabilities` with `POKEAGENT_CAPS` unset and a `tmp_path` root: no `cut_taught.state` -> no `cut`; with `runs/checkpoints/cut_taught.state` -> `cut`; env `cut` still works; the union is a frozenset. Then `campaign.selectable("vermilion_gym_entry", agent_capabilities(root=tmp))` is False before and True after (its chain prefix needs only `cut`), while `selectable("beat_surge", ...)` stays False (it also needs `puzzle`).
  3. `pick_target`: a fixture `wild_by_map` shaped like the table in section 2 (Routes 5, 6, 7, 11, 24, 25) and fixture `hm = {"cut": [...]}`: from Vermilion (5) with Routes 5 and 6 known -> Route 6, ODDISH, (13, 16), chance within 0.01 of 0.348; with only Route 24 known -> Route 24; Route 11 alone -> `None`; empty tables -> `None`; a water-only Cut species is never chosen.
  4. `cut_capable` with a Squirtle-line + Magikarp party -> False; with an ODDISH added -> True; `hm` None -> False.
  5. Goal detector: `check_goals` on a `FakeEmulator` Squirtle + Magikarp party with `hm01_cut` met: `cut_learner` False; adding Oddish (species 185) -> True and sticky; the party knows Cut -> True; `hm_table()` monkeypatched to `{}` -> True. `GOALS` order is `hm01_cut`, `cut_learner`, `cut_taught`, `pokemon_fan_club`.
  6. Settle cap: drive the `plan_goal` counter (or the extracted helper) past `LEARNER_STEP_CAP` -> `cut_learner_skipped` True and the goal reads True; below the cap it stays False.
  7. `learner_hunt.applies` is False before `hm01_cut`, when `cut_learner` is met, while battling, or when skipped; `catch_target_map` returns a target only when `cut` is an uncovered upcoming need.
- Update, do not delete, existing assertions that the goal ladder is exactly the old list or that `cut_taught` follows `hm01_cut` (`tests/test_campaign.py`, `tests/test_goal_order.py` `EXPECTED` if affected, anything the full run shows).
- `uv run pytest -q` green; paste the before/after tails.
- **Controller validation (not Devin):** on the laptop, from `runs/checkpoints/hm01_cut.state` with a Squirtle + Magikarp party, a headless segment `hm01_cut -> cut_taught`: the agent should reach Route 6, catch an Oddish, teach Cut; then `tools/segments.py` should list the Cut-gated segments.

## 7. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation is rejected and ends the run. No installs, downloads or fetches.
  Never read outside the worktree.
- **Do not run the `pokeagent` entry point (the sandbox refuses it). Do not list the directory tree recursively; use `git ls-files`.
  Do not read outside the worktree. Create no scratch files; deleting is denied. If something expected is missing, stop and write that in the Status row.**
- Do not search, glob or hunt for a missing file or fact: stop and say so in the Status row.
- Test commands are exactly `uv run pytest -q` and `uv run pytest -q tests/<file>`. Never bare `python`.
- Work only on branch `directive/pokeagent-cut-learner-and-capabilities-directive`. Never commit to `main`; never push; never deploy. Commit on the branch as you go.
- Create no scratch or debug files (deleting is denied and ends the run). If one is truly needed it goes under `.devin-scratch/` and stays.
- If a tool call is genuinely blocked, stop and write why in the Status row; do not try another way around it.
- SOLID/SRP/KISS is a hard rule here: small new modules (under 300 lines), no new dependencies.

## 8. Completion criteria

- [ ] `unlocks.capabilities`; `agent_capabilities(emu=None, root=None)` with env override, RAM and the `cut_taught` checkpoint evidence; the Cut-gated prefix of the chain is selectable after `cut_taught`
- [ ] `knowledge/cut_learner.py` (`pick_target`, `cut_capable`, `LEARNER_STEP_CAP`); `cut_learner` goal in `campaign.json` + hand-coded settled detector in `goals.py`; step cap in `plan_goal.py`
- [ ] `behaviours/learner_hunt.py` registered, one added term in `frontier.py`, `catch_list.catch_target_map`; no change to `catch.py`'s throwing, `goal_talk.py`, `hm_teach.py`
- [ ] ROADMAP bullet; both new test files pass; `uv run pytest -q` green (paste the tail); `git diff --stat main` pasted; no forbidden file changed
- [ ] Status row moved to Review with the branch name

## 9. Report

Findings first: test tails (before/after), `git diff --stat`, the final signatures, exactly where the capability set is read by the segment picker (functions), the target `pick_target` returned on the fixture, every existing test updated, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-cut-learner-and-capabilities-directive |
| Base branch | - |
| Base commit | 45b74bf7374d6d45b4a3c440907db823540d9843 |

**Status log**
- 2026-11-07 13:42 · robert-claude-laptop · none → Draft — Claude 2026-11-07: cut_learner goal + RAM/checkpoint capabilities; depends on PR #141
- 2026-11-07 13:42 · robert-claude-laptop · Draft → Queued — Claude 2026-11-07; depends on PR 141 merging first; lint_override: dispatch-path-missing/verification-path-missing on new modules/tests and gitignored kb/ evidence paths
- 2026-11-07 13:43 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing / verification-path-missing on greenfield files (unlocks.py, cut_learner.py, learner_hunt.py, tests) and gitignored evidence (kb/hm_compat.json, kb/rom_tables.json); known false positives. Dependency PR #141 merged as 10a3aa5.
- 2026-11-07 13:43 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-cut-learner-and-capabilities-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6VN5KPHQKJM3BAFX4QR816S
- 2026-11-07 13:48 · dispatcher · launched pid=22692; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-cut-learner-and-capabilities-directive; provisioned: uv sync --frozen
<!-- queue:end -->
