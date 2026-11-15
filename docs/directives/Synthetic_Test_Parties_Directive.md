# PokeAgent: synthetic test parties - build fixed-party drill states from the clean seeds with the existing state surgery, labelled synthetic, and promote a result only after an organic run reproduces it

**Depends on `Save_Library_And_Party_Gate_Directive.md` merged** (it adds the team fingerprint `fp["team"]` with moves in `src/pokeagent/statefp.py`, `src/pokeagent/team_fp.py` with `build_key`, `src/pokeagent/party_rules.py`, the library index `runs/states/library.json` in `src/pokeagent/statelib/library.py`, and `pokeagent states library build|list|validate`). If `git grep -n "def build_key" -- src/pokeagent/team_fp.py` finds nothing at the start of the run, stop and write that in the Status row; do not recreate those modules. Base: a main that contains that directive. <!-- new: src/pokeagent/team_fp.py --> <!-- new: src/pokeagent/party_rules.py --> <!-- new: src/pokeagent/statelib/library.py --> <!-- new: runs/states/library.json -->

The two behaviours these drills test are `Lead_And_Wild_Switch_Directive.md` (lead with a member that can hurt the foe, never lead a Harden-only Kakuna) and `PP_Zero_Move_Guard_Directive.md` (never press a 0-PP move, Struggle path). This directive does NOT depend on them: it builds the test states; Claude runs the drills after they merge.

## Why this exists

Robert, 2026-11-07, standing rule: "We can use synthetic data and states and saves throughout, with a standing rule that a synthetic result must be verified by organic data and states and saves, as a proof system." Robert, 2026-11-14: the agent leads with the weakest member until it faints, presses Ember with 0 PP, and carries a wild Harden-only Kakuna; each needs a fixed party to test on, and waiting for the swarm to stumble into one organically takes days.

What exists on main today (read by Claude 2026-11-14, read-only):

- State surgery since 2026-11-07: `tools/state_edit.py` (whitelisted RAM edits, output stamped synthetic with parent, edited, edit_class and legal keys; refuses position edits without `--unsafe-pos`; refuses OUT under `runs/checkpoints/` or `runs/segments/`; default OUT dir `runs/edited`), `src/pokeagent/surgery.py` (the whitelist is heal, set_hp, set_level, money, respawn, give, take, position), `src/pokeagent/legality.py` plus `src/pokeagent/legality_party.py` (`check`; invariants party_structure, party_stats, party_exp, party_moves, party_pp, party_evolution), `src/pokeagent/lineage.py` (`edit_class`, `promote`), commit 05b2f03 (legality check, organic envelope, lineage and `states promote`). Synthetic states are gated out of the curriculum: `statelog._kept` skips lineage synthetic, and the `tools/seg_store.py` `ckpt` fallback skips `statefp.is_synthetic`.
- The whitelist cannot change a party: nothing writes a species, a move id, a PP byte or a new party slot, and `set_level` only raises a level and keeps the species. So the four drill parties below are NOT reachable today; this directive adds exactly one whitelisted edit for them (`set_mon`), with a legality rule and tests, and nothing broader.
- Nothing has used synthetic states yet: no synthetic or promoted lineage exists among the `runs/checkpoints` and `runs/legs/states` sidecars (Claude checked 2026-11-14).
- Clean, Kakuna-free seeds exist locally (gitignored, NOT in your worktree): `runs/clean_seeds_2026-11-14/` holds `54_4_13.2` (Pewter Gym door: Charmander L9 + Weedle L4), `13_8_0.2`, `47_4_7.2`, `2_19_35.2` and `to_route2` (Charmander L14, Pidgey L8, Rattata L8), each as a `.state` plus a `.fp.json`. Tests never read them.

## Scope (in this order)

1. `src/pokeagent/surgery_mon.py` <!-- new: src/pokeagent/surgery_mon.py --> - the `set_mon` plan function. Under 150 lines. `src/pokeagent/surgery.py` - register it in `WHITELIST`, `_PLAN` and `_CONFLICTS` (three small changes; `surgery.py` stays under 260 lines).
2. `src/pokeagent/legality_party.py` and `src/pokeagent/legality.py` - one new invariant `party_names` (below), registered in `_INVARIANTS` beside the other party checks.
3. `src/pokeagent/synth_party.py` <!-- new: src/pokeagent/synth_party.py --> - the recipe registry: pure functions from a team summary to an edit dict. Under 150 lines.
4. `tools/state_edit.py` - add `--recipe NAME` and `--list-recipes`; stamp `recipe` into the output fingerprint. No new CLI program.
5. `src/pokeagent/synth_proof.py` <!-- new: src/pokeagent/synth_proof.py --> and `src/pokeagent/statescmd.py` - the proof record and `pokeagent states proof record|report`. synth_proof.py under 90 lines.
6. `src/pokeagent/statelib/library.py` and `src/pokeagent/statescmd.py` (`states library list`) - lineage and recipe in each index entry; `runs/edited` scanned as tier "drill"; `library list` shows lineage. Smallest possible change to the dependency's code.
7. Tests (all synthetic, `FakeEmulator` + `tmp_path`): `tests/test_surgery_mon.py`, `tests/test_synth_party.py`, `tests/test_synth_proof.py`, `tests/test_synth_library.py` <!-- new: tests/test_surgery_mon.py --> <!-- new: tests/test_synth_party.py --> <!-- new: tests/test_synth_proof.py --> <!-- new: tests/test_synth_library.py -->.
8. `docs/KNOWLEDGE.md` - a short "Synthetic test parties" paragraph: the recipes, the hypothesis rule, where drill states live.

## The work

Existing facts, pasted because the worktree has no `runs/` and you must not search. `uv run python --version` prints `Python 3.12.12`.

```
# src/pokeagent/surgery.py
class SurgeryError(ValueError)
WHITELIST = ("heal", "set_hp", "set_level", "money", "respawn", "give", "take", "position")
@dataclass(frozen=True) class _Ctx: max_pp (move id -> base PP | None), base_stats (species id -> dict | None), growth (species id -> group | None)
_PLAN = {"heal": _heal, ..., "position": _position}          # each: fn(emu, value, ctx) -> list[(addr, new_byte)]
_CONFLICTS = (("give","take"), ("heal","set_hp"), ("heal","set_level"), ("set_hp","set_level"))
def apply(emu, edits: dict, *, max_pp=None, base_stats=None, growth=None) -> list[(addr, old, new)]   # validates every edit before the first write
# _set_level shows the stat recompute to copy: stats.dvs(mon), stats.stat_exp(mon), stats.stat_value(base, dv, stat_exp, level, hp=...),
#   exp_for_level(growth, level) from pokeagent.grind.xpmath; writes level at +3 and +33, max HP +34/+35, stats +36..+43, exp +14..+16, big-endian.
# src/pokeagent/ram_symbols.py (re-exported by ramstructs): PARTY_COUNT 0xD163, PARTY_SPECIES 0xD164 (0xFF terminated), PARTY_MON1 0xD16B,
#   PARTY_MON_SIZE 44, MAX_PARTY 6, PARTY_MON_OT 0xD273 (11 chars per slot), PARTY_MON_NICKS (11 chars per slot, 0xD2B5)
# party_struct offsets: 0 species, 1-2 HP, 3 box level, 4 status, 5-6 types, 7 catch rate, 8-11 moves, 12-13 OT id, 14-16 exp,
#   17-26 stat exp, 27-28 DV word, 29-32 PP (low 6 bits PP, top 2 bits PP Ups), 33 level, 34-35 max HP, 36-43 attack/defense/speed/special
# src/pokeagent/legality.py: check(emu, kb, *, catalog=None, hm=None, rom=None) -> Legality(ok, violations, warnings, checked); read-only, never raises.
#   party_pp only checks the UPPER bound (PP 0 is legal); party_evolution flags an evolved form below its pre-form's level; party_moves flags a move id
#   not in the moves table or a non-zero move after an empty slot, and WARNS (not fails) on a move it cannot prove learnable.
# tools/state_edit.py: main(argv) -> int; make_emulator(rom); _edits(a) -> dict; _legality_inputs() -> (kb, catalog, hm); _max_pp(); _growth();
#   the output fingerprint is built by statefp.stamp(emu, out, source_run=f"edit:{name}") then .update(synthetic=True, edited=edits, parent=name,
#   lineage="synthetic", edit_class=..., edit_context=..., legal=...). lineage.edit_class returns "shortcut" for any edit name it does not know (set_mon included).
# src/pokeagent/statefp.py: stamp, read(state), write(state, fp), lineage_of(fp), lineage(state), is_synthetic(state); sidecar suffix ".fp.json"
# from the dependency (Save_Library_And_Party_Gate_Directive.md): fp["team"] = list of members, each with keys species, level, moves (4 ids), hp, max_hp, ot_id, exp;
#   team_fp.build_key(fp, kb) -> str | None; party_rules.violations(fp, kb) -> list[str]; party_rules.verdict(fp, kb) -> "clean" | "violation" | "unknown"
# src/pokeagent/explorer/catch_list.py: wild_never_catch(name, moves) is true for KAKUNA knowing only HARDEN (moves are NAMES)
# src/pokeagent/knowledge/kb.py: table(kb, key) -> dict; tables used: "name_of_internal" ("113" -> "KAKUNA"), "moves" ("106" -> name, power, pp, ...),
#   "dex_of_internal", "species_by_dex" (row keys include name, growth, hp/atk/def/spd/spc, type1, type2, moves1), "learnsets" (name -> learnset [[level, move name], ...], evolves)
```
Species ids in this save family, for TESTS only: WEEDLE 112, KAKUNA 113, CHARMANDER 176, CHARMELEON 178. Production code resolves names through `table(kb, "name_of_internal")` and `table(kb, "moves")` and never hard-codes an id. Without ROM tables those tables are empty: every new function takes `kb` explicitly and tests pass a small synthetic dict with fabricated ids (see `KB` at the top of `tests/test_legality.py` for the style: name_of_internal, dex_of_internal, species_by_dex with growth and base stats, learnsets, moves with pp). Copy the pieces you need into your own test module; do not import one test module from another.

### 1. `set_mon` (surgery_mon.py)

One new whitelisted edit. Its value is a dict from slot number to a spec dict. Spec keys, all optional except where stated: `species` (internal id), `level` (1..100), `moves` (up to four move ids), `pp` (one value per move, 0 up to that move's base PP, no PP Ups), `hp` (default: full). A slot equal to the current party count APPENDS a new member (the spec must then carry `species` and `level`); the count may not pass `MAX_PARTY`. Any other slot must be an existing one. Omitted keys keep the slot's current bytes. Everything is validated before the first write (raise `SurgeryError`, writing nothing). The plan:

- species: write the struct byte (+0) and the species list entry at `PARTY_SPECIES + slot`; for an append also write `PARTY_COUNT` and the 0xFF terminator after the last list entry.
- level and stats: recompute exactly as `_set_level` does (DVs and stat exp from the slot's existing bytes; for an appended slot use the DV word 0xAAAA and stat exp zero; base stats from `ctx.base_stats(species)`), HP = `hp` or max HP, status byte 0, exp = `exp_for_level(growth, level)` for the species' growth group. Missing base stats or growth group: `SurgeryError`, as `set_level` does. Unlike `set_level`, `set_mon` may LOWER a level (the recompute keeps the struct self-consistent).
- types (+5, +6): from the kb species row keys `type1` and `type2` (`src/pokeagent/knowledge/party.py` reads these). Catch rate (+7) and OT id (+12, +13): kept for an existing slot; for an append the OT id is copied from slot 0 and the catch rate is 0.
- moves (+8..+11) and PP (+29..+32): moves written then zero-padded to four; PP bytes from `pp`, validated against each move's table PP; a move without a `pp` value gets its table base PP; an empty move slot gets PP 0.
- names: for an append write the 0x50 string terminator as the first byte of the new slot's 11-byte nickname field (`PARTY_MON_NICKS`) and OT-name field (`PARTY_MON_OT`) so the game never reads garbage. A replace leaves names alone.
- conflicts: add the pairs set_mon with heal, set_mon with set_hp, and set_mon with set_level to `_CONFLICTS` (they write the same bytes). The bag edits are independent and need no pair.
- `lineage.edit_class` must keep returning `shortcut` for it (it already does for unknown names): add a test that asserts it and do not change `lineage.py`.

New legality invariant `party_names` (in `legality_party.py`, registered in `legality._INVARIANTS`): for each party slot, the nickname field and the OT-name field must contain a 0x50 terminator within their 11 bytes. A field of 11 bytes with no 0x50 is a violation; an all-zero field is treated as legal (a bare test fixture has no names). Real organic states satisfy it (the game writes both); an appended slot without the terminator fails, which is the point. The existing `tests/test_legality.py` fixture must keep passing unchanged. State in the Report how the all-zero case was handled.

### 2. Recipes (synth_party.py)

```
class RecipeError(ValueError)                       # the seed's party does not meet a recipe's precondition
RECIPES: dict[str, Recipe]                          # name -> Recipe(name, summary, build)
def plan(name: str, team: list[dict], kb: dict | None) -> dict     # team = fp["team"] of the seed; returns an edit dict for surgery.apply
def names() -> list[str]
```
`plan` resolves species and move names to ids through `table(kb, ...)` and returns an edit dict whose only key is `set_mon` (recipes use no other edit, so legality and lineage see one thing). No kb tables: `RecipeError` saying it needs kb/rom_tables.json. Every recipe states its preconditions and raises `RecipeError` with the reason when the seed misses them.

- `weedle_trainee` (precondition: a CHARMANDER-line member in slot 0 and a WEEDLE-line member in some slot): slot 0 becomes CHARMELEON L16 with moves SCRATCH, GROWL, EMBER, LEER (all at base PP); the WEEDLE slot becomes WEEDLE L5 with POISON STING and STRING SHOT. Purpose: a Charmeleon that can lead and a Poison Sting trainee that must not faint (drill for `Lead_And_Wild_Switch_Directive.md`).
- `harden_kakuna` (precondition: at most five party members): keeps the seed party and APPENDS a KAKUNA L7 knowing only HARDEN (the lowest level at which a Kakuna is legal; `party_evolution` flags it lower). Purpose: a wild Harden-only Kakuna that the gate must flag (the `party_rules` verdict is violation, `wild_never_catch` is true) and the lead rule must never lead. The output is a deliberate NEGATIVE CONTROL: it lives under `runs/edited`, is labelled by its `recipe` key, and `states library validate` listing it as a violation is the expected result.
- `pp_zero_ember` (precondition: a CHARMANDER or CHARMELEON member whose moves include EMBER and at least one of SCRATCH or TACKLE): that member keeps its moves, EMBER gets PP 0, SCRATCH and TACKLE keep base PP. Purpose: the Ember-with-no-PP loop (drill for `PP_Zero_Move_Guard_Directive.md`).
- `all_pp_zero` (precondition: a non-empty party): every move of every member gets PP 0. Purpose: the Struggle path.

Each recipe's output must pass `legality.check` with no new violation against the seed (it is plain Gen 1 structure: species, level, recomputed stats and exp, moves from the learnset, PP within the table).

### 3. The CLI (state_edit.py)

`--list-recipes` prints name, a tab, then the summary, one per line, and exits 0. `--recipe NAME` loads the seed in the emulator, reads `statefp.fingerprint(emu)["team"]`, calls `synth_party.plan(NAME, team, kb)` with the kb from `_legality_inputs()`, and uses the returned dict as THE edits (it may not be combined with `--heal --money --respawn --give --take --set-hp --set-level --pos`: exit 2 with the reason). A `RecipeError` prints `refused: <reason>` and exits 2. The default OUT becomes `runs/edited/<seed stem>.<recipe>.state`. Everything else is the existing path: legality before and after, `--allow-illegal`, `--dry-run`, `--force`, the refusal under `runs/checkpoints` and `runs/segments`, the synthetic stamp. After the existing `fp.update(...)` add the keys `recipe` (the name) and `synthetic_reason` (a plain string "drill party: <name>") before `statefp.write`.

### 4. Lineage and the library

- Every recipe output is stamped by the existing path: synthetic, parent = the seed's file name, edited = the set_mon edit, plus `recipe`. Do not weaken any of it.
- `src/pokeagent/statelib/library.py`: the Entry gains `lineage` (organic, synthetic or promoted, via `statefp.lineage_of`) and `recipe` (null unless present), and the build scans `runs/edited` as tier `drill` in addition to the dependency's default dirs. Tier `drill` entries are never ranked or dropped by `retain`, never get a `segment`, and never count as a checkpoint or a best. `states library list` prints lineage and recipe as two more columns and accepts `--lineage organic|synthetic|promoted`. If `states library compare` exists on main (`git grep -n "def compare_rows" -- src/pokeagent/statelib/`), pass lineage through its rows too; if it does not exist, do nothing for it and say so in the Report.
- The curriculum gate is already in place; add tests that pin it for a recipe output: `statelog.select` and `pick` never return it, `tools/seg_store.py` `ckpt` never returns it, and `lineage.edit_class` keeps it `shortcut` so `states promote` refuses it. Do not change `statelog.py`, `seg_store.py` or `lineage.py`.

### 5. The proof hook (synth_proof.py)

A result born on a synthetic state is a HYPOTHESIS: usable for drills, A/B runs and planning, never a chain best, a confirmed segment, a KNOWLEDGE fact or a shared-memory veto until an organic run reproduces it. Keep the machinery minimal: a record file and a status.

```
PROOF_FILE = Path("runs/edited/proof.json")            # a document with key v (1) and key records (a list of Record dicts)
# Record keys: recipe, claim, build, lineage, run, passed, steps, recorded.  claim is a short id such as "weedle-evolves-within-300-steps"
def record(path, *, recipe, claim, start_state, run, passed, steps=None, kb=None) -> dict
    # build = team_fp.build_key(statefp.read(start_state), kb); lineage = statefp.lineage_of(statefp.read(start_state))
def status(records, recipe, claim, build) -> "hypothesis" | "confirmed" | "contradicted" | "unknown"
def report_lines(records) -> list[str]
```
`status`: `unknown` when there is no record for that recipe and claim; `hypothesis` when only records whose lineage is synthetic exist; `confirmed` when at least one ORGANIC-lineage record with the same claim and the same `build` has `passed` true and no organic record with that claim and build failed; `contradicted` when an organic record with that claim and build has `passed` false (the organic result wins over the synthetic one). A promoted lineage does NOT count as organic here. `report_lines` prints one line per recipe and claim: `<recipe> / <claim>: hypothesis (synthetic only, N run(s); needs an organic run with build <build>)`, or `confirmed (organic run <run>)`, or `contradicted (organic run <run> failed)`. The file is written atomically (`pokeagent.goexplore.store.atomic_write(path, text)`); a missing or corrupt file reads as no records, never an exception.

`pokeagent states proof record --recipe R --claim C --start STATE --run RUN --passed|--failed [--steps N]` and `pokeagent states proof report` (no emulator, no ROM; `report` always exits 0). Add both under the existing `states` parser; keep every existing subcommand unchanged. This is a status field and a report line, not a new system: no store beyond `proof.json`, no scheduler, no daemon.

## What NOT to do

- Do not run any emulator, and do not read `runs/`, `roms/` or `baselines/`: there is no ROM or `runs/` in your worktree. Tests use `FakeEmulator`, `tmp_path` and fabricated bytes only (`world()` in `tests/test_surgery.py` is the existing small fixture: two party mons at 0xD16B, one bag stack; copy its shape into your own test module).
- Do not add an edit beyond `set_mon`; do not touch `position`, and do not make any recipe use `--unsafe-pos`.
- Do not change `statelog.py`, `tools/seg_store.py`, `lineage.py`, `lineage.promote`, `party_rules.py` or `team_fp.py` (the dependency's code is read, not edited, except the Entry and list-column change in `statelib/library.py` and `statescmd.py` named above).
- Do not write a synthetic state to `runs/checkpoints`, `runs/legs/states` or `runs/segments`, and do not let any recipe output be promoted: recipe states are `shortcut` class by design. The proof is on RESULTS, not on states.
- Do not change catch, battle, lead or PP code (the two other directives own it), `tools/swarm.py`, or any live checkout.
- Do not hard-code species or move ids in production code; resolve names through the kb tables.
- Do not state where any game copy came from. States, ROMs and `runs/` are local and gitignored; never add one as a fixture.

## Verification (exact commands)

```
uv run --frozen pytest -q -p no:cacheprovider tests/test_surgery_mon.py tests/test_synth_party.py tests/test_synth_proof.py tests/test_synth_library.py
```
Expected: all pass. They must cover: each recipe on a fabricated seed (the resulting party read back with `read_party`: species, level, moves, PP, count; the species list and terminator; `legality.check` with the test KB reports no new violation); every `RecipeError` precondition; `set_mon` validation failures write nothing; an append past six refused; `party_names` flags an appended slot without a terminator; `plan` output has only the `set_mon` key; `state_edit.main` with `--recipe` stamps recipe, synthetic lineage, parent and edit_class shortcut, refuses a flag combination, and `--list-recipes` lists four names; proof `status` for unknown, hypothesis, confirmed, contradicted (and a promoted lineage not counting as organic); library entries carry lineage and recipe, tier `drill` is never retained-dropped, and `select`, `pick` and `ckpt` never return a recipe output.

```
uv run --frozen pytest -q -p no:cacheprovider tests/test_surgery.py tests/test_legality.py tests/test_statelog.py tests/test_lineage.py tests/test_states_legal_cli.py
```
<!-- new: tests/test_team_fp.py --> <!-- new: tests/test_party_rules.py --> <!-- new: tests/test_state_library.py --> <!-- new: tests/test_states_library_cli.py --> <!-- new: tests/test_state_gate_enforcement.py -->
Expected: no new failures. Claude ran this exact command on main while writing the directive: `107 passed, 1 warning in 7.79s`. Also run the dependency's test files once it has merged (`tests/test_team_fp.py tests/test_party_rules.py tests/test_state_library.py tests/test_states_library_cli.py tests/test_state_gate_enforcement.py`), unchanged.

```
git diff --stat origin/main -- src/pokeagent tools
```
Expected: the files in Scope only.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download or fetch. Never read outside the working directory. Do not search, glob or hunt: if a file named here is missing, stop and write that in the Status row.
- Use `uv run --frozen` for every command.
- THE STANDING RULE FOR SYNTHETIC STATES (Robert, 2026-11-07): a synthetic result must be verified by organic data, states and saves. A record born synthetic is a hypothesis: usable for drills, A/B runs and planning, never a chain best, a confirmed segment, a KNOWLEDGE fact or a shared-memory veto until an organic run reproduces it. Code, docs and the Report you write say "hypothesis" for such a result until `synth_proof.status` says `confirmed`.
- Branch only (`directive/pokeagent-synthetic-test-parties-directive`); commit as you go; never commit to or push main; never merge.
- Create no scratch or debug files; anything temporary goes under `.devin-scratch/`.
- If blocked, stop and write why in the Status row. Status row done means `Review`, with the diff stat and test tails in the Report.

## Completion criteria

- [ ] `set_mon` is whitelisted, validates before writing, builds a self-consistent party struct (species list, terminator, count, recomputed stats and exp, moves, PP, names) and conflicts with heal, set_hp and set_level. <!-- test: tests/test_surgery_mon.py -->
- [ ] `party_names` flags an unterminated appended slot and the existing legality tests pass unchanged. <!-- test: tests/test_surgery_mon.py -->
- [ ] The four recipes build legal parties from a fabricated seed (harden_kakuna also fails the party rule on purpose) and refuse a seed that misses a precondition. <!-- test: tests/test_synth_party.py -->
- [ ] `state_edit.py --recipe NAME` and `--list-recipes` work through the existing synthetic stamp, add `recipe`, and refuse combination with other edit flags. <!-- test: tests/test_synth_party.py -->
- [ ] Library entries show lineage and recipe, tier `drill` is never retained-dropped or ranked, and no recipe output is selectable as a checkpoint start or chain best. <!-- test: tests/test_synth_library.py -->
- [ ] `synth_proof.status` returns hypothesis until an organic record with the same build and claim passed; `states proof record|report` run without a ROM. <!-- test: tests/test_synth_proof.py -->
- [ ] The five existing test files above pass unchanged; the dependency's test files still pass.
- [ ] Status row set to `Review` with the evidence above.

## Report

Diff stat, test tails, which new files are under their line caps, whether `library compare` existed (and was extended or skipped), and how `party_names` treated all-zero name fields. Then the steps Claude runs afterwards, with the ROM and the real `runs/` (Devin cannot; the worktree has no `runs/`; nothing here is queued or run by this directive):

1. After this and the Lead/Wild-Switch and PP-Zero-Guard directives merge: build the four drill states from the clean seeds, one at a time: `uv run python tools/state_edit.py runs/clean_seeds_2026-11-14/54_4_13.2.state --recipe weedle_trainee`, then `harden_kakuna` and `pp_zero_ember` on the same seed, and `all_pp_zero` on `runs/clean_seeds_2026-11-14/to_route2.state`. Read each legality line; any refusal is reported, not forced.
2. Run each drill headless for a few hundred steps from its `runs/edited/*.state` (not on Robert's screen, swarm paused first) and record each result with `states proof record` (lineage synthetic, so it reads hypothesis).
3. Reproduce each result ORGANICALLY from the clean seeds (a run from an organic start whose `build_key` matches) and record that too; only then may a result leave hypothesis status, and only `states proof report` showing confirmed lets it into a chain best, KNOWLEDGE or shared memory.

## Forbidden Actions

- ROMs, extracted game art, save states and anything derived from them are local and gitignored. Never commit them or add one as a fixture.
- Never state, in code, comments, docs, commit messages or the report, where any game copy came from.
- Do not run `uv lock`, `uv sync`, any install or download, any queue verb (approve, dispatch, mark Done), `agentflow lint --all`, or janitor.
- Do not open a window or send input.
- Do not commit to or push main, merge, or deploy.

## Required from User

- The post-merge ROM steps in the Report section, run by Claude with the swarm paused. Nothing here blocks the run.

## Sandbox needs

- Exec(uv run --frozen pytest)
- Exec(git diff)
- Exec(git grep)
