# PokeAgent: item balls - learn that the Poke Ball sprite is something to pick up (starters included)

**Read first:** `docs/superpowers/specs/2026-11-05-viewer-and-hybrid-design.md` section 5.
**Depends on:** `World_Legend_And_Ledges_Directive.md` merged (`explorer/legend.py`, `explorer/tilekind.py`).
If missing, stop and write that in the Status row. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "Can we teach it to pick up items, and that the pokeball image represents items to be
interacted with or picked up, including your first pokemon?"

Verified from the shared memory `runs/maps.json` on 2026-11-05 (sprite table: slot `pic` at 0xC1x0, position
from 0xC2x4/5 minus 4, as `MapMemory.observe_npcs` records it): **picture id 61 (0x3D) is the Poke Ball
sprite.** Every static pic-61 object seen so far:

| map | tile | what it is (recorded text) |
|---|---|---|
| 40 Oak's lab | (6,3) (7,3) (8,3) | the three starter balls |
| 13 Route 2 | (13,54) (13,45) | item balls (never interacted) |
| 51 Viridian Forest | (25,11) (12,29) (1,31) | item balls, text "BCN fo..." = "BCN found <ITEM>!" |

Today these are just `N` (an NPC) to the agent: it only touches them by accident. A ball that has been picked up
disappears from the sprite table (its slot's picture id goes to 0 / the slot is hidden), which is how "collected"
can be read live without storing it.

## 2. Scope (in order)

1. `explorer/items.py`: `BALL_PIC = 61`; `item_balls(emu) -> list[(slot, x, y)]` from the sprite table (static,
   pic 61, visible); `is_item_ball(npc_entry) -> bool`.
2. Memory: `MapMemory` keeps `maps[m]["items"]["x,y"] = {"pic": 61, "text": str, "item": str | None,
   "seen": int, "picked": int}` (`item` parsed from "found <ITEM>!" / "obtained <ITEM>!" text; `picked` counts
   runs that picked it up). This is a world fact; whether a ball is still there in *this* run is read live from
   the sprite table, never from memory.
3. Legend: add kind `item`, glyph `*`. In `legend.py`'s `PRECEDENCE` (today `you, trainer, trainer_beaten, npc,
   warp, ledge, object, wall, ...`) insert `item` **after `trainer_beaten` and before `npc`**, so it also wins over
   `object` (whose KIND_ROWS text currently says "sign, PC, item ball" - drop "item ball" from it). Starter balls
   in the lab show as `*` too. Both renderers and the viewer legend pick it up through `legend.py`. If the Brain
   Tools `tile_kind` override exists when you run, it must accept `item`.
   (The pic-61 table in section 1 comes from the gitignored `runs/maps.json`; the controller re-checks it on the
   ROM. In your tests, build the sprite table with `FakeEmulator`.)
4. Behaviour `pickup` (new module `behaviours/pickup.py`), placed in the selector **after `plan_goal`'s
   goal-critical routes and before `frontier`**: applies when a visible item ball on the current map is reachable
   (navigation BFS to a tile adjacent to it) within `PICKUP_DETOUR = 20` tiles, and the current goal is not one
   that forbids detours (`deliver_parcel`, as the planner already does for training). Steps: route to the
   adjacent tile, face the ball, press A, then let `advance_dialog` close the box. Records the result in memory
   and in `decisions.jsonl` (`behaviour = "pickup"`). In Oak's lab before `first_pokemon` it does nothing - the
   starter planner owns those balls (do not change the starter logic).
5. Metric: `tools/status.py` prints items picked up in the newest run.

## 3. The work

Keep the detour rule simple and named (`PICKUP_DETOUR`). A ball that was tried and gave no item text twice in a
run is skipped for the rest of that run (in-memory only).

## 4. What NOT to do

- Do not change the starter selection (`planner.py` ball choice, `declined_balls`), battle, or menu logic.
- Do not persist "collected" in `maps.json` (it differs per save state).
- No new dependencies; no module over 300 lines; changes inside `src/pokeagent/explorer/` (+ `tools/status.py`).

## 5. Verification

- `uv run pytest -q` green (paste before/after).
- Tests with `FakeEmulator` sprite-table setups: `item_balls` finds static pic-61 slots and ignores moving or
  hidden ones; `pickup` applies within the detour budget and not beyond, not during `deliver_parcel`, not in the
  lab before `first_pokemon`; the "found X!" text parse; the `*` glyph and precedence.
- Do NOT run `uv run pokeagent ...` or the demo. Controller ROM check: a run through Route 2 / Viridian Forest
  picks up at least 2 of the 5 known item balls without human input.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-item-balls-directive`. Never commit to `main`.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.

## 7. Completion criteria

- [ ] `items.py`, memory `items`, legend `*`, `pickup` behaviour, status metric
- [ ] Tests in section 5 pass; `uv run pytest -q` green (paste the tail)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts, where `pickup` sits in the selector order and why, anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-item-balls-directive |
| Base branch | - |
| Base commit | 488b510af0ae92ce3e7be151c64524bbb1b263a9 |
| Head commit | bd521d1604d575649199a6a4fbfde65f07b9f332 |
| Head remote | rfd62794/pokeagent |
| Model | swe-2-flash-max |

**Status log**
- 2026-11-05 19:34 · robert-claude-laptop · none → Queued — Robert asked 2026-11-05; dep World Legend merged (#34)
- 2026-11-05 19:40 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: cited new paths are files it creates; deps merged
- 2026-11-05 19:40 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-item-balls-directive; lane=explicit; model=swe-2-flash-max; persona=steady-builder; agent_id=01M6Q4T3ZVNEZWZ51V3PT4GSNA
- 2026-11-05 19:42 · dispatcher · launched pid=21428; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-item-balls-directive; provisioned: uv sync --frozen
- 2026-11-05 19:56 · devin · In progress → Review — [origin] spent: devin 14 min est. n/a
- 2026-11-05 21:13 · robert-claude-laptop · Review → Done — note: merged via PR #48 (6cfc975) with ROM-verified fixes; Route 2 checkpoint: 59 pickup decisions, POTION + ANTIDOTE collected, no ball pressed twice; follow-ups: cache approach BFS, ball_result overwrite test
<!-- queue:end -->
