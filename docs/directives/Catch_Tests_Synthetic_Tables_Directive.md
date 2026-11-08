# Trailswarm: two catch-policy tests run everywhere on a small hand-written table instead of skipping without local data

**Size:** S. **Assignee:** devin.

## 1. Why this exists

Measured on 2026-11-08 from the verify log of head f59002a: 40 tests skip in the clean verify copy, 6 of them only because `kb/rom_tables.json` is missing (gitignored, so missing in a fresh worktree). That file is generated from a local ROM and gitignored, and it must never be committed.

Of those 6, only 2 test our own behaviour. The other 4 assert facts about the real generated table, so a made-up table would make them pass without proving anything. They stay as they are:

- `tests/test_campaign.py::test_item_ids_exist_in_rom_item_table`
- `tests/test_grind_atlas.py::test_rom_tables_have_base_exp_and_growth`
- `tests/test_knowledge.py::test_every_rom_effect_id_has_a_table_entry`
- `tests/test_knowledge.py::test_rom_facts_drained_from_the_cartridge`

The 2 in scope are in `tests/test_team_inventory.py`, both marked `@needs_rom`:

```python
needs_rom = pytest.mark.skipif(ROM_KB is None, reason="kb/rom_tables.json not present")   # line 22

@needs_rom
def test_catch_skips_an_unwanted_species(tmp_path):
    ctx = battle_ctx(tmp_path, 36, owned_count=10)  # PIDGEY, 10 already owned, nobody needs it
    Catch().step(ctx)
    assert ctx.catch_attempt is None and ctx.catch_mode is False

@needs_rom
def test_catch_still_catches_a_wanted_species(tmp_path, synthetic_hm):
    ctx = battle_ctx(tmp_path, 188, owned_count=10)  # BELLSPROUT: a Cut learner and the party has none
    Catch().step(ctx)
    assert ctx.catch_attempt is not None and ctx.catch_attempt["species"] == 188
```

The code under test reads the table through a name bound in its own module, `src/pokeagent/explorer/behaviours/catch.py`:

```python
from pokeagent.explorer.kb import ROM_KB                                                        # line 14
items = (ROM_KB or {}).get("items", {})                                                         # line 65
dex_no = int((ROM_KB or {}).get("dex_of_internal", {}).get(str(species), 0) or 0)               # line 116
if kind == 1 and balls and dex_no and e_max and cave_catch_allowed(ctx, species):               # line 120
    sp_name = (ROM_KB or {}).get("name_of_internal", {}).get(str(species), str(species))        # line 121
```

Without a table `dex_no` is 0, the policy branch at line 120 never runs, and `test_catch_skips_an_unwanted_species` would pass without exercising anything. So simply deleting the marker is wrong: the test needs a table that makes `dex_no` non-zero.

## 2. Scope

Only `tests/test_team_inventory.py`.

## 3. The work

1. Add a pytest fixture next to `synthetic_hm` (line 135), named `synthetic_catch_kb`, using `monkeypatch.setattr("pokeagent.explorer.behaviours.catch.ROM_KB", TABLE)`. Patch that module's name, because `from ... import ROM_KB` binds it per module. `TABLE` is a hand-written dict in the test file containing only what the two tests need:

   ```python
   SYNTHETIC_CATCH_KB = {
       "dex_of_internal": {"36": 16, "188": 69},
       "name_of_internal": {"36": "PIDGEY", "188": "BELLSPROUT"},
       "items": {},
   }
   ```

   The dex numbers must be above 10 so `owned_count=10` does not mark them owned. If `Catch.step` needs another key for these two tests, add the smallest hand-written value that works and say so in the report.
2. Remove `@needs_rom` from the two tests and use the fixture in both. `test_catch_skips_an_unwanted_species` also needs `synthetic_hm`, so the result does not depend on a local HM table.
3. Make `test_catch_skips_an_unwanted_species` prove the policy ran: use `caplog` or the context's log to assert the `[catch: skipping PIDGEY` line was written, or assert `ctx.catch_want` was set to a falsy decision for that species. Pick whichever works without changing production code.
4. Keep `needs_rom` defined if another test still uses it; remove it only if nothing does.

## 4. What NOT to do

- Do not change anything under `src/`, or any test other than these two and the new fixture.
- Do not touch the 4 real-table tests listed in section 1, or any test that skips for a missing ROM, checkpoint or baseline.
- Do not read, copy, print or commit `kb/rom_tables.json`, `kb/items.json`, `kb/hm_compat.json`, `roms/` or `baselines/`. They are not in your worktree, and that is correct. Write the table by hand from this directive.
- Do not add a new skip, `xfail`, or broad fixture such as an autouse patch of `ROM_KB`.
- Do not say where any game copy came from, in code, comments, docs or the report.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

```
uv run pytest -q -p no:cacheprovider tests/test_team_inventory.py -rs
```
Expected: all pass, and neither `test_catch_skips_an_unwanted_species` nor `test_catch_still_catches_a_wanted_species` appears in the skip report. Before this change the file printed `18 passed` in a checkout that has the local table.

```
uv run pytest -q -p no:cacheprovider tests/test_magikarp.py tests/test_surgery.py tests/test_knowledge.py
```
Expected: same result as on your base commit, with no new failures. Report any pre-existing failure separately.

```
git diff --stat main -- src
```
Expected: no output.

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] Both tests run and pass with no `kb/rom_tables.json` present, and neither is skipped. <!-- test: tests/test_team_inventory.py -->
- [ ] `test_catch_skips_an_unwanted_species` fails if the policy branch does not run (it asserts the decision, not only the absence of a catch). <!-- test: tests/test_team_inventory.py -->
- [ ] Nothing under `src/` changed, and the only edited file is `tests/test_team_inventory.py`.
- [ ] No ROM-derived file was added to the repo.

## 8. Report

Findings first: which assertion proves the policy ran, any table key added beyond section 3, and the skip count of `tests/test_team_inventory.py` before and after. Then the command tails from section 5.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(tests/test_team_inventory.py)
- Read(src/pokeagent/explorer/behaviours/catch.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git diff)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 16:30 · robert-claude-laptop · none → Queued — Drafted by Claude at Robert's request 2026-11-08: two catch-policy tests run on a hand-written table instead of skipping
<!-- queue:end -->
