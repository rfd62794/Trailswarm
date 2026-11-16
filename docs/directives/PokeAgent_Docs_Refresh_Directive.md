# PokeAgent: Docs refresh - bring README and docs/ in line with the code, then document the recent features

## 1. Why this exists

An audit on 2026-11-15 (main at a870e08) compared README.md, AGENTS.md, DIRECTION.md, EXPLORATION.md and docs/*.md
against the code and the CLIs. The docs stop around 2026-11-08; the last week of merged work is undocumented, and several
claims are now wrong. Measured gaps (file: claim -> what the code says):

STALE
1. README.md "Highlights": "It is currently stuck before Bill's house." -> docs/RESULTS.md says `to_bill` was solved
   (map 0x58 in 2,177 steps, 2026-11-07) and PR #299 added the `ss_ticket` goal (`src/pokeagent/explorer/behaviours/goal_talk_bill.py`,
   `goal_talk.py:26`).
2. README.md "How it works": "a chain of 128 goals" -> `src/pokeagent/data/campaign.json` holds 131 goals.
3. docs/campaign_goals.md line 3: "129 goals" and the table has 129 rows; `team_ready` and `cut_learner` are in
   campaign.json (131) but missing from the table.
4. docs/SEGMENTS.md S6: "not yet reached by any agent" and the table stops at S20 (`ss_ticket`); the ladder continues to
   `beat_champion`. The Curriculum section does not mention build selection (PR #292, `src/pokeagent/statelib/start_pick.py:1-21`:
   exploit 0.60 / alternative 0.25 / promising 0.15, shares file `runs/curriculum_builds.json`).
5. docs/plans/training-controller-2026-11-13.md line 3: "Status: design draft, no code" -> built: `src/pokeagent/explorer/training_ctl/`
   (controller, target, sustain, roster, exit_rule, state, adapters); the slice 2-5 directives are Done.
6. docs/plans/go-explore-2026-11-14.md line 3: "design draft, no code" -> built: `src/pokeagent/goexplore/` (archive, cell, cell_dump,
   census, runner, select, store); the slice 1-4 directives are Done.
7. docs/ROADMAP.md layer table (lines 40-44): "MCP server (dir 5, building)", "battle state (dir 12, new)", "checkpoints/branching
   (dir 10, new)" -> all merged (`pokeagent mcp`, `states`, `rewind` exist). The "Rewinder slice 1" row points at the directive but
   does not say it merged (PR #301, `src/pokeagent/rewind/`, `pokeagent rewind`). Slice 2 is not started.
8. docs/RESULTS.md: nothing after 2026-11-08 (no training controller, banded grind, Bill/ss_ticket, save library results).
9. README.md "Project layout" lists 8 directories; `src/pokeagent/` now also has bandit/, brain/, bytecheck/, compat/, family/,
   game/, goexplore/, grind/, legs/, mapview/, novelty/, procedures/, review/, rewind/, statelib/, vision*/ and more.
10. README.md "Docs" list omits docs/BYTECHECK.md, docs/LEGAL.md (linked elsewhere), docs/plans/, docs/research/.

MISSING (feature exists, no doc outside directives)
11. `pokeagent rewind RUN [--at STEP] [--segments] [--moments] [--json]` (PR #301). Mentioned only in DIRECTION.md/ROADMAP.md.
12. Level-banded grinding and solo viability (PR #300): `src/pokeagent/grind/xp_buckets.py`, `grind/solo_viable.py`,
    `explorer/xp_spots.py` (ledger `runs/xp_spots.json`, 5-level bands), `grind/points.py`.
13. Training controller (no user-level doc at all; only the stale design plan).
14. Curriculum build selection (see 4) and the save-state library: `pokeagent states {list,check,promote,restamp,retire,library}`
    and `states library {build,list,validate}` -> `runs/states/library.json` (`statelib/library.py`). Only a KNOWLEDGE.md section.
15. Behaviour bandit (`--bandit`, `src/pokeagent/bandit/`) and novelty (`--novelty`, `src/pokeagent/novelty/`): flags are in
    no README/docs page outside KNOWLEDGE.md fragments.
16. Headless harness `tools/explore_headless.py` (leg drills, grind drills, `--stop-at-goal`): not in README or any doc.
17. Marathon runs: `tools/explore_demo.py --headless ... --tag marathon-<name>` (`--tag` = opaque label in meta.json): no doc.
18. CLI subcommands absent from README: `review`, `brain`, `hex`, `bytecheck` (only BYTECHECK.md covers one), `states`, `rewind`.
19. Window model: which things open a PyBoy/SDL2 window and which never do. No doc states it (see section 4).
20. Go-Explore cell flags `--cell-dump/--cell-from/--cell-steps` on explore_demo.py: no user doc.

CURRENT (no change needed unless a section below says so): docs/BYTECHECK.md, docs/LEGAL.md, EXPLORATION.md, AGENTS.md
(pytest-xdist is NOT installed in this env, so `-p xdist -n 4` fails; AGENTS.md's serial command is right),
docs/KNOWLEDGE.md (append-only fact log; its Bill section is current), docs/superpowers/specs/*, docs/research/*.
Not audited in depth: docs/plans/{Training_V2,Yellow_Prep,Yellow_Translation_Layer,Multi_Game_Framework_Plan,Demo_Video_Pipeline_Plan}.md.

## 2. Read first (all inside the worktree)

README.md, docs/SEGMENTS.md, docs/campaign_goals.md, docs/ROADMAP.md, docs/RESULTS.md, docs/BYTECHECK.md, DIRECTION.md,
docs/plans/training-controller-2026-11-13.md, docs/plans/go-explore-2026-11-14.md, and the module docstrings of
`src/pokeagent/rewind/cli.py`, `statelib/start_pick.py`, `statelib/library.py`, `grind/xp_buckets.py`, `grind/solo_viable.py`,
`explorer/xp_spots.py`, `explorer/training_ctl/controller.py`, `explorer/behaviours/goal_talk_bill.py`.
Every claim you write must come from code you read or a command output you ran. If a claim cannot be checked, leave it out.

## 3. Scope (edit/create in this order; nothing else)

1. README.md - fix items 1, 2, 9, 10; add Quickstart lines for rewind, states, review; link the new docs.
2. docs/campaign_goals.md - fix the count (131), add the two missing rows by reading campaign.json.
3. docs/SEGMENTS.md - fix S6; for later segments add a pointer to `pokeagent review segments` / `tools/segments.py` instead of
   inventing records; add a "Build selection" subsection.
4. docs/plans/training-controller-2026-11-13.md and docs/plans/go-explore-2026-11-14.md - change only the Status line to say
   built, with the module path and a pointer to docs/TRAINING.md (design text below stays as history).
5. docs/ROADMAP.md - fix the layer table status words; update the Rewinder slice table (slice 1 merged, PR #301).
6. docs/RESULTS.md - add only results you can read from the repo (directive Report rows list measured numbers); cite the
   directive file. If none is measurable from the repo, add nothing and say so in the Report.
7. NEW docs/CLI.md - every `pokeagent` subcommand and the three tools, from the help text in section 5.
8. NEW docs/TRAINING.md - training controller, level-banded grinding, solo viability, bandit, novelty, build selection, save library.
9. NEW docs/OPERATING.md - how a run is launched and watched: headless harness, marathon tag convention, swarm, viewer, rewind,
   and the window model.

## 4. The work

- Window model (verify in code, then write): `pokeagent view` and `pokeagent world` are Dear PyGui windows.
  `tools/explore_demo.py` without `--headless` opens a PyBoy window; with `--headless` none. `tools/swarm.py` agents,
  `tools/explore_headless.py`, `pokeagent state`, `rewind`, `states`, `review` open no window. `pokeagent mcp` and `pokeagent run`
  open a PyBoy window unless `--headless` is passed (`src/pokeagent/cli.py:236-259`). The project's viewer is Dear PyGui only.
  `tools/agent_window.py` is a legacy tk runner; mention it only if you verify it still runs from its docstring and imports.
- Rewind: it plays back `transitions.jsonl`, `decisions.jsonl`, `levels.jsonl`; needs no ROM and no window; text or `--json`;
  exit 2 on unknown run. Slice 2 (viewer scrubber) is NOT built; say so. Make no stall-cause claims (DIRECTION.md rule: it shows
  what happened, not why).
- Marathon: describe only the convention (a long headless run tagged `marathon-*`); state no results.
- README intro: describe the project as an exploration/experiment, not a product; no benchmark claims.
- Keep each new doc under 150 lines and the README under 140.

## 5. Facts to use (pasted so you need not look elsewhere)

`uv run pokeagent --help` subcommands: run, check-rom, state, mcp, view, world, states, rewind, hex, brain, review, bytecheck.
- `rewind RUN [--runs DIR] [--at STEP] [--segments] [--moments] [--json]`: "play a finished run back: frames, activity segments, moments".
- `states {list,check,promote,restamp,retire,library}`; `list [--map M] [--bad] [--dir D]`; `library {build,list,validate}`
  ("build: scan the state dirs and write runs/states/library.json"; "validate: re-run the party rules; print RETIRABLE lines").
- `world [--root DIR] [--fake N] [--png OUT] [--rom ROM] [--base PNG] [--layers LAYERS] [--model JSON] [--no-tint] [--scale S]
  [--interiors {inset,inplace,inplace-full,auto,stretch}] [--mode {tiles,world}]`.
- `view [--root DIR] [--fake N] [--fps N] [--mode {tiles,world}] [--source DIR] [--game NAME] [--preset NAME] [--genre NAME]`
  (it also has a `--web` flag; do NOT document it, see section 6).
- `review {run,swarm,diff,replay,segments}`; `brain {maps,map,tile,find,diff,lessons,edit,edits,undo,apply,q}`;
  `hex {dump,diff,find,screen}`; `bytecheck {build,scan,staged}`; `run [--backend {stub,claude}] [--steps N] [--headless]`.
- tools/explore_headless.py: `--state --steps --seed --stop-at-goal GOAL --starter --bandit --bandit-path --par-follow --role --novelty
  --save-leg-states --drill-leg MAP:X,Y->X,Y --drill-grind MAP --drill-steps --drill-min-hp --drill-goto`.
- tools/explore_demo.py adds `--headless --tag TAG --stop-at-goal GOAL --stop-at-map MAP --maps --runs-dir --control-port
  --starter {any,random,bulbasaur,charmander,squirtle} --train-level --explore-rate --cell-dump --cell-from --cell-steps`.
- tools/swarm.py: `--agents --steps --continuous --plan curriculum --suite --segment --drills F --save-leg-states --roles --bandit
  --bandit-share --par-follow --par-share --novelty --upgrade --duration --stop-now --port-base --no-share-frames`.
- Build selection: modes exploit 0.60 / alternative 0.25 / promising 0.15 (untuned), PROMISING_MIN_TRIES 3 (`statelib/start_pick.py:20-22`).
- Level bands: `explorer/xp_spots.py:21` BAND_WIDTH = 5 (L5-9, L10-14); `grind/xp_buckets.py` BUCKET = 5; the xp_spots ledger is
  measurement only, it picks no spot.
- Stall watchdog: `tools/swarm_watch.py:25-28` WINDOW_PRESSES = 600, HUNG_S = 120 (README's "two minutes" is correct).
- Bill's house: three stages (monster, console, human), stage read from the RAM sprite table, never from vision (`goal_talk_bill.py:1`).

## 6. What NOT to do

- No code changes, no test changes, no config changes, nothing under src/, tools/, tests/, kb/, runs/.
- No files outside docs/ and README.md. Do not edit any file in docs/directives/ (no Queue edits, no status changes).
- No ROM content: no ROM bytes, no hex dumps of ROM regions, no ROM download links, no instructions for obtaining a ROM. Leave the
  README's existing "bring your own ROM" wording as it is; do not add to it.
- No personal data: no tokens, keys, machine names, usernames, employer or client names, no private paths outside the repo.
- Native Dear PyGui only. Do not document, link or propose the web view (`--web`, `tools/webview.py`) or any browser UI.
- Do not call it a product or a benchmark; it is an exploration/experiment project.
- Do not touch process state: do not start the viewer, a swarm or a run to check a claim; read code and help text only.

## 7. Verification (each command run successfully on main, 2026-11-15)

```
uv run python --version
```
Expected: `Python 3.12.12`.
```
uv run pytest -q -p no:cacheprovider --co 2>&1 | tail -1
```
Expected: `3282 tests collected in ...s` (may be higher on your branch; must not drop; no collection errors).
```
uv run pytest -q -p no:cacheprovider -rfEs tests/test_frame_slot_layout.py tests/test_swarm_handoff.py 2>&1 | tail -1
```
Expected: `41 passed, 1 warning in ...s` (the only two test files that reference docs/ paths). Run the full suite
`uv run pytest -q -p no:cacheprovider -rfEs` only if the machine is idle (about 5 minutes); it must stay 0 failed.
Do NOT use `-p xdist -n 4`: pytest-xdist is not installed here and the command errors.
Do NOT run `uv run pokeagent ... --help` (not on the dispatch allow list). Every flag you document must appear in the
help text pasted in section 5; if a flag is not there, leave it out.
`uv run pokeagent bytecheck scan` needs `runs/bytecheck/index.npz`, which needs the ROM and is absent in a worktree (it exits with
"no bytecheck index"); it is NOT usable for this run. Run these text checks instead (not run by the author; the first must print
nothing, the second must print nothing except possibly the existing "bring your own ROM" paragraph):
```
git diff origin/main --name-only | grep -v -E "^(docs/|README.md$)"
git diff origin/main | grep -n -i -E "rom download|api[_-]?key|token|password"
```
Also check every relative link you added resolves: `ls` each target.

## 8. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. Never install, download or fetch anything.
- Never read outside the worktree. No scratch or debug files except under `.devin-scratch/`.
- Do not search or hunt for a missing file. If a file named here is missing, stop and write why in the Status row.
- Work only on branch `directive/pokeagent-docs-refresh`. Never commit to main, never push, never merge. Commit on the branch only.
- Run commands with `uv run`, never bare python.

## 9. Completion criteria

- Items 1-20 each resolved, or listed as "left out: reason" in the Report.
- Three new docs exist and are linked from README.md; none over 150 lines.
- All section 7 checks pass; the diff touches only docs/ and README.md; test count did not drop; 0 failed.
- Status row set to Review with the diff stat.

## 10. Report

Findings first: per item number, DONE / LEFT OUT (reason). Then the diff stat, then the real tails of each section 7 command.
List every claim you could not verify and therefore omitted. State no conclusions about why any run stalled.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Approved |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-15 18:54 · robert-claude-laptop · none → Queued
- 2026-11-15 20:09 · robert-claude-laptop · Queued → Approved — lint override: Remaining hits are gitignored runs/ paths the directive only names, and docs/CLI.md, docs/TRAINING.md, docs/OPERATING.md which the directive creates.
<!-- queue:end -->
