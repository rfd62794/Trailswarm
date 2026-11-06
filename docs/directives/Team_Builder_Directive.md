# PokeAgent: Team Builder - shop for balls, catch to a plan, and train an optimal team

**Read first:** `src/pokeagent/explorer/behaviours/catch.py` (weaken to <=35% then throw; attempts recorded),
`src/pokeagent/knowledge/` (encounters, trainers, readiness, damage, kb item prices),
`src/pokeagent/explorer/stat_records.py` (DV keep-best), `docs/directives/Opponent_Modeling_Directive.md`,
`docs/directives/Magikarp_Switch_Training_Directive.md`, `docs/directives/Defined_Interactions_Directive.md`.
**Depends on (merged):** Defined Interactions (the `shop`/`buy()` procedure), Opponent Modeling (species book,
counter planner, team-gap report), Magikarp switch-training (party reorder + turn-one switch + party-menu decoding).
If any is missing, stop. **Builder:** a Claude builder on the laptop with the ROM, `kb/` and checkpoint copies.
**Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "How do we also incorporate purchasing poke balls, capturing pokemon, and training an optimal
team?" Pieces exist separately: the agent catches unowned species when it happens to have a ball (catch.py), the
cartridge's encounter tables say what lives where, trainer parties say what the next bosses use, readiness scores
our party against them, the counter planner says who beats whom, switch-training shares XP. Nothing plans a TEAM:
what to buy, what to catch where, which six to carry, and who to level.

## 2. Scope (in order)

1. **Team plan** `explorer/team_plan.py` (pure): for the next 2 bosses (gym leaders / rival from trainer data),
   score candidate teams of up to 6 from {owned} + {catchable on reachable routes (encounter tables) with their
   expected level} using the counter planner / readiness scoring (battle simulator rollouts when it is merged,
   behind its flag). Output: `targets` (species to catch, where, why: "ODDISH Route 24/25: GRASS beats STARYU,
   STARMIE"), `party` (the six to carry, in lead order), `train` (who needs levels and how many). Re-planned at
   every goal change and after each catch. Logged and shown in the snapshot / cockpit.
2. **Shopping** (goal-aware, money-aware): a shopping list from the plan - POKe BALLs for the targets (expected
   throws from the recorded catch odds per species/HP%, + 2 spare), POTIONs by the potion rule - bought with the
   Defined Interactions `buy()` at the nearest Mart when money >= cost + a named reserve (keep >= 500 for the
   Magikarp buy before Mt Moon); never during deliver_parcel; one Mart visit per town per goal stage.
3. **Targeted catching**: the planner routes to the target's encounter area (grass tiles from the encounter
   table's map, learned grass tiles) within a detour budget; in battle, catch only planned targets or new species
   for the Pokedex when balls are plentiful (> named threshold); status-first catching via the effect-aware move
   scoring (sleep/paralyse before throwing); better DVs kept via stat_records (duplicates: keep the better one in
   the party, report the other).
4. **Party management**: carry the planned six in lead order (reuse `reorder_party`); deposit/withdraw via the PC
   only when the plan's party differs from the carried one and a PC is in the current Pokemon Center (PC procedure
   with screen verification - verify texts on the ROM); never deposit the last healthy member.
5. **Training allocation**: generalise Magikarp's switch-training to any `train` member that is far below the
   others (lead it, switch out on turn one); otherwise rotate leads so XP goes where the plan needs it; respect the
   grind budget.
6. **Metrics** (`tools/status.py` + cockpit): team plan, targets caught / attempts / balls used, money spent,
   party levels vs plan, readiness verdict for the next boss.

## 3. The work

Planning pure and tested; behaviours small and named; every threshold a named constant (Live Control params if
merged).

## 4. What NOT to do

- No changes to flee/potion thresholds or the battle simulator itself.
- Never release/discard Pokemon. No new dependencies; modules <= 300 lines; never commit ROM bytes/states/kb.

## 5. Verification

- `uv run pytest -q` green; tests: team plan on synthetic owned/catchable sets vs a synthetic boss (picks the
  counter), shopping list math and reserve, target routing gate, catch-only-targets rule, PC deposit guard, training
  allocation.
- ROM: from a Viridian checkpoint with money, the agent buys balls per the plan, catches at least one planned
  target on Route 2 / Viridian Forest, carries the planned party; report the plan, purchases, catches and party.

## 6. Rules for this run

- Branch `directive/pokeagent-team-builder-directive` in a scratchpad worktree off main. Never commit to `main`.
  Test command `uv run pytest -q`. Never bare `python`. Headless only.

## 7. Completion criteria

- [ ] team plan; shopping; targeted catching; party management (PC); training allocation; metrics
- [ ] tests and ROM checks pasted

## 8. Report

The plan for the next two bosses, ROM purchases/catches/party, test tail, anything that did not fit.
