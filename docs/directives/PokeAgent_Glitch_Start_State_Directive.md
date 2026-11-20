# PokeAgent Glitch Start State: an unbeaten trainer plus an Abra whose field menu shows TELEPORT

Repo: PokeAgent (public GitHub rfd62794/Trailswarm, default branch main; queue repo name "PokeAgent"). Branch: `directive/pokeagent-glitch-start-state`.
Execute-On: local
(needs the real ROM and emulator runs: the laptop or the Home Tower only; never cloud, never the Office Tower. If `roms/` is absent in the worktree, STOP and write
"no ROM here: needs local" in the Status row. Do not search for a ROM.)
Depends on: directive 2 (PokeAgent_Teleport_Field_Menu_Research_Directive.md, doc `docs/research/teleport-field-menu.md`) for WHY a boxed L10 Abra with Teleport showed no
TELEPORT entry. Do not start until that doc is on main or copied into the worktree by the controller; if it is missing, STOP and write "directive 2 not merged" in the Status row.
Also benefits from directive 1 (PokeAgent_Glitch_Engagement_Signal_Directive.md) for the survey step but does not require it.

## 1. Why this exists

The trainer-escape probe (PR #331) cannot test its hypotheses on today's saves. Real-ROM facts from 2026-11-19 (controller-verified):
- `runs/checkpoints/nugget_bridge.state` has EVERY Route 24 (map 0x23) and Route 25 (0x24) trainer already beaten (the Route 25 Hiker at (8,4) gives post-defeat text; walking to
  Bill's house at x=44 triggers no battle). The only unbeaten trainer seen was a Cerulean Rocket NPC (about x=30, y=8). Route 6 (0x11) trainers are probably unbeaten, unchecked.
- `--build abra` from that save (seed 1, 5500 steps) did NOT catch an Abra this time: the save has 0 Poke Balls and 11575 money; the explorer wandered Route 24 at x=4-5, y=18-26
  trying to reach a Mart. Earlier 2026-11-18 runs did catch one at about step 1374, so compare what differed (balls in the bag).
- That save boxes an L10 Abra with moves `[0x64, 0, 0, 0]` (0x64 = TELEPORT). Withdrawn to party slot 6 with PC presses only, its START > POKeMON > Abra submenu shows only
  STATS / SWITCH / CANCEL: no TELEPORT, outdoors on Route 25 and in Cerulean.
The probe needs ONE start state with both: an unbeaten trainer reachable on foot, and a party Abra whose field menu lists TELEPORT. This directive produces it. The state
itself is NOT committed (gitignored); the deliverable is its path and sha256 in the Status row.

## 2. Scope (exact files, in order)

Tooling already in the repo (read these, they are tracked; paste of the relevant interfaces is below):
- `tools/explore_headless.py` (`--state`, `--rom`, `--steps`, `--seed`, `--build abra`, `--stop-at-goal`; prints a JSON summary incl. `goals`, `catch_abra_gave_up`, `work`).
  It does NOT save the final emulator state. Section 4B adds that.
- `uv run pokeagent states library list` / `states list` (save library CLI, `src/pokeagent/statescmd.py`): list checkpoints by name, map, party, money. Sub-commands of `states`:
  `list, check, promote, restamp, retire, library`; of `library`: `build, list, validate`.
- `tools/state_edit.py` (`--give ID:QTY`, `--money N`, `--heal`, writes a SYNTHETIC-stamped state) exists but is NOT allowed here: a start state for glitch probing must be organic
  (button presses only), because the probe's value is what the real game does. Do not use it, `--pos`, or any RAM write.
- `tools/glitch_probe.py` (the probe CLI; `survey --state S --map ID`) and `src/pokeagent/glitchlab/scratch.py` (`FORBIDDEN_DIRS = checkpoints, leg_states, states, baselines`;
  the probe refuses a source inside any of them, so the output MUST live outside them: `runs/scratch_in/`).
Files:
1. `src/pokeagent/glitchlab/startstate.py` (new, small): `save_final_state(emu, path) -> Path` that refuses any path under a directory named in `scratch.FORBIDDEN_DIRS`, refuses
   a path that exists (no overwrite), creates the parent directory, calls `emu.save_state(path)`, and returns the path. Pure and testable with `FakeEmulator`.
2. `tools/explore_headless.py` (edit, minimal): a `--save-final-state PATH` option that calls `save_final_state(emu, Path(PATH))` once after the run loop and adds `"final_state": str(path)`
   to the printed summary. No other behaviour change.
3. `tests/test_glitchlab_startstate.py` (new): `save_final_state` writes via a FakeEmulator, refuses `checkpoints/`, `states/`, `leg_states/`, `baselines/` parents, refuses overwrite,
   and the tool's argparse accepts `--save-final-state` (parse only; never boot an emulator in a test).
The state files and notes go under `runs/scratch_in/` (gitignored) only.

## 3. The work

Everything below runs on the laptop or Home Tower, in the worktree, with the ROM at `roms/Pokemon Red.gb` (or `POKEAGENT_ROM`). Stop at the first failed check and write why in the Status row.

### A. Pick the base checkpoint
1. `uv run pokeagent states list` (and `states library list`). Pick the EARLIEST checkpoint at or after Cerulean that still has Route 24/25 trainers unbeaten. The candidates named
   by the controller are `beat_misty` and `to_cerulean`; verify the names exist, else pick the nearest earlier one and say which. Record the chosen state's path and sha256
   (`uv run python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <path>`).
2. Confirm an unbeaten trainer exists: run the probe survey from the chosen state on map 0x24 (Route 25) and 0x23 (Route 24):
   `uv run python tools/glitch_probe.py survey --state <path> --map 0x24 --name base-r25` (if directive 1 is merged its signal is reliable; if not, the old survey's
   `engaged` column is an artifact, so instead READ the trainers: `read_trainer_sprites` from directive 1, or walk to a trainer and watch for the "!" in the tile map text).
   If no unbeaten trainer is visible on Routes 24/25 from that checkpoint, try Route 6 (map 0x11, between Vermilion and Saffron: later) and record why.

### B. Get balls, then catch the Abra (organic only)
1. Check the bag for Poke Balls: `uv run python tools/ram_query.py --help` shows the RAM reader; the bag is `read_bag` in `src/pokeagent/ramstructs.py`. The 2026-11-19 failure was
   0 balls. If the base state has none, FIRST buy balls: run `tools/explore_headless.py --build abra` from the base state and let it reach a Mart on its own, or walk by presses; it
   must end with at least 5 Poke Balls (ball item ids: the `BALLS` mapping that `src/pokeagent/abra_goal.py` uses; do not guess). Never `--give`.
2. Catch an Abra: from the state, `uv run python tools/explore_headless.py --rom "roms/Pokemon Red.gb" --state <path> --steps 5500 --seed 1 --build abra --save-final-state runs/scratch_in/abra_start_1.state`.
   Try seeds 1..3 (one run per seed, stop at the first success). Success = JSON `goals` contains `catch_abra` and `catch_abra_gave_up` is false. Abra appears on Route 24/25 grass
   (Red). If none is caught in 3 seeds, STOP and write the three summaries' `goals` and `catch_abra_gave_up` in the Status row.
3. The catch may land in the PC box when the party is full (`src/pokeagent/abra_goal.py` `box_species`). A full party boxes it. If the Abra is in the box, withdraw it with PC button presses
   only (`tools/probe_pc.py` shows the PC navigation idiom), so the Abra is in the party.
   The save must be taken with the player outdoors (not in a menu, not in a battle, no text box open).

### C. Make TELEPORT show up (use directive 2's finding)
1. Read `docs/research/teleport-field-menu.md`. Take the measurement plan in its section 4 on the saved state: open START > POKeMON > the Abra, read the RAM bytes it lists, and
   screenshot the submenu headlessly (`emu.screenshot()` from `src/pokeagent/emulator.py` saved to `runs/scratch_in/abra_menu.png`, or read the tile map at 0xC3A0 for 360 bytes
   and print `screen_lines(...)` from `src/pokeagent/explorer/party_menu.py`; the box grows UPWARD, so print ALL rows, not just the bottom).
2. If TELEPORT is listed: done. If not, the doc's top-ranked cause tells you what to change by presses only (for example the Abra is not the slot you opened; or the Abra's moves
   in the party struct are empty and need a move-relearn route that exists in-game). If the fix needs a RAM write, a synthetic edit or a tool this directive forbids, STOP and write
   the cause in the Status row: the controller decides.
3. Confirm with the engine rule, not only the screenshot: the party Abra's moves (4 bytes at the party slot's move offset per the doc) contain 0x64 and the submenu text lists TELEPORT.

### D. Record
Save the final state as `runs/scratch_in/glitch_start_<date>.state` (use today's date, no overwrite). Compute its sha256. Verify the probe accepts it:
`uv run python tools/glitch_probe.py survey --state runs/scratch_in/glitch_start_<date>.state --map <map id> --name start-check` runs and exits 0 or 1, never 2 (2 = refused source).
Verify the input is untouched by the probe: sha256 before == sha256 after. Write the state path, its sha256, the map id and player x,y, the Abra's party slot, and the trainer
(class, tile, facing if known) in the Status row. Do not paste the state's bytes anywhere.

## 4. What NOT to do

- NEVER commit, stage or publish a ROM, a save state or any ROM-derived data: `roms/`, `kb/`, `runs/` are gitignored; `git status --short` before every commit must show none of them.
  No screenshots or tile-map dumps committed (they are ROM-derived); keep them under `runs/scratch_in/`.
- No RAM writes, no `state_edit.py`, no `--give`, no `--money`, no `--pos`, no synthetic stamping: the start state must be reached by button presses (explorer runs and menus).
- Never write under `runs/checkpoints/`, `runs/legs/states`, `runs/states/`, `baselines/`, and never overwrite an existing state; output goes to `runs/scratch_in/` with a new name.
- Do not alter the checkpoint you started from. Do not retire, restamp or promote anything with the `states` CLI (read-only `list`/`library list` only).
- Do not run the full probe `repro` recipe (its cursor presses are placeholders for the controller). Do not edit the research doc or any other directive.
- Do not open a GUI window or send input to the desktop; headless only (`PyBoyEmulator(..., headless=True)`).
- No new dependencies, no network, no installs.

## 5. Verification

Code part (cloud-safe, run anywhere, serial, Python 3.12 via `uv run`). Baseline on origin/main before this change (2026-11-19):
```
uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitchlab_script.py tests/test_glitch_probe_tool.py
11 passed, 1 warning in 0.97s
```
After: the same command still passes, and `uv run pytest -q -p no:cacheprovider -rfEs tests/test_glitchlab_startstate.py` shows the new tests passing (each fails on origin/main without the
change). Then the full serial suite once (`uv run pytest -q -p no:cacheprovider -rfEs`, about 5 minutes, xdist NOT installed); paste the final summary line.
Full-suite baseline on origin/main in a fresh worktree without kb/ or roms/ (2026-11-19, `uv run pytest -q -p no:cacheprovider -rfEs`, serial, 5 minutes):
```
1 failed, 3451 passed, 73 skipped, 1 warning in 302.33s (0:05:02)
FAILED tests/test_lead_and_wild_switch.py::test_geodude_fight_pick_uses_the_real_kb_tables
  AssertionError: needs the gitignored kb/rom_tables.json (the laptop verify recipe copies it in)
```
That ONE failure is environmental (the gitignored ROM-derived kb is absent from a cloud worktree) and is the only failure allowed. Any other failure, or any new one, means stop and report it; do not mark done.
The controller's verify lane runs with the kb present and requires 0 failed there.
On the laptop with `kb/rom_tables.json` present that test should pass: there, expect 0 failed.
ROM part (local): the commands in section 3 with their real outputs pasted into the Status row tail: the `explore_headless` summary line (goals, gave_up, final_state), the sha256 of
the saved state, the tile-map or screenshot evidence that TELEPORT is listed, and the `glitch_probe survey` exit code on the saved state.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call needing confirmation is rejected and the run ends mid-task. Never require an install, download or fetch. Never read outside the working directory.
- Use `uv run` (Python 3.12), never bare `python`. Run tests serially, `-p no:cacheprovider`. Long emulator runs: one at a time (laptop is memory-limited).
- Do not search, glob or hunt for missing files (including the ROM and checkpoints): if something this directive names is missing, stop and write why in the Status row.
- Create no scratch or debug files except under `.devin-scratch/` (stays) or `runs/scratch_in/` (gitignored); deleting is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the Status row rather than trying another way around it.
- Branch `directive/pokeagent-glitch-start-state` only. Commit the code part there as you go. Never commit to main, never push, never deploy; only the controller merges.
- Every commit message ends with this trailer line (docs/STANDARDS.md requires it for unsigned commits; the PR #331 gate flagged its absence):
  `Unsigned-Reason: automation without a key; Robert approved agent commits`
- Do not add a `## Queue` block.

## 7. Completion criteria

Done means ALL of: `startstate.py`, the `--save-final-state` option and `tests/test_glitchlab_startstate.py` are committed and the focused suites show 0 failed and the full suite shows only the baseline's environmental failure (0 failed where the kb is present);
a state `runs/scratch_in/glitch_start_<date>.state` exists with its sha256 recorded; the party holds an Abra whose moves include 0x64 AND the submenu shows TELEPORT (evidence pasted);
an unbeaten Route 24/25 (or Route 6) trainer is reachable on foot from the saved position (class and tile recorded); `glitch_probe survey` accepts the state (exit 0 or 1);
the base checkpoint's sha256 is unchanged; `git status --short` shows no ROM, state or runs file staged. If any ROM-side step cannot be completed, the Status row says which step,
the exact output, and the top-ranked cause: partial progress is reported, never papered over.

## 8. Report

Findings first. Status row (one block): `state=<path> sha256=<hex> map=<id> xy=(x,y) abra_slot=<n> trainer=<class@tile> teleport_listed=<yes/no>`. Then: which base checkpoint and why,
the seeds tried and their `goals`, how balls were obtained (presses only), what directive 2's ranked cause turned out to be on the real ROM (confirmed / refuted), the test tails
(focused and full), the commit sha, and anything the controller must still decide.
