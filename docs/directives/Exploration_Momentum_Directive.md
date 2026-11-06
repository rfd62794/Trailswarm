# PokeAgent: exploration momentum - stop the every-third-step backtracking

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` section 5.
**Depends on:** `Explorer_Behaviours_Directive.md` merged (the `frontier` behaviour and `MapMemory.choose` /
`frontier_step` inside `src/pokeagent/explorer/`). If that package is missing, stop and write that in the Status
row. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "Is there a way to teach it to avoid back-tracking every 3rd step?" Measured on the live run
`runs/explore-20261105-182100-23396` (2,610 presses, 690 agent moves within one map): **22% of agent moves
immediately undo the previous move** (UP then DOWN) and **27% of moves land back on the tile it stood on two moves
earlier.** On the previous run, Route 1 alone cost 1,519 presses (steps 546-2065).

Cause, from the code being extracted (`MapMemory.choose` and `frontier_step`, demo lines 458-525):
1. `choose` is greedy per step: it steps to the neighbour with the fewest `visited` counts, ties broken by the
   fixed order `UP, DOWN, LEFT, RIGHT`. Stepping A->B raises B's count, so A and B trade places as "least
   visited" and the agent ping-pongs - the classic failure of greedy count-based exploration.
2. When every neighbour has been seen, `frontier_step` re-runs a BFS to the *nearest* frontier tile **every
   press** and takes only the first step. Two frontiers at similar distance swap as "nearest" after each step,
   so the agent turns back.

## 2. Scope (in order)

1. **Commit to a target.** The `frontier` behaviour keeps a chosen target tile and its BFS route in
   `ExplorerContext` (`frontier_target`, `frontier_route`) and follows the route press by press; it re-plans
   only when the target is reached, the next step is blocked or a map change happens, or the target stops being
   a frontier. Re-planning picks the nearest frontier but keeps the current one unless a new one is at least
   3 tiles closer (hysteresis).
2. **Reverse penalty in `choose`.** Score = visits + `REVERSE_PENALTY` (2) when the direction is the opposite of
   the last successful move; ties prefer continuing straight, then the fixed order. Learned walls, warps,
   grass rules, NPC/A-probe rules unchanged.
3. **Short tabu memory.** Tiles stood on in the last 8 moves on this map count as `+1` visit extra in `choose`
   (in-memory only, never written to `maps.json`).
4. **Metric.** `decisions.jsonl` lines gain `"reversal": bool` (this move undoes the previous one). Add
   `tools/backtrack_report.py RUN_DIR` printing immediate-reversal % and back-in-2 % for agent moves (the two
   numbers in section 1), and the same two numbers in `tools/status.py` for the newest run.

## 3. The work

Constants at the top of the frontier behaviour module: `REVERSE_PENALTY = 2`, `TABU_LEN = 8`,
`RETARGET_MARGIN = 3`. Keep them named so the RL selector and the review tool can tune them later.

## 4. What NOT to do

- Do not change walls/warps/ledge learning, the stall guards, battle, menu or dialog behaviours, or the
  `maps.json` schema.
- Do not touch `tools/rl_*.py` or the viewer.
- No new dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green (baseline = main at dispatch; paste before/after).
- Tests on synthetic memory: a corridor where the old rule ping-pongs - the new rule walks to the end
  without a reversal; two equidistant frontiers - the agent commits to one and does not alternate; retarget
  only when a frontier is >= 3 tiles closer; tabu tiles weigh +1; `backtrack_report` on a fixture
  transitions file prints the expected percentages.
- Do NOT run `uv run pokeagent ...` or the demo. Controller check on the laptop with the ROM: a 4,000-step
  Explorer run from `baselines/bedroom.state` with no human input: immediate reversals < 8% of agent moves,
  and every goal through `to_viridian` reached no later than in the parity run.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-exploration-momentum-directive`. Never commit to `main`.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] Frontier target commitment with hysteresis; reverse penalty; tabu memory
- [ ] `reversal` in decisions.jsonl; `tools/backtrack_report.py`; status.py shows both numbers
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, the corridor/two-frontier test traces, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | In progress |
| Assigned to | devin |
| Branch | directive/pokeagent-exploration-momentum-directive |
| Base branch | - |
| Base commit | d2c7f13a63dc066f438fcd1115e5e11ca9655eac |
| Model | swe-2-flash-max |

**Status log**
- 2026-11-05 18:43 · robert-claude-laptop · none → Queued — Robert approved all 2026-11-05; measured 22% immediate reversals; depends on E1 (merged PR #30)
- 2026-11-05 18:50 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: cited new paths are files it creates; dependency E1 merged
- 2026-11-05 18:50 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-exploration-momentum-directive; lane=explicit; model=swe-2-flash-max; persona=steady-builder; agent_id=01M6Q1XRRSEGBMEVFSPW4FYZ5K
- 2026-11-05 18:52 · dispatcher · launched pid=16012; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-exploration-momentum-directive; provisioned: uv sync --frozen
<!-- queue:end -->
