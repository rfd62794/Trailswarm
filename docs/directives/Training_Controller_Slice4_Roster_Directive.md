# PokeAgent: Training Controller slice 4 (Roster) - one trainee-selection owner; faint counter in team_sig; Weedle preference over a wild Kakuna

**Size:** M. **Model:** swe-2-high. **Assignee:** devin.

**Read first:** `docs/plans/training-controller-2026-11-13.md` (sections 2, 4 item 4, 5, 6 and "Slice 3 result"). Slices 1 (shadow), 2 (Target, #250) and 3 (Sustain, #259) are merged: `src/pokeagent/explorer/training_ctl/{state,controller,adapters,target,sustain}.py`. Base: current main. All paths below are under `src/pokeagent/` unless they start with `tests/`, `tools/` or `docs/`.

## 1. Why this exists

Seed 12 baseline (heal_cerulean -> beat_misty, 12000 steps): 42 reorder sessions (503 decision lines, 4.2% of steps): 25 on Route 24, 14 inside the Cerulean Pokecenter right after heals, 3 in Cerulean; 167 of 862 SHAKEs fall within 40 steps of a reorder press; switch_train 163 lines. Trainee selection has no single owner: six call sites of `magikarp.trainee_slot_for` (verified below) pass different arguments, and `party_order.team_sig` includes a per-member `fainted` bit, so every heal (fainted -> alive) changes the signature and re-triggers a reorder (the 2026-11-13 incident: 31 reorders on one grass edge; the 300-step expiry was removed, the heal trigger remains).

Slice 3 ended differently from the plan: NO per-step tick writer; `sustain.publish` is the single writer at main's old points, and a real-ROM seed 12/13 run was byte-identical to main (`decisions.jsonl`). LESSON, binding for this slice: a "move" slice must keep `decisions.jsonl` byte-identical on the real ROM, and any timing/ordering change of a flag read by guards or behaviours is forbidden; behaviour CHANGES live in their own clearly flagged step with an A/B.

Robert's rule (2026-11-14; catch side merged in #253 as `catch_list.NEVER_CATCH = frozenset({"KAKUNA"})`): prefer evolving a WEEDLE over keeping a wild KAKUNA. A wild Kakuna knows only Harden; Weedle -> Kakuna (L7) -> Beedrill (L10) keeps Poison Sting. `knowledge/team_value.py` `EVOLUTIONS` already has `"WEEDLE": ("KAKUNA", 7)` and `"KAKUNA": ("BEEDRILL", 10)`. Seed 12-14 parties held two Kakuna; match by `Combatant.name`, never by hard-coded internal id.

## 2. Scope: two parts, strictly separated

**Part (a): pure ownership moves. Decisions MUST stay identical.** Claude will byte-compare seed 12 `decisions.jsonl` on the real ROM against main for part (a), so part (a) is its own commit. Anything that changes a decision in part (a) is a bug.
**Part (b): behaviour changes, each its own commit and its own tests, subject line starting `BEHAVIOUR CHANGE`**: (b1) faint counter, (b2) Weedle preference, (b3) Kakuna deposit. Claude A/Bs (b) on seeds 12/13/14 against the merged baseline using `bench_xp_per_1k_run_steps` and `second_member_l9_step` (`tools/step_budget.py`), plus reorder sessions.

Files:
1. NEW `explorer/training_ctl/roster.py` (< 120 lines) + NEW `tests/test_training_ctl_roster.py`.
2. Part (a): `explorer/behaviours/catch.py`, `explorer/behaviours/switch_out.py`, `explorer/grind_episode.py`, `explorer/trainee_gate.py`; test adaptations `tests/test_party_full_policy.py`, `tests/test_switch_matchup.py`.
3. Part (b): `explorer/behaviours/party_order.py` (`team_sig`), `knowledge/team_plan.py` (`trainee_slot`), `explorer/behaviours/catch.py` (`full_party_slot`).

## 3. The work

### Current code (verified on main f17c793)

All six call sites of `trainee_slot_for` (re-check with `git grep -n "trainee_slot_for" -- src`; `docs/` hits are prose):
```python
magikarp.py:37          def trainee_slot_for(emu, named: int | None, breakers=(), wild=None) -> int | None:
                            t = trainee_slot(emu)                     # the Magikarp's slot wins
                            if t is not None: return t
                            from pokeagent.knowledge import team_plan  # deferred import
                            return team_plan.trainee_slot(read_party(emu), named, breakers, wild)
behaviours/catch.py:28  from pokeagent.magikarp import trainee_slot_for
behaviours/catch.py:47  t = trainee_slot_for(ctx.emu, ctx.train_member)   # inside full_party_slot (:36): protects the trainee from deposit
behaviours/switch_out.py:25  from pokeagent.magikarp import MAGIKARP, MAX_RUNS, party_species, switch_candidate, trainee_slot_for
behaviours/switch_out.py:37  t = trainee_slot_for(ctx.emu, ctx.train_member, team_plan.of(ctx).get("breakers") or ())   # trainee_out: the ONLY site passing breakers
behaviours/switch_out.py:88  trainee=trainee_slot_for(ctx.emu, ctx.train_member))   # _matchup_pick -> team_plan.switch_choice(...); NO breakers
grind_episode.py:33     from pokeagent.magikarp import trainee_slot_for
grind_episode.py:89     return trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None))   # _slot(ctx), wrapped in try/except -> None (the plan said :92; it is :89)
trainee_gate.py:31      from pokeagent.magikarp import trainee_slot_for
trainee_gate.py:41      slot = trainee_slot_for(ctx.emu, ctx.train_member)   # trainee_check (pure read)
trainee_gate.py:66      slot = trainee_slot_for(ctx.emu, ctx.train_member)   # trainee_ok (after trainee_check said not ok)
```
IMPORTANT finding: the owners DISAGREE today. Only `switch_out.py:37` passes `breakers`, so `trainee_check`, `full_party_slot`, `_matchup_pick` and `grind_episode._slot` can return None (or the Magikarp) while `trainee_out` returns a band breaker. Unifying that is a behaviour change, so it is NOT part (a): `roster.trainee_slot` takes `breakers: bool = False` and each site keeps passing exactly what it passes now (only `switch_out.py:37` passes True). Do not "fix" the disagreement; list it in the Report.

`knowledge/team_plan.py:167`, the pure selection (stays; `magikarp.trainee_slot_for` stays too as the pure primitive, and `tests/test_team_readiness.py:131-140` tests it unchanged):
```python
def trainee_slot(party, named: int | None = None, breakers=(), wild=None, kb=None) -> int | None:
    if not party: return None
    if named is not None and 0 <= named < len(party) and party[named].level <= max(c.level for c in party) - TEAM_GAP:
        return named
    foes = [...]                      # wild Combatants
    chart, moves = _chart(kb), table(kb, "moves")
    for s in sorted((s for s in breakers if 0 <= s < len(party)), key=lambda s: (party[s].level, s)):
        if not foes or all(survives_hit(party[s], f, chart, moves) for f in foes):
            return s
    return None
```
`knowledge/team_plan.py:253` `release_candidate(party, *, protected=frozenset(), values=None)`: lowest `values` score not in `protected` (values default to levels). `team_plan.of(ctx)` (:262) is the per-run state dict on `ctx.__dict__["team_plan_state"]`.

`explorer/behaviours/party_order.py` (the plan's `explorer/party_order.py` is wrong: the file is under `behaviours/`):
```python
:31  def team_sig(ctx: ExplorerContext) -> tuple:
:32      """The order-independent team state a reorder may react to: (species, level, fainted) per member, sorted."""
:33      return tuple(sorted((getattr(m, "species", 0), getattr(m, "level", 0), getattr(m, "hp", 1) == 0)
:34                          for m in read_party(ctx.emu)))
:37  def _held(ctx) -> bool:   # docstring :38-41 (the incident: 31 reorders, no-expiry rule)
:42      last = team_plan.of(ctx).get("order_hold")
:43      return bool(last) and last[1] == team_sig(ctx)
:55      if swap is None or _held(ctx): return None     # inside want_home (:46)
:95      team_plan.of(ctx)["order_hold"] = (ctx.step, team_sig(ctx))     # set when a reorder completes
```
Pinned by `tests/test_party_order_ascending.py:72` (`order_hold = (ctx.step - 12, po.team_sig(ctx))`) and `tests/test_party_log_reorder.py`.

`explorer/status_care.py::trainee_eligible` is the pure eligibility check; `trainee_gate.trainee_check` composes it. Reuse, do not duplicate.

### Part (a) steps: ownership move (decisions identical)

**Step 1: `training_ctl/roster.py`.**
```python
def trainee_slot(ctx, *, breakers: bool = False) -> int | None:
    """THE one entry for 'which party slot is the switch-trainee'."""
    # = magikarp.trainee_slot_for(ctx.emu, getattr(ctx, "train_member", None),
    #                             (team_plan.of(ctx).get("breakers") or ()) if breakers else ())
```
No memo, no ctx write (a QUERY, like `sustain.heal_now`): the sites run at different points of a step and caching would change decisions. `grind_episode._slot` keeps its own try/except around the roster call. `roster.py` imports only `pokeagent.magikarp` and `pokeagent.knowledge.team_plan` (never `grind_episode`, `trainee_gate`, `switch_out`, `catch`, `plan_goal`).

**Step 2: migrate the six call sites** (import `from pokeagent.explorer.training_ctl import roster`; call `roster.trainee_slot(ctx)`; `switch_out.py:37` passes `breakers=True`). After this, `git grep -n "trainee_slot_for" -- src` shows only the definition `magikarp.py:37` and the single call in `roster.py`. `trainee_gate` keeps only the pure eligibility check in spirit, but do NOT move `trainee_ok`'s actions (counters, log row, heal_walk request) in this slice: just read the slot from `roster`. Splitting the actions off is a later slice; say so in the Report.

**Step 3: adapt tests (only what the move forces; name each in the Report).** `tests/test_party_full_policy.py:29,40,47` monkeypatch `catch_behav.trainee_slot_for`; they become `monkeypatch.setattr(roster, "trainee_slot", lambda ctx, **kw: <same value>)` (patch the `roster` module attribute; the sites call `roster.trainee_slot(...)`, so one patch point works). `tests/test_switch_matchup.py:58,115` patch `so_mod.trainee_slot_for` the same way. No assertion changes. `tests/test_trainee_gate.py`, `tests/test_trainer_grind.py`, `tests/test_team_readiness.py` should pass untouched; if not, make the smallest change and say why.

**Step 4: part (a) tests** in `tests/test_training_ctl_roster.py`: (i) `roster.trainee_slot` equals `magikarp.trainee_slot_for` for a Magikarp party, a named weak member, and a band-breakers party with `breakers=True` (and None with `breakers=False`): build parties with the helpers `tests/test_team_readiness.py` and `tests/test_trainer_grind.py` already use; (ii) a source test with `inspect.getsource`: none of the five migrated modules mentions `trainee_slot_for`; (iii) fresh-process import test via `subprocess.run([sys.executable, "-c", "import pokeagent.explorer.training_ctl.roster, pokeagent.explorer.grind_episode, pokeagent.explorer.trainee_gate, pokeagent.explorer.behaviours.catch, pokeagent.explorer.behaviours.switch_out"], capture_output=True, text=True)` with returncode 0 (inside a test; `python -c` is forbidden in YOUR shell only). COMMIT part (a) alone, subject `Roster slice 4a: one trainee_slot owner (decisions identical)`.

### Part (b) steps: behaviour changes (separate commits)

**Step 5 (b1): faint counter in `team_sig`.** Replace the fainted bit with a monotonic counter.
- State: `team_plan.of(ctx)["faints"]` (int, starts 0) and `["faints_prev"]` (last step's count of fainted members), beside `order_hold`.
- `roster.note_faints(ctx) -> int`: idempotent per `ctx.step` (stamp `["faints_step"]`; a second call in the same step returns the stored counter). Count `n = sum(1 for m in read_party(ctx.emu) if m.hp == 0)`; `faints += max(0, n - faints_prev)`; `faints_prev = n`. ORDER-INDEPENDENT on purpose (a reorder permutes slots; a per-slot comparison would miscount). A heal (n drops) never decrements. Known blind spot, accept and say so in the docstring: a revive and a new faint within one single step cancel out.
- `party_order.team_sig` becomes `(tuple(sorted((species, level) per member)), roster.note_faints(ctx))`. Nothing else in `party_order.py` changes (`_held`, `want_home`, :95 keep working: they only compare equality).
- Reset: never within a run (blackouts and Pokecenter heals do not reset it; a new context starts at 0).
- Regression tests (`tests/test_training_ctl_roster.py`, fake-party style of `tests/test_party_order_ascending.py`): (1) a level-up changes `team_sig` and `want_home` reorders again; (2) a real faint (alive -> hp 0) bumps the counter by 1, `_held` is False, a reorder fires; (3) a heal-revive (hp 0 -> alive) does NOT change `team_sig` relative to the post-faint value and `_held` stays True; (4) a pure slot permutation (same members, other order) changes nothing and does not bump the counter; (5) no expiry: `order_hold` set at `ctx.step - 5000` is still held for an unchanged team; (6) `note_faints` twice in one step counts once; (7) a member that faints twice over a run counts twice. Adapt `tests/test_party_order_ascending.py:72` only if the new `team_sig` shape forces it.

**Step 6 (b2): prefer evolving a WEEDLE.** In `knowledge/team_plan.py::trainee_slot` add, BEFORE the existing `named`/breakers logic, one clearly commented rule: a party member whose `.name == "WEEDLE"` that is not the strongest member (`level <= max level - 1`) and is below its second evolution level (`level < EVOLUTIONS["KAKUNA"][1]`, read from `knowledge.team_value.EVOLUTIONS`, not hard-coded; `team_value` does not import `team_plan`, so a plain import is fine, otherwise import lazily) is the trainee: it keeps Poison Sting through Beedrill. Pick the lowest-level such Weedle. A Magikarp in the party still wins upstream (`magikarp.trainee_slot_for`, unchanged). Do NOT add METAPOD or CATERPIE (undecided). Tests: a Weedle L5 under a stronger lead is chosen over a named weak member and over a breaker; a Weedle L10 is not; a Kakuna is never chosen by this rule; with no Weedle the result equals the old function (run `tests/test_team_readiness.py:131-140` unchanged).

**Step 7 (b3): a wild Kakuna in the party is a deposit candidate.** In `behaviours/catch.py::full_party_slot` (:36) pass `values=` so any member whose `name in catch_list.NEVER_CATCH` scores below every other member (e.g. `-1`), still never overriding `protected` (the trainee slot and HM learners stay protected, so a Kakuna that is the current trainee is kept). Import `NEVER_CATCH` from `explorer/catch_list.py:22`; do not copy the set. This only changes WHICH member is marked when the party is already full and a wanted catch lands; it adds no new deposit trigger. Tests: six-member party with one KAKUNA and a lower-level non-Kakuna: the Kakuna slot is returned; the same Kakuna as the trainee slot (monkeypatch `roster.trainee_slot`) is NOT; no Kakuna -> the old lowest-level choice; HM protection still wins (reuse the helpers of `tests/test_party_full_policy.py`).

## 4. What NOT to do

- Do not change any decision in part (a). Do not memoize `roster.trainee_slot`. Do not unify the `breakers` disagreement. Do not move `trainee_ok`'s actions.
- Do not touch Sustain/heal (`planner.py`, `planner_east.py`, `sustain.py`), Exit (`grind.py`, `GrindBudget`, `ctx.grind`, `gym_hold_seen`, `floor_unmet`, `gate_lifted`/`lifted_need`), the loop guard (`center_visit`, `LoopGuard`), Mart/restock, `grind/points.py`, ledger files, `bandit/hook.py`, the contents of `catch_list.NEVER_CATCH`, `explorer/context.py`, `explorer/memory.py`.
- `explorer/behaviours/plan_goal.py` is not expected in the diff (net lines <= 0 if it is). No new `ExplorerContext` field: the counter lives in `team_plan.of(ctx)`.
- Do not add METAPOD, CATERPIE or any other species rule. Do not delete files.
- No ROM runs, no `tools/explore_demo.py`, no `runs/` access. The A/B is Claude's after merge.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

Baseline first (unmodified base; Claude ran these four gate files on f17c793: `30 passed`):
```
uv run pytest -q -p no:cacheprovider tests/test_party_order_ascending.py tests/test_party_log_reorder.py tests/test_trainee_gate.py tests/test_trainer_grind.py
```
After part (a), and again after each part (b) step:
```
uv run pytest -q -p no:cacheprovider tests/test_party_order_ascending.py tests/test_party_log_reorder.py tests/test_trainee_gate.py tests/test_trainer_grind.py tests/test_team_readiness.py tests/test_party_full_policy.py tests/test_switch_matchup.py tests/test_training_ctl_roster.py tests/test_training_ctl_shadow.py tests/test_grind_episode.py
```
Expected: 0 failed each time. Then the full suite once at the end (never `-n`):
```
uv run pytest -q -p no:cacheprovider
```
Expected: 0 failed. Structure checks:
```
wc -l src/pokeagent/explorer/training_ctl/roster.py src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py
git diff --stat origin/main -- src/pokeagent/explorer/behaviours/plan_goal.py src/pokeagent/explorer/context.py src/pokeagent/explorer/memory.py
git grep -n "trainee_slot_for" -- src
```
Expected: roster.py < 120; plan_goal, context, memory not in the diff; `trainee_slot_for` only at `magikarp.py` (definition) and one call in `roster.py`.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt for missing things: if something named here is missing or a cited shape differs, stop and write why in the Status row.
- Use `uv run` and Python 3.12 only; never bare `python`, and never `python -c` (put every check in a test).
- Never delete files (the sandbox refuses and stops the run). Leave any dead file in place, unchanged, and name it in the Report; Claude deletes it in review.
- Create no scratch or debug files; if you need one, put it under `.devin-scratch/` and leave it there.
- Never commit to main/master, never push to main, never deploy, never merge. Commit as you go on your branch (part (a) first, then b1, b2, b3 as separate commits) and push it.
- No ROM runs, no `runs/` access; never touch ROM files.
- 0 failed tests is a hard rule: no "known failures", no skips added to make it pass.
- Do NOT hand-write a `## Queue` block or edit anything between the queue markers.
- Set the Status to `Review` only when the branch is pushed with the work and every check in section 5 passes. If a tool call is genuinely blocked, stop and write why in the Status row.

## 7. Completion criteria

- [ ] `roster.trainee_slot` is the only caller of `magikarp.trainee_slot_for`; the six sites migrated with identical arguments (only `switch_out.py:37` uses `breakers=True`). <!-- test: tests/test_training_ctl_roster.py -->
- [ ] Part (a) is its own commit and changes no decision (Claude byte-compares seed 12 on the real ROM).
- [ ] `team_sig` uses the monotonic faint counter; the seven regression tests of step 5 pass; no expiry. <!-- test: tests/test_training_ctl_roster.py -->
- [ ] Weedle preference and Kakuna deposit implemented with their tests; no Metapod/Caterpie rule. <!-- test: tests/test_training_ctl_roster.py -->
- [ ] plan_goal, context, memory not in the diff. Gate tests and the full suite: 0 failed.

## 8. Report

Findings first: what changed per file and per commit (4a, b1, b2, b3); exact `wc -l` numbers; each test adapted in step 3 and why; every place a cited shape differed; the `breakers` disagreement between the call sites (left as is); any import cycle and its resolution; any dead file left for deletion. Then real output tails: baseline gate run, each post-step gate run, structure checks, the full-suite line. State plainly that no ROM was used. The real-ROM checks are Claude's after merge: (a) seed 12 `decisions.jsonl` byte-identical to main; (b) seeds 12/13/14 vs the merged baseline: `bench_xp_per_1k_run_steps` not worse, `second_member_l9_step` not later, reorder sessions (baseline 42 on seed 12; target 0 inside a Pokecenter, <= 5 total), and whether a Weedle is trained/evolved and a Kakuna deposited.

## Required from User

Nothing for the build. After merge, Claude runs the seed A/Bs on the laptop.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/plans/training-controller-2026-11-13.md)
- Exec(uv run pytest)
- Exec(git diff)
- Exec(git grep)
- Exec(wc)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-14 03:38 · robert-claude-laptop · none → Queued — Training Controller plan approved; slices 1-3 merged; includes Robert's Weedle-over-Kakuna rule (2026-11-14).
- 2026-11-14 03:39 · robert-claude-laptop · Queued → Approved — lint override: Any cited training_ctl/roster.py and new test files are created by this directive; behaviours/*.py shorthand refers to existing files under src/pokeagent/explorer/.
<!-- queue:end -->
