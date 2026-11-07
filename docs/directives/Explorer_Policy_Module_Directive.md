# PokeAgent: explorer policy module - the spike becomes framework code; the LLM backend becomes one policy among several

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md`, `goals.json`, and the spike itself:
`tools/explore_demo.py`, `tools/explore_plan.py`, `tools/review_runs.py`. Build step 11. Merge order, stop if
any is missing: **Map_Memory (`src/pokeagent/mapmem.py`), then Text_Box_Awareness (`textbox.py`), then Viewer
(`viewer.py`, `steering.py`), then Mcp_Server (`mcp_server.py`)**, then this directive. If one of those four files is
absent from your worktree, stop and write that in the Status row. Also needed from `main`: `agent.py`, `prompt.py`,
`decision.py`, `backend.py`, `runlog.py`, `console.py`, `cli.py`, `ram.py`, `emulator.py`, `screentext.py`,
`names.py`, `hexmap.py`. **Do not list the tree recursively** (`Get-ChildItem -Recurse`, `find`, `tree` are refused
by the sandbox and end the run); use `git ls-files`.

## 1. Why this exists

Robert asked (2026-11-02): "How do we take the Spike Test and incorporate it directly as the Agent, or feed it into
the Main System?" Tonight `tools/explore_demo.py` reached all four first goals in one run (potion step 14, left house
42, first pokemon 116-132, won the rival battle 264) and Robert approved `goals.json` as the campaign plan. The answer:
**the spike's logic moves into framework modules; the spike shrinks to a wiring script; the LLM backend becomes one
`Policy` among several.** The rule-based policy is the fast, free, repeatable driver; the LLM is the fallback for
situations the rules do not know, and what it answers is stored so the next time costs nothing. This is a MOVE and a
re-seat, not a redesign: the spike's behaviour is the specification. Where this text and the spike disagree on
behaviour, the spike wins; the function names cited below are the source of truth. Port them, do not redesign.
Facts you build on: `0xD31D` bag, `0xD35E` map, `0xD163` party count (verified 0 -> 1), `0xD057` battle (nonzero, 2
for a trainer), `0xC3A0` 20x18 tile map, border tile `0x79`, menu cursor `0xED`; others in `goals.json` are marked
unverified. Test command `uv run pytest -q` (Python 3.12). No ROM, window or new dependency in tests.

## 2. Scope

Each new module under 300 lines (split `policies/explorer.py` into `explorer_menus.py` + `explorer_moves.py` if needed):

1. `src/pokeagent/policy.py` - `Policy` protocol, `Observation`, `LLMPolicy`, `build_observation(emu, ...)`.
2. `src/pokeagent/policies/__init__.py`, `explorer.py` (+ `explorer_menus.py`, `explorer_moves.py`).
3. `src/pokeagent/planner.py` (`WorldGraph`, `plan_step`, `interaction_spots`) and `goals.py` (goal detection).
4. `src/pokeagent/demos.py` - interventions, demonstrations, best-path replay.
5. `src/pokeagent/review.py` + `pokeagent review` subcommand.
6. `cli.py` (`run --policy`), `agent.py` (policy-driven loop), `console.py` (the spike's line formats).
7. Demo integration (section 3.7): `tools/explore_demo.py` shrinks; `tools/explore_plan.py` and `tools/review_runs.py`
   become re-export shims, or are deleted once nothing imports them. 8. Tests, a README paragraph.

## 3. The work

### 3.1 `policy.py`

```python
@dataclass
class Observation:
    state: GameState; tilemap: bytes; textbox: TextBoxInfo | None; screen_lines: list[str]; in_battle: bool
    goals: dict[str, bool]; memory: MapMemory; step: int; facing: str; last_dialog: list[str]
class Policy(Protocol):
    def choose(self, obs: Observation) -> Decision: ...
```

`Decision` is the existing one (`decision.py`; `thinking` carries the spike's "why" line, `button` may be `"NONE"` to
mean "wait this step"). `LLMPolicy(backend, log)` wraps `build_prompt` + `Backend.choose` + `parse_reply` exactly as
`Agent.run` does today, so `pokeagent run --backend claude` is unchanged: same prompt bytes, same `BackendError` ->
`Decision("NONE", error=...)`, same failure counting. `screen_lines` is the spike's `frame_lines(tilemap)` when a box
is open, else `[]` (port `frame_lines`, `box_open`, `is_menu`, `box_text` into `textbox.py` helpers only if that module
lacks equivalents; otherwise reuse and diff the outputs in a test). `last_dialog` is the spike's `st["dialog"]`
(fragments since the box opened, max 12). The policy object holds its own per-run state (what the spike kept in
`st`: `facing` excepted, which the Agent supplies); no globals.

### 3.2 `policies/explorer.py` - port `agent_step` and its helpers

Behaviours to preserve exactly (spike names in brackets), in this priority order:
1. **Settle/readiness** [`agent_step` top]: `settle` countdown after a warp; overworld-only wait while the tile map
   changed within 8 frames or `wJoyIgnore` `0xCD6B` is set, max 4 s then act and log; never wait while a box/menu is
   open (the blinking cursor stalled the 23:20 run). The stable-frame counter moves to `Agent`/`Observation` input
   (a `frames_stable` attribute on the policy, fed by `Agent` each tick); return `Decision("NONE")` while waiting.
2. **Battle** [`in_battle` branch]: `0xD057 != 0` or "FIGHT" on screen -> press A (FIGHT, move 1); count battles,
   remember `battle_pos`; on exit, `won = party > 0 and position == battle_pos` (a blackout warps you away),
   `battles_won += 1`. Keep as one small method; Battle_Awareness replaces it later.
3. **Box handling** [`box_streak`]: menu open 12 presses -> B; any box 60 presses -> B; dialog -> A.
4. **Menus** [`is_menu` branch]: YES/NO via `yesno_answer` + `YESNO_RULES` (nickname/name/toss/deposit/release/give
   up/run -> NO, default YES; starter offered -> YES if `--starter` is `any` or equals the offered name, else NO; the
   question is context = last 4 dialog fragments + on-screen question); move the cursor with DOWN/UP until it sits on
   the answer, then A. Goal-aware choice via `goal_menu_choice` + `GOAL_MENU` (containment match, never "CANCEL").
   Otherwise explore: choose the cursor option if not in `tried`, else DOWN, else B.
5. **goto** [`st["goto"]`]: route with `WorldGraph.path`; clear on arrival or no route (log both).
6. **Demonstration replay** [`replay`, `matching_demo`, `replayed_here`]: same `(map,x,y)` and screen as a recorded
   demo -> replay its buttons once per 50 steps per spot.
7. **Plan** [`plan_step`]: goal-directed step over the `WorldGraph`.
8. **Explore** [`MapMemory.choose`]: untested wall -> A; else least-visited non-blocked direction; warps scored
   `warp_taken * 3`; all blocked -> A. This logic belongs in `mapmem.py` only if Map_Memory already has it; else put it
   in `explorer_moves.py` and read `blocked`, `warps`, `warp_taken`, `visited`, `interactions` from `MapMemory`.

`MapMemory` must keep every field the spike writes (`warp_taken`, `interactions.{count,text,presses,menus,choices,
effects}`, `demos`); if the merged `mapmem.py` lacks one, add it there (spike behaviour wins) and say so in the Report.
`Agent` owns `learn`/`interact`/`visit` bookkeeping (the spike's `do_press`), including the two-failures-confirm rule
for walls, `settle_position` (tick 8 frames until stable for 3 reads, +60 frames after a map change), and the
`transitions.jsonl` record with every extra the spike writes: `battle_flag`, `ahead_tiles`, `ram_diff`, `sprites`,
`trigger`, `waited`. Do not drop a field.

### 3.3 `planner.py` and `goals.py`

`planner.py`: move `WorldGraph`, `interaction_spots`, `plan_step` unchanged (same signatures, same strings). Add
best-path use from 3.4 as a separate function `best_path_step(...)`, called before `plan_step`. `goals.py`:
`load_goals(path) -> list[Goal]` reads `goals.json` (`id`, `name`, `done`, `verified`, `best_steps`);
`evaluate(emu, goals, st) -> dict[str, bool | None]`. Detector types and their meaning:
`bag_has_item` / `bag_lacks_item` (`0xD31D` count, pairs from `0xD31E`; item ids are hex strings; count 1-20 guard as
the spike's `check_goals`), `map_is`, `map_not_in` (`0xD35E`; `left_house` stays sticky once true, as the spike's
`goal_left_house`), `party_count_gt` (`0xD163`), `battle_ended_same_tile` (the explorer's `won` rule; the goal
`won_rival_1` also requires `party_count_gt`), `start_menu_has` (needs the START menu decoded from the tile map; return
`None` unless the menu is open), `badge_bit` (`0xD356`, unverified), `party_hp_full` (`0xD16C`/`0xD18D`, unverified),
`party_mon1_level_gte` (`0xD18C`, unverified). Rule: a detector whose goal has `"verified": false` returns `None`
(unknown), never `False`; `"partial"` evaluates but logs once. The planner treats `None` as not done and logs
`[goal X: unknown (unverified detector)]` once per run. The old ids `first_pokemon` / `won_battle` map to
`goals.json` ids `first_pokemon` / `won_rival_1`; keep the spike's four console names as aliases so the console and
`milestones.json` lines are unchanged. Hard-coded `GOALS` lists disappear; the order is the file's order.

### 3.4 `demos.py`

Port `record_intervention`, `close_episode`, `matching_demo`, replay as a class `DemoBook(mem, path="runs/
interventions.jsonl")`. Episodes start on the first `human` or `claude` press and close when an `agent` press follows
or at shutdown; each is appended to `runs/interventions.jsonl` and to `maps.json` `maps[<id>].demos` (last 20, keys
`at, facing, screen, buttons, achieved, source, end`). The console line is `[learned a <source> demonstration: N
presses from (m, x, y) -> goals]`. **Best-path replay:** `runs/best_paths.json` (written by `pokeagent review`) holds
per goal `{run,length,start,end,buttons,sources}`. `best_path_step(goal_id, pos, progress)` returns the next button when
the player stands at the recorded `start` of the next unmet goal's segment (and then follows `buttons[i]` while each
press is expected to land on the segment, checked against the recorded `to` positions when available); the moment the
position drifts off the script it returns `None` and the planner falls back to `plan_step`. A segment is tried at most
twice per run so a bad script cannot loop. Source is tagged `agent` with why `best path for <goal> (i/N)`.

### 3.5 `review.py` and `pokeagent review`

Move `tools/review_runs.py` into the package unchanged in output: goal steps best/median/worst, fastest segment per
goal, waste (blocked moves) by source, per-situation outcomes, never-worked actions (3+ blocked, one outcome). Writes
`runs/review.json` and `runs/best_paths.json`; prints the same lines. `pokeagent review [--runs runs]`. Goals come
from `goals.json`, not a hard-coded list. It must read both `explore-*` and `<timestamp>` run dirs.

### 3.6 CLI, Agent, hybrid

`pokeagent run --policy explorer|claude|hybrid [--starter any|random|bulbasaur|charmander|squirtle] [--goals
goals.json] [--maps runs/maps.json]`. Default `claude` (so existing invocations are unchanged); `--backend` applies to
`claude`/`hybrid`. `explorer` needs no `--steps` guard (it costs nothing); `claude` and `hybrid` keep the guard.
`Agent` takes `policy: Policy` instead of `backend` (keep `Agent(emu, backend, ...)` working by wrapping the backend
in `LLMPolicy` when no policy is given, so the Agent tests stay green), and gains the Viewer's `before_step` and the
log field `source` (`agent` | `human` | `claude`), plus the `steering` pause check. **Hybrid:** the explorer drives.
It raises an `Unknown(reason)` signal for: a menu with no rule (every option tried, nothing goal-relevant), a YES/NO
whose context matches no rule except the default, a battle state outside the FIGHT rule (cursor not on FIGHT after
3 presses), or 8 consecutive no-progress steps (no position change, no new text, no goal). On `Unknown`, `Agent`
asks `LLMPolicy.choose` ONCE, presses its button with `source="claude"`, and the `DemoBook` records the press
sequence that follows as a demonstration so the next identical situation replays free. Budget: at most 1 LLM call per
20 steps; over budget, the explorer's default is used. Control API: the spike's HTTP `ControlServer`
(`/status /goals /screen /screenshot.png /map /press /pause /resume /goto /say`) is **retired once the MCP server
exposes the same verbs** (`press, state, pause, resume, goto, explore` are in the MCP directive); until then the
viewer may keep it, and `explore_demo.py` keeps starting it behind `--control-port` (0 disables). `goto` becomes an
Observation-visible request on the policy (`policy.goto = (m,x,y)`); MCP's `explore(steps)` runs `Agent` steps with
the explorer policy.

### 3.7 Demo integration

`tools/explore_demo.py` shrinks to **under 80 lines**: parse args (`--rom --state --maps --steps --frames-per-step
--control-port --starter --goals`), build `PyBoyEmulator` + `ExplorerPolicy` + `Viewer`, run `Agent`. Everything the
spike did must still happen: the same console lines (`--- step N/M  map=0x.. pos=(x,y) facing F  party= bag=  goals:
potion+ ...`, `learned here: ...`, `thinking:`/`human:`, `button: ... result: ...`, `*** GOAL REACHED: g at step N ***`,
the `[waiting...]`, `[ready after ...]`, `[battle over - WON ...]`, `[arrived at ...]` lines), the same files
(`runs/maps.json` every 10 steps and at shutdown, atomically; `runs/explore-<ts>/transitions.jsonl` with every extra
field; `runs/interventions.jsonl`; `runs/milestones.json` with `species_byte` and `wanted` for `first_pokemon`), the
same window. Move the console formatters into `console.py`. **Compatibility test:** drive a scripted FakeEmulator
session (bedroom -> PC -> stairs) through `Agent` + `ExplorerPolicy`, and compare the set of keys in each
`transitions.jsonl` line and the schema of `maps.json` (map keys, `interactions` entry keys, `warp_taken`, `demos`) to
fixtures captured from the spike's output (write the expected key sets verbatim into the test; do not import the
spike). Any difference fails the test.

## 4. What NOT to do

- No redesign: do not change rule order, thresholds (12, 60, 8 frames, 4 s, 50-step replay window, 20 demos) or
  message text. Do not "improve" the explorer; improvements are separate directives.
- No new dependencies, no vision, no edits to `emulator.py`, `backend.py`, `decision.py` (the existing `Decision`
  is reused). No coordinates from `KNOWLEDGE.md`. No LLM call from `explorer` policy; only `hybrid` calls it.
- Never run the real ROM or PyBoy in tests. Do not delete `tools/explore_demo.py`'s HTTP `ControlServer` yet.

## 5. Verification

`uv run pytest -q` green, FakeEmulator-only. Scripted "bedroom" fake: memory with map `0x26`, `(x,y)`, party 0, bag
0, and a tile map (tiles written at `0xC3A0`, 20x18, border `0x79` + `0x7A`, cursor `0xED`, text via `CHARMAP`
inverse) containing a PC menu frame. Tests: (a) goal menu: PC menu with `WITHDRAW ITEM`, `TOSS ITEM`, `LOG OFF` ->
cursor moves DOWN to `WITHDRAW ITEM`, A; then item list with `POTION` -> chosen; `CANCEL` never; (b) YES/NO about a
nickname -> NO (DOWN then A); (c) starter offer `So! You want CHARMANDER?` with `--starter squirtle` -> NO, and
`...SQUIRTLE?` -> YES, `--starter any` -> YES, line-broken fragments across `last_dialog` still match; (d) readiness:
overworld with changing tile map -> `Decision("NONE")` up to 4 s then acts; the same unstable tile map with a menu open
-> acts immediately; (e) demonstration replay: a recorded demo at `(0x26,3,3)` with screen `[...]` is replayed once,
then not again within 50 steps; (f) best-path replay: a `best_paths.json` with `potion` start/buttons is followed
from its start tile and abandoned (returns `None`, planner takes over) after a forced drift; (g) `goals.py`: a
`goals.json` fixture evaluates `bag_has_item` (verified), `map_not_in` (verified), `party_count_gt` (verified),
returns `True/False` for them and `None` for `badge_bit`, `party_hp_full`, `party_mon1_level_gte`; the planner treats
`None` as not done and logs once; (h) `WorldGraph.path` and `plan_step` give the spike's results on a fixed `maps` dict
(copy three cases from `explore_plan.py` semantics); (i) hybrid: a menu with no rule asks a fake `LLMPolicy` exactly
once, the answer is recorded in `demos`, and the repeat is answered without a second call; (j) `Agent(emu, backend,
...)` still works (old tests unchanged); (k) the transitions/maps schema test from 3.7; (l) `pokeagent review` on a
fixture runs dir prints best/median/worst and writes both JSON files; (m) `pokeagent run --help` lists `--policy`,
`--starter`, `--goals`; `explore_demo.py` is under 80 lines (assert in a test). Existing tests stay green.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-explorer-policy-module-directive`. Never commit to `main`, never push to it, never merge.
- Create no scratch or debug files (if unavoidable, `.devin-scratch/`). Keep every module under 300 lines.

## 7. Completion criteria

- [ ] `policy.py`, `policies/explorer*.py`, `planner.py`, `goals.py`, `demos.py`, `review.py`, each under 300 lines
- [ ] `pokeagent run --policy explorer|claude|hybrid`, `--starter`, `--goals`; `pokeagent review`; `--backend claude` unchanged
- [ ] Section 5 tests pass; `uv run pytest -q` green (paste the tail)
- [ ] Demo integration: `tools/explore_demo.py` under 80 lines; same console lines and files; schema-compat test passes
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts of every new module and of `explore_demo.py`, which of `mapmem.py`/`textbox.py`/`viewer.py`/
`mcp_server.py` were present, any spike field `mapmem.py` lacked and how you added it, the unverified detectors that
returned `None`, how hybrid's `Unknown` triggers were detected, and anything in the spike you could not port exactly.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-02 · robert-claude-laptop · none → Draft — build step 11 (explorer policy module), spike approved by Robert 2026-11-02; queue after Map_Memory, Text_Box_Awareness, Viewer and Mcp_Server merge
- 2026-11-06 21:11 · robert-claude-laptop · Draft → Queued — closing as superseded
<!-- queue:end -->
