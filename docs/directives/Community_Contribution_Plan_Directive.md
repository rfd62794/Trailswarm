# Trailswarm: write the sharing inventory and the ranked community-contribution plan (documentation only)

**Size:** S. **Assignee:** devin.

## 1. Why this exists

Robert, 2026-11-08, settled: the project is public (rfd62794/Trailswarm, MIT) and he wants it to add something new to the Game Boy RAM and agent community, without publishing anything that is not ours to publish. Two things are missing:

- A single page saying what the project can share and what it cannot. Today the answer is spread across `docs/LEGAL.md` and habit.
- A ranked plan saying where the project can contribute something new, backed by evidence from the repo's own research report and nothing else.

This directive writes those two documents. It writes no code, no data and no tests.

## 2. Scope

Exactly three new files. Nothing else is created or edited.

1. `docs/SHARING.md` <!-- new: docs/SHARING.md --> - the inventory. Structure in section 3.
2. `docs/plans/Community_Contribution_Plan.md` <!-- new: docs/plans/Community_Contribution_Plan.md --> - the ranked plan. Structure in section 3.
3. `tests/test_sharing_docs.py` <!-- new: tests/test_sharing_docs.py --> - the checks on those two documents, given in full in section 5. Under 80 lines.

## 3. The work

Write in plain, direct language. No marketing words ("revolutionary", "cutting-edge", "unlock", "seamless"). Short sentences. Say what is true, what is not known, and who decides.

### Facts you need (pasted; the worktree has the two source documents, but everything load-bearing is here)

**Fixed sharing rules (settled by the owner; state them as rules, do not soften or add exceptions):**

1. ROMs are never published.
2. ROM-derived tables under `kb/` (`rom_tables.json`, `hm_compat.json`, `items.json`) stay private. Datasets of extracted game art (for example sprite and tile crops under `runs/vision/`) stay private.
3. Emulator save states may be published, for demos and tests.
4. Trained weights wait for the owner's decision.
5. Where a game copy came from is never stated in any published text.
6. `pokered.sym` is not redistributed. Labels derived from it are credited as `docs/LEGAL.md` credits them.

**From `docs/LEGAL.md` (current text, condensed):**

- The MIT License covers original code and documentation only. It grants no rights in any game.
- Not in the repository: ROM images or any copy of game software; boot ROMs, firmware, keys; extracted game graphics, audio or text as data files (other than one documentation image); links to, or instructions for obtaining, game software.
- `roms/`, `baselines/` and `runs/` are gitignored, plus the three generated files under `kb/`: `rom_tables.json`, `hm_compat.json`, `items.json`.
- Earlier commits briefly held tables generated from a local ROM (moves, type chart, species names, items, HM compatibility). They are not in the current tree but remain in git history. A rights holder who wants them removed from history can open an issue.
- In the repository: original source, tests, documentation, plus memory addresses, labels and goal names. One documentation image, `docs/media/world.gif`, shows agent runs on a map rendered from the game's own graphics; it will be removed on request. Emulator save states may be included where they help demonstrate or test the software.
- RAM labels in `src/pokeagent/data/ram_map.json` derive from pret/pokered's `pokered.sym`. That repository publishes no licence file, so the symbol file itself is not redistributed.
- Videos and streams: only from lawfully held copies; add real commentary or analysis; follow the publisher's current rules for that specific game, checked before publishing.
- Third-party: PyBoy (LGPL-3.0) is an unmodified, separately installed dependency. A future GPL dependency would be an optional extra, never bundled.

**What exists in the repo that could be shared (for the inventory), with its real location:**

| Item | Location | Notes |
|---|---|---|
| Source code, tests, docs | `src/`, `tests/`, `docs/`, `tools/` | MIT |
| RAM labels and addresses | `src/pokeagent/data/ram_map.json` (2792 entries, 107 flagged verified) | derived from `pokered.sym`; credited in LEGAL.md |
| ROM-derived tables | `kb/rom_tables.json`, `kb/items.json`, `kb/hm_compat.json` | gitignored, so missing in a fresh worktree |
| ROM images | `roms/` | gitignored |
| Start-of-game and checkpoint save states | `baselines/*.state`, `runs/checkpoints/*.state` | gitignored today |
| Agent shared memory (learned maps, plus text read from the screen) | `runs/maps.json` | gitignored, so missing in a fresh worktree; holds dialogue and menu text |
| Run logs and frames | `runs/` | gitignored |
| Sprite and tile crop datasets | `runs/vision/<game>/` | extracted game art; gitignored |
| Trained model weights | local models directory (planned) | none published |
| Documentation image | `docs/media/world.gif` | the single exception LEGAL.md names |
| Research report and notes | `docs/research/` | own prose with third-party links |
| Sanitized progress export | tool being built in `Progress_Export_Sanitized_Directive.md` | not merged at the time of writing; check before claiming it exists |
| Measured address table | tool being built in `Measured_Ram_Address_Table_Directive.md`; the data file does not exist yet | the real table needs a run Claude does later |
| Videos and streams | outside the repo | LEGAL.md policy applies |

**From the research report `docs/research/reports/RAM ROM tooling for game agents.md`, by section name (use these exact section names when citing):**

- **"The authoritative sources are the disassembly, not the wikis"**: the pret/pokered disassembly is the authoritative WRAM label source.
- **"What agent projects actually read, and the standards worth adopting"**: community RL projects converged on a small address set (PokemonRedExperiments, MIT, reads map, X, Y, party species, HP, level, badges, money, event flags, opponent levels). pokemonred_puffer has a named-event table but shows no licence: design reference, not code to copy. stable-retro `data.json` convention: name, `address`, and a struct-like `type` string (endianness, then `i`/`u`/`d`/`n` for signed, unsigned, BCD, nibble-BCD, then byte count, for example `|u1`, `>u2`, `>d2`); Game Boy is supported there. "No existing JSON/YAML schema specific to Pokemon Red RAM, and no tool that auto-verifies an address table against the disassembly, was found in the research notes, so the project would be filling a real gap rather than duplicating one."
- **"NPC reading and the shared world map have a ready template"**: pokerl-map-viz (MIT) needs only `[x, y, mapId]` per agent over WebSocket JSON, and converts with an offset table in that project's own `assets` folder (an external file, missing from this repo). Interior placement in any world map is a heuristic, not in game data; a hand-corrected `map_id -> (x, y)` table is "the realistic approach". NPCs can share the same transform as agents. NPC tables hold only the current map, so a shared NPC map must be accumulated across runs. "No ready-made stitched full-world PNG with a known licence was found other than the community map used by pokerl-map-viz." The contents of `map_data.json` were not read.
- **"Writing is the frontier: link battles, trades and opponent injection"**: PyBoy ships an experimental two-instance serial cable example, demonstrated for Gen 1 trading only. "No published project automates a Gen 1 Colosseum battle between two emulated agents." Whether the Colosseum path works over the same serial layer is "a reasonable inference but untested". Save states are unsupported on linked instances, which rules out rollback for linked pairs. Which PyBoy release introduced serial support was not confirmed. The Gen 1 link RNG is documented (Smogon RBY link RNG thread); exact master/slave handshake bytes and the on-wire party layout were not found, and `home/serial.asm` in pret/pokered is the entry point to read. Opponent injection has precedent in technique (a RAM-randomiser project rewrites enemy trainer data every frame) but not in a PyBoy recipe; `read_trainer_party.asm` zeroes the enemy party count first, so injected data must be written after that routine runs; a `hook_register` on the symbol after the party load is the natural PyBoy equivalent, and it is unproven.
- **"Recommended module shape and open risks"**: licences: pokemonred_puffer none visible; pret/pokered's text was not retrieved (ROM data and assets are Nintendo/Game Freak IP regardless); Data Crystal is GNU FDL 1.2; Continual Harness is CC BY-NC-SA 4.0; treat these as reference, not code sources. Version drift: which pokered revision the `.sym` matches the ROM is unstated, and sprite field names changed in 2024. Unproven: Colosseum over PyBoy serial, injection timing, and `symbols=` loading of pokered `.sym`. Unread: Bulbapedia structures, pokecrystal, the `map_data.json` contents, `home/serial.asm`, Cheat Engine tables, tracker and overlay ecosystems beyond those found.
- **"Conclusion"**: "the novel work is not reading RAM ... but unifying three things that currently live in separate ecosystems": typed variable files (stable-retro), disassembly-derived labels (RGBDS `.sym`), and live multi-agent visualisation (pokerl-map-viz). The write side "deserves a time-boxed spike before design commitments", deciding three questions: whether PyBoy's serial cable can enter the Colosseum, whether a symbol-addressed hook reliably overwrites the enemy party after the trainer load, and whether pkmn/engine should carry search and training while PyBoy demonstrates on the real cartridge.

**Evidence available in the repo for the two entries the report does not cover:**

- Cold versus seeded run comparison: the swarm starts every agent from a copy of the shared memory `runs/maps.json` (`tools/swarm_merge.py`: "Every agent starts from a copy of the shared memory, so counts are taken as MAX, never summed"). The multi-game design spec (`docs/superpowers/specs/2026-11-06-layered-methods-design.md`) names the metric "hours from a cold start to the first goal, per game". `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` describes a Q table "seeded from Explorer runs". No document in the repo reports a measured cold-versus-seeded comparison; say so plainly. The project's own rule: synthetic runs may exist everywhere, but organic verification comes before a result counts. Sample size and seeds for any such comparison are not decided.
- Vision-model code and recipe: `docs/directives/Vision_Label_Recorder_Directive.md` and `docs/directives/Cheap_Sprite_Model_Directive.md` describe using game RAM and sprite tables as free labels for a small CPU-trainable sprite classifier, scored against a nearest-template baseline on held-out maps. The research report does not survey prior art for this, so do NOT claim a public gap; write that prior art is unchecked and must be checked first. Code and recipe can be published; the dataset of crops cannot (rule 2); the weights wait for the owner (rule 4).

### `docs/SHARING.md` structure (exact headings, in this order)

1. `# What this project can share`
   Two or three sentences: what the page is for, and that `docs/LEGAL.md` is the legal statement (link `LEGAL.md`). Say it is not legal advice.
2. `## Status words`
   Define exactly four words, each on its own line: `OK now`, `needs cleaning`, `private`, `owner's decision`. One sentence each.
3. `## Fixed rules`
   The six fixed rules above as a numbered list, in plain words. Rule 5 is worded: "Where a game copy came from is never stated in any published text." Add nothing else about game copies.
4. `## Inventory`
   ONE markdown table with the header `| Item | Where | Status | Why or condition |` and one row per line of the "what exists" table above (14 rows; split or add a row only if needed). Rules for the table:
   - Column 3 holds exactly one of the four status words and nothing else.
   - Assign statuses from the fixed rules and LEGAL.md. Required: ROM images `private`; the three `kb/` files `private`; sprite and tile crop datasets `private`; `runs/maps.json` `private` (text read from the screen); run logs and frames `private`; trained weights `owner's decision`; save states `OK now` (rule 3; say gitignored today and that publishing one is a choice); source/tests/docs `OK now`; `ram_map.json` labels `OK now` (credited as LEGAL.md describes); `docs/media/world.gif` `owner's decision` (it is the one image LEGAL.md names as an exception to the rule that extracted game art stays private; removed on request); videos and streams `owner's decision` (LEGAL.md policy must be met first); the sanitized progress export `needs cleaning` (does not exist until the tool merges; raw maps.json never ships); the measured address table `needs cleaning` (no data file exists yet).
   - Put `pokered.sym` in its own row: Where `pokered.sym (not in this repo)`, Status `private`, Why: not redistributed; the labels derived from it are the `ram_map.json` row above.
   - Never put a row's path in the Where column with the status `OK now` if it appears in rules 1, 2 or 6.
5. `## Before publishing anything`
   A short checklist (5 to 8 lines): check the Status column; confirm no ROM bytes, game text or extracted art; confirm no game copy provenance; run the repo's tests; credit labels as LEGAL.md does; nothing is published by an agent, the owner decides.

### `docs/plans/Community_Contribution_Plan.md` structure (exact headings, in this order)

1. `# Community contribution plan`
   Title block with the date 2026-11-08, status "plan, nothing here is built or promised", and a link to `../LEGAL.md`, `../SHARING.md` and `../research/reports/RAM ROM tooling for game agents.md`.
2. `## How the entries are ranked`
   Three or four lines: ranked by how well the evidence supports a real gap, how small and certain the work is, and what must be verified before starting. High novelty with no evidence ranks below small certain work.
3. `## What the research report flags as unverified`
   A bullet list stating plainly every unverified, untested or unread item from the report (collect them from the pasted facts: Colosseum over serial untested; the PyBoy release that added serial unconfirmed; handshake bytes and party wire layout not found; injection timing unproven; `symbols=` loading unproven; pret/pokered licence text not retrieved; revision drift and the 2024 sprite renames; `map_data.json` contents unread; `home/serial.asm` unread; stable-retro file wrapper not shown in the report). Add one more bullet: the report has no prior-art survey for vision models.
4. Five entry sections, in this order, each a level-3 heading numbered exactly as below:
   - `### 1. Measured Red and Blue address table and typed variable file`
   - `### 2. Shared world-map format`
   - `### 3. The writing side: link cable and opponent injection`
   - `### 4. Cold versus seeded run comparison, as a measured demo`
   - `### 5. Vision-model code and recipe`
5. `## Not on this list`
   Two or three lines: reading RAM (a solved problem per the report), publishing ROM-derived tables, datasets, or weights (decided elsewhere in `SHARING.md`).

**Each entry has exactly these six bold labels, in this order, each starting its own paragraph:** `**What exists publicly:**`, `**The gap:**`, `**What Trailswarm would contribute:**`, `**Effort:**`, `**Verify first:**`, `**Who decides:**`. Cite report section names in quotes (for example: see "Writing is the frontier: link battles, trades and opponent injection"). Content per entry:

1. Measured address table. Public: the pokered labels, the PokemonRedExperiments address set, stable-retro `data.json` convention. Gap: no Pokemon-Red-specific JSON/YAML schema and no tool that checks an address table against evidence (report's own wording, "in the research notes"). Contribute: the per-game status table (`measured`, `believed`, `not-exercised`) and a stable-retro style typed variable file, produced by `Measured_Ram_Address_Table_Directive.md`. Effort: small for the tool (in flight), moderate for the real run, which needs a game copy for each game; say Blue's run is not done. Verify first: that the `data.json` wrapper and Game Boy address base load in a real stable-retro install; which pokered revision matches the ROM; the pret/pokered licence text. Decide: the owner, for publishing the data file.
2. Shared world map. Public: pokerl-map-viz (MIT) with `[x, y, mapId]` and an offset table; a community hand-built Red/Blue map. Gap: no published project reads a shared world map of NPCs across agents (report, "Writing is the frontier..." intro and "NPC reading..." section; use the report's own words, "or reads a shared world map of NPCs across agents"). Contribute: a sanitized per-map format (walkable and blocked tiles, warps, counts, map ids) from `Progress_Export_Sanitized_Directive.md`, with NPC positions only after a cleaning decision, and a hand-corrected `map_id -> (x, y)` table. Effort: small for the format (in flight), moderate for NPCs and placement. Verify first: licence of the community map and `map_data.json` contents (unread); that NPC positions carry no game text. Decide: the owner.
3. Writing side. Public: PyBoy's trade example, the documented link RNG, a RAM-randomiser technique. Gap: no published Colosseum automation, no PyBoy opponent-injection recipe (report). Contribute: a working recipe and tests if the spike succeeds; a negative result is also a result. Effort: large and risky; start with the time-boxed spike the report asks for, answering its three questions. Verify first: everything in the unverified list that touches serial and injection; read `home/serial.asm`. Decide: the owner decides whether to commit to the spike; results are published only if the spike works or the owner chooses to publish a negative finding.
4. Cold versus seeded. Public: nothing found in the report; say "not covered by the report". Gap: not established; the repo has the metric name but no measurement. Contribute: a measured comparison of runs starting empty versus starting from shared memory, with seeds, step counts and failure counts, as a demo. Effort: moderate; needs many organic runs and a pinned commit. Verify first: sample size and seeds; that runs are organic, not synthetic; that no learned text from the screen is in any published artifact (use the sanitized export). Decide: the owner, and videos follow the LEGAL.md policy.
5. Vision model. Public: unchecked. Gap: not established; do not claim one. Contribute: publish the recorder and model code and the recipe (steps and hyperparameters), score against the template baseline; not the dataset (rule 2); weights only if the owner decides (rule 4). Effort: small to publish the code and recipe once the two directives merge; check that they have. Verify first: a prior-art search; that the code contains no crops or game art; that the recipe does not require stating where a game copy came from. Decide: the owner, for weights.

### Style limits

- No file over 600 lines; aim for `SHARING.md` about 90 lines and the plan about 160.
- No employer, client, workplace or personal information; refer to "the owner". No names of people.
- Say nothing about how or where any game copy was obtained, beyond rule 5's wording.
- Use ASCII hyphens and quotes.
- Relative links only, and each must resolve to a file that exists in the repo.

## 4. What NOT to do

- No code, no tests, no data files, no third file. Do not create `docs/data/` anything.
- Do not edit `docs/LEGAL.md`, `README.md` or any existing file.
- No ROM, no network, no installs, nothing read outside the worktree.
- Do not mark anything shared that rules 1, 2 or 6 forbid, or any ROM-derived file or extracted-art dataset as `OK now`.
- Do not claim a gap the report does not support, and do not claim anything is built that is not merged.
- Do not name any employer, client or workplace, and say nothing about game copy sources beyond rule 5.
- Do not touch `src/pokeagent/game`, `src/pokeagent/cli.py`, the emulator or the explorer; a separate Devin run is changing those.

## 5. Verification (exact commands, from the worktree root)

```
uv run python --version
```
Expected: `Python 3.12.x`.

The checks that were four inline scripts are one test file, `tests/test_sharing_docs.py`, which you write exactly as below (copy it; change nothing but formatting). It reads the two documents you write, so it fails until they are right.

```python
"""Checks on docs/SHARING.md and docs/plans/Community_Contribution_Plan.md."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARING = ROOT / "docs" / "SHARING.md"
PLAN = ROOT / "docs" / "plans" / "Community_Contribution_Plan.md"
FILES = (SHARING, PLAN)
SHARING_HEADS = ["# What this project can share", "## Status words", "## Fixed rules", "## Inventory", "## Before publishing anything"]
PLAN_HEADS = ["# Community contribution plan", "## How the entries are ranked", "## What the research report flags as unverified",
              "### 1. Measured Red and Blue address table and typed variable file", "### 2. Shared world-map format",
              "### 3. The writing side: link cable and opponent injection", "### 4. Cold versus seeded run comparison, as a measured demo",
              "### 5. Vision-model code and recipe", "## Not on this list"]
LABELS = ["**What exists publicly:**", "**The gap:**", "**What Trailswarm would contribute:**", "**Effort:**", "**Verify first:**", "**Who decides:**"]
FORBIDDEN = re.compile(r"employer|day job|dialer|contact.center|\bclient\b|torrent|romhub|archive\.org|dumped|ripped|downloaded|purchased|bought|\bRFD\b|Dugger", re.I)
STATUS_OK = {"OK now", "needs cleaning", "private", "owner's decision"}
PRIVATE_MARKS = ("roms/", "kb/rom_tables.json", "kb/items.json", "kb/hm_compat.json", "pokered.sym", "runs/vision", "runs/maps.json")


def _has_heading(text, heading):
    return re.search("^" + re.escape(heading) + r"\s*$", text, re.M) is not None


def test_required_headings_and_entry_labels():
    sharing, plan = SHARING.read_text(encoding="utf-8"), PLAN.read_text(encoding="utf-8")
    missing = [h for h in SHARING_HEADS if not _has_heading(sharing, h)] + [h for h in PLAN_HEADS if not _has_heading(plan, h)]
    assert missing == []
    assert [lab for lab in LABELS if plan.count(lab) != 5] == []


def test_no_forbidden_words():
    hits = [(f.name, i + 1) for f in FILES for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()) if FORBIDDEN.search(line)]
    assert hits == []


def test_inventory_rows_use_the_four_status_words_and_keep_private_things_private():
    lines = SHARING.read_text(encoding="utf-8").splitlines()
    rows = [ln.split("|") for ln in lines if ln.startswith("|") and not set(ln.strip()) <= set("|- ")]
    rows = [r for r in rows if r[1].strip() != "Item"]
    assert len(rows) >= 12
    assert [r[1].strip() for r in rows if r[3].strip() not in STATUS_OK] == []
    assert [r[1].strip() for r in rows if any(p in r[2] for p in PRIVATE_MARKS) and r[3].strip() != "private"] == []


def test_links_resolve_and_files_stay_short():
    broken = []
    for f in FILES:
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", f.read_text(encoding="utf-8")):
            if not target.startswith("http") and not os.path.exists(os.path.normpath(os.path.join(f.parent, target.replace("%20", " ")))):
                broken.append((f.name, target))
    assert broken == []
    assert max(len(f.read_text(encoding="utf-8").splitlines()) for f in FILES) <= 600
```

```
uv run pytest -q tests/test_sharing_docs.py
```
Expected: `4 passed`.

```
git status --short
```
Expected: only the three new files (plus nothing else).

## 6. Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt beyond the files named here. If something expected is missing, stop and write that in the PR description.
- Use `uv run` and Python 3.12 only.
- Never commit to main/master, never push to main, never merge, never deploy. Work stays on the directive branch; commit as you go.
- Do NOT edit anything between `<!-- queue:start -->` and `<!-- queue:end -->` in this file.
- Status row meaning: leave it to the pipeline. "Done" for this directive is Review with a pushed branch.
- Create no scratch or debug files outside `.devin-scratch/`; deleting files is denied in the sandbox.
- If a tool call is genuinely blocked, stop and write why in the PR description.

## 7. Completion criteria

- [ ] `docs/SHARING.md` has the five headings, the four defined status words, the six fixed rules and an inventory table whose every row uses exactly one status word. <!-- test: docs/SHARING.md -->
- [ ] No ROM, `kb/` table, extracted-art dataset, `runs/maps.json`, run log or `pokered.sym` row is anything other than `private`; trained weights are `owner's decision`; save states are `OK now`. <!-- test: docs/SHARING.md -->
- [ ] The plan has the five entries in the stated order, each with all six labels, citing report section names in quotes. <!-- test: docs/plans/Community_Contribution_Plan.md -->
- [ ] Everything the report flags as unverified is stated plainly, and the cold-versus-seeded and vision entries do not claim a public gap. <!-- test: docs/plans/Community_Contribution_Plan.md -->
- [ ] The forbidden-words, status, link and heading checks in section 5 all exit 0.
- [ ] Only the two named files were added.

## 8. Report

Findings first: any inventory row whose status you were unsure about and why, any claim in the plan you could not support from the pasted facts and therefore left out, and whether the two other directives (address table, progress export) are merged on your base, so the docs describe them correctly. Then the tails of the section 5 commands.

## Required from User

Nothing during the run. After review, the owner decides whether the status words in the inventory are right and whether anything is published; no agent publishes.

## Forbidden Actions

- Never edit `agentflow.toml`, scheduled tasks, or any protected repo (TeleseroAdminSuite2026, DialerListPulse).
- Never approve, dispatch or mark Done any row; never delete or close a queue row.

## Sandbox needs

- Read(docs/LEGAL.md)
- Read(docs/research/reports/RAM ROM tooling for game agents.md)
- Write(docs/SHARING.md)
- Write(docs/plans/Community_Contribution_Plan.md)
- Write(tests/test_sharing_docs.py)
- Exec(uv run python --version)
- Exec(uv run pytest)
- Exec(git status)

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-08 17:18 · robert-claude-laptop · none → Queued — Drafted by Claude at Robert's request 2026-11-08: sharing inventory and ranked plan for where the project can add something new
<!-- queue:end -->
