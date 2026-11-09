# PokeAgent: defined interactions - typed, memorised conversations; heal only when needed; fastest safe text pace

**Read first:** `src/pokeagent/explorer/memory.py` (`interactions`, `npcs`, `beats`), `explorer/dialog.py`,
`src/pokeagent/explorer/behaviours/heal.py`, `.../behaviours/advance_dialog.py`, `.../behaviours/procedures.py`,
`.../behaviours/replay_beat.py`,
`docs/KNOWLEDGE.md`. **Depends on:** the Mt Moon -> Cerulean goals branch merged (it adds `ctx.center_intent`).
**Builder:** a Claude builder on the laptop with the ROM, `kb/` and checkpoint copies (gitignored).
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "How do we teach it to be efficient when talking to mom, one time only to heal? And it also
needs to find the optimal rate to tap A to get through so many menus and interactions. We also need to work toward
Defined Interactions if possible. Observed and Memorized Chats or conversations, and I wonder if there are multiple
definable interaction types?"

Today every talk spot is an `interactions["x,y,FACING"]` entry with the first text, press counts, menus and
choices; NPCs are tracked separately; "beats" replay the shortest button sequence for a recognised text. Nothing
says *what kind* of interaction it was or whether repeating it is ever worth anything, so the agent re-talks to
NPCs, walks home to Mom on a timer-like rule (`heal.py` only guards a failed heal for 150 steps), and pastes text
at a fixed `--box-pace 6` frames regardless of how fast each box can actually go.

## 2. Scope (in order)

1. **Interaction types**, classified from the observed effect of the whole interaction (not from text guesses),
   stored as `interactions[key]["type"]` with a confidence count:
   | type | detected by |
   |---|---|
   | `healer` | party HP all restored at the end (Mom, Pokemon Center nurse) |
   | `shop` | the BUY/SELL menu appeared (Poke Mart clerk) |
   | `pc` | the PC menu text ("turned on the PC") |
   | `giver` | the bag or party gained something ("received", "got", "obtained", "found") - normally once (story flag) |
   | `vendor` | a YES/NO offer with a price and money decreased on YES (the Magikarp salesman) |
   | `trainer` | a battle started right after the text (battle flag 2) |
   | `story` | a forced walk, map change or event flag flipped by the text (Oak, rival, guards) |
   | `blocker` | the text repeats and the player is pushed back / cannot pass (guard, "can't go that way") |
   | `sign` | a solid non-NPC tile that shows text (signs, bookshelves) |
   | `info` | plain text with no effect - talking again teaches nothing |
2. **Repeat policy** from the type (one table of named rules, logged in the decision rule string):
   `info` and `sign` - never re-talk once memorised (store the full text); `giver` - once per run, then never
   (skip if the bag already has the item); `healer` - only when the party needs healing (any mon below the existing
   heal threshold or fainted) **and** it is the nearest known healer by route length; `shop`/`vendor` - only when a
   goal or the item budget wants something; `trainer` - beaten once, then avoid re-triggering; `blocker` - record
   the condition and do not retry until a goal changes. Mom becomes just the nearest `healer` early in the game -
   one visit when needed, not a routine.
3. **Memorised conversations**: per interaction keep the full ordered text pages (deduplicated), the menus and
   choices seen, the button sequence that completed it fastest, and its outcome. Expose them in the decision log
   and (if Brain Tools is merged) via `brain_find --type <type>`.
4. **Fastest safe text pace**: first, a one-time procedure `set_text_speed_fast` (START -> OPTION -> TEXT SPEED
   FAST -> back; verify the option byte on the ROM - ram_map.json has only wOptions* cursor labels, so take the
   text-speed byte (wOptions) address from pret pokered.sym (symbols branch) and add it to ram_map overrides;
   confirm it changes). Then replace the fixed `box_pace` with an adaptive rule: press A as soon as
   the box is waiting for input (the down-arrow prompt tile in the text box, or the text fully printed - verify the
   prompt tile id on the ROM) instead of after a fixed frame count; keep a per-screen-kind learned minimum frames
   (box / menu / yes-no / battle text) that never dropped an input, shrinking it while presses keep working and
   growing it on a dropped press (detected when the same page is still shown after the press). Named constants for
   the bounds.
5. **Metrics** in `tools/status.py`: presses per interaction type, re-talks avoided, heal visits, mean frames per
   text page before/after.

## 3. The work

Classification is a small pure function over an interaction's recorded effects; the repeat policy is a table;
pacing is a small learner with explicit bounds. Keep the existing beats/procedures - they are reused, not replaced.

## 4. What NOT to do

- Do not change battle, catch, flee, potion logic, or the starter / Magikarp YES rules.
- Do not script specific NPCs by position - everything comes from observed effects.
- No new dependencies; no module over 300 lines; never commit ROM bytes or states.

## 5. Verification

- `uv run pytest -q` green; tests for each type's classifier on recorded fixtures, the repeat policy table, the
  heal decision (needs-healing + nearest), and the pace learner (shrinks, grows on a dropped press, stays in bounds).
- ROM: text speed set and verified via the option byte; a 3,000-step run from `baselines/bedroom.state` shows
  fewer presses per text page than before (report the numbers), Mom visited only when the party needed healing,
  and no `info` NPC talked to twice.

## 6. Rules for this run

- Branch `directive/pokeagent-defined-interactions-directive` in a scratchpad worktree off main. Never commit to
  `main`. Test command `uv run pytest -q`. Never bare `python`.

## 7. Completion criteria

- [ ] interaction types + repeat policy + memorised conversations
- [ ] text speed FAST procedure + adaptive A pacing
- [ ] metrics; tests and ROM checks pasted

## 8. Report

Verified addresses/tiles, test tail, before/after numbers, and the type counts the ROM run produced.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | claude |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-09 00:45 · agentflow-tick · none → Queued — suggested by heartbeat: Close-out audit, not a rebuild: code appears present; needs tests and ROM evidence from section 5.
<!-- queue:end -->
