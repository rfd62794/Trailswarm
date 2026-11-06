# PokeAgent: buy the Magikarp, party order, and switch-training it into Gyarados

**Read first:** `docs/SEGMENTS.md`, `docs/KNOWLEDGE.md`, `src/pokeagent/goals.py` (goal ladder),
`src/pokeagent/explorer/behaviours/procedures.py` (named menu procedures with per-step screen verification),
`behaviours/battle.py` / `battle_moves.py` (battle menu handling: FIGHT / PKMN / ITEM / RUN).
**Depends on:** the Mt Moon -> Cerulean goals branch (`feat/goals-mt-moon-to-cerulean`) merged. If missing, stop.
**Builder:** a Claude builder on the laptop with the ROM, `kb/` and the live checkpoints copied in (gitignored).
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "We apparently can buy a Magikarp, in the Pokemon Center, before Mount Moon, for 500 Zeni,
which we should make a goal, as well as getting the magikarp to evolve, as it journeys forward. This will involve
teaching it to PokeSwap, and to order their pokemon, as we need Magikarp to be first, but immediately swapped
out."

Facts already in hand (verify each on the ROM before relying on it):
- Mt Moon Pokemon Center is map 68 (0x44) in the shared memory; its recorded talk spots so far are the nurse
  (3,3,UP), the PC (13,4,UP) and an NPC at (1,4,LEFT). The Magikarp salesman is not yet recorded.
- Internal species ids from `kb/rom_tables.json` `name_of_internal`: MAGIKARP and GYARADOS are ids 133 and 22
  (check which is which). Party species list starts at 0xD164, party count 0xD163, lead species 0xD16B.
- Gen 1 experience is split among every Pokemon that **took part** in a battle: Magikarp leads, the agent switches
  it out on the first turn, and Magikarp still earns a share. Magikarp evolves at level 20 (verify from the
  evolution data if the Game Knowledge drain exists; else from the level-up evolution table offset in pokered).

## 2. Scope (in order)

1. **Goal `buy_magikarp`** (party contains MAGIKARP), inserted before `to_mt_moon`, gated on money >= 500 and a
   free party slot; planner routes to the Mt Moon Pokemon Center, finds the salesman (an untalked NPC there),
   answers YES to his offer (extend the YES/NO rules in `explorer/dialog.py` the way the starter offer is handled:
   YES only for the MAGIKARP offer at 500), handles the nickname prompt (NO, as for the starter).
2. **Party order procedure** `reorder_party(target_order)` in `behaviours/procedures.py`: START -> POKeMON ->
   select a member -> SWITCH -> select the other -> back out, with per-step screen verification (read the party
   menu text) like the existing procedures. Used to put Magikarp **first** after buying it and after every
   heal/faint that changes the order.
3. **In-battle switch** `switch_out_lead`: when the battle opens and the lead is the trainee (Magikarp), on turn
   one choose PKMN -> the strongest healthy non-trainee -> the party-menu action the ROM actually shows for
   sending a Pokemon out (read it from the screen text on the ROM and record it in KNOWLEDGE.md; do not assume a
   word) -> confirm; then fight normally. Never switch into a fainted or sub-25%-HP member.
   **Precedence with flee** (`behaviours/battle.py` flee rule): in a **wild** battle the existing flee decision
   wins - if the agent would flee, it flees on turn one with Magikarp still out (no switch; Magikarp gets no XP,
   which is fine). In a **trainer** battle (cannot flee) the switch always happens on turn one. The "enemy level
   >= Magikarp level + 8" case only matters for trainer battles: switch on turn one as usual, never give Magikarp
   a second turn.
4. **Goal `gyarados`** (party contains GYARADOS) is **not in the GOALS ladder** (it must never block the main
   route). Add a separate `SIDE_GOALS` list in `goals.py` with its detector, reported by `check_goals` and
   `tools/status.py` but ignored by the planner's next-goal choice and by segment/checkpoint logic.
   Switch-training applies in every battle while Magikarp is in the party; after evolution it stops and Gyarados
   joins normal team logic. `buy_magikarp` IS in the main ladder (before `to_mt_moon`) - update
   `tests/test_goal_order.py` and every other GOALS consumer accordingly, and add a test that SIDE_GOALS never
   appear in the ladder.
5. **Viewer/decision log**: rule strings `switch_train: MAGIKARP L12 -> out, BULBASAUR in`,
   `reorder_party: [MAGIKARP, BULBASAUR]`; status.py prints Magikarp level and battles shared.

## 3. The work

Keep the menu sequences as named procedures with verification and retries (the existing pattern), and the switch
decision as a small rule in the battle behaviour with named thresholds (register them in the Live Control params
registry if it exists).

## 4. What NOT to do

- Do not change catch, flee, potion thresholds or the starter logic.
- Do not script Mt Moon. Do not commit ROM bytes, states or kb/.
- No new dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green; tests for the YES rule on the salesman text, the reorder procedure steps on a fake
  menu, the turn-one switch decision (trainee lead, healthy candidate, fainted/low-HP exclusions, flee case).
- ROM: from a checkpoint before Mt Moon with >= 500 money, the agent buys Magikarp, reorders it first, and in the
  next three battles switches it out on turn one; report Magikarp's level gain over a 4,000-step run and whether
  it reached 20.

## 6. Rules for this run

- Branch `directive/pokeagent-magikarp-switch-training-directive` in a scratchpad worktree off main (after the
  goals branch merged). Never commit to `main`. Test command `uv run pytest -q`. Never bare `python`.

## 7. Completion criteria

- [ ] `buy_magikarp` goal + salesman YES rule + nickname NO
- [ ] `reorder_party` procedure; Magikarp first after buying and after heals
- [ ] turn-one `switch_out_lead`; `gyarados` background goal; stops after evolution
- [ ] Tests and ROM checks in section 5 (paste tails and numbers)

## 8. Report

Verified ids/menu texts, test tail, ROM numbers (purchase step, battles shared, level reached), anything that did
not fit.
