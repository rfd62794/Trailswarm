# PokeAgent: game knowledge - every move's meaning, species data, wild encounters and trainer parties, from the ROM

**Read first:** `docs/KNOWLEDGE.md`, `tools/rom_tables.py` (the existing drain: moves, type chart, names, dex
order, via pret/pokered symbol offsets), `docs/superpowers/specs/2026-11-05-atlas-overlay-note.md`.
**Builder:** a Claude builder on the laptop with the ROM present (this needs the cartridge to verify every
offset; Devin's sandbox has no ROM). **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-05): "Is there a way to give it context to each attack in existence? There's enough data on this
game that we could give it a lot of base knowledge."

Today `kb/rom_tables.json` (ROM-derived, gitignored) holds 165 moves with `name, effect, power, type, accuracy,
pp`, the 82-entry type chart and species names / dex order. Move choice uses only power x type x STAB x
accuracy, so every **status or special move scores 0 or is misjudged**: Growl, Sleep Powder, Thunder Wave,
Leech Seed, Seismic Toss (fixed damage = level), Hyper Beam (recharge), Solarbeam/Dig/Fly (two turns), Double
Kick (2 hits), Absorb (drain) all look like "power x type".

The `effect` byte is already drained. Grouping the ROM's own moves by it (2026-11-05) gives its meaning directly:

| effect | moves (from the ROM) | meaning |
|---|---|---|
| 00 | POUND, SCRATCH, TACKLE, CUT | plain damage |
| 02 / 21 | POISON STING / SMOG, SLUDGE | damage + poison chance (low / high) |
| 03 | ABSORB, MEGA DRAIN, LEECH LIFE | damage, heal half |
| 04 / 22 | EMBER, FLAMETHROWER / FIRE BLAST | damage + burn chance (low / high) |
| 05 | ICE BEAM, BLIZZARD | damage + freeze chance |
| 06 / 24 | THUNDERSHOCK, THUNDERBOLT / BODY SLAM, LICK | damage + paralyse chance (low / high) |
| 07 | SELFDESTRUCT, EXPLOSION | user faints |
| 08 | DREAM EATER | only vs sleeping target, heal |
| 09 / 53 / 52 / 39 | MIRROR MOVE / METRONOME / MIMIC / TRANSFORM | copy / random |
| 0A 0B 0D 0F | MEDITATE / HARDEN, WITHDRAW / GROWTH / DOUBLE TEAM | own stat +1 (atk / def / spc / evasion) |
| 32 33 34 35 | SWORDS DANCE / BARRIER / AGILITY / AMNESIA | own stat +2 (atk / def / spd / spc) |
| 12 13 14 16 | GROWL / TAIL WHIP, LEER / STRING SHOT / SAND-ATTACK, FLASH | foe stat -1 (atk / def / spd / acc) |
| 3B | SCREECH | foe def -2 |
| 44 45 46 47 | AURORA BEAM / ACID / BUBBLEBEAM / PSYCHIC | damage + foe stat -1 chance (atk / def / spd / spc) |
| 10 / 11 | PAY DAY / SWIFT | money / never misses |
| 18 19 1A | CONVERSION / HAZE / BIDE | misc |
| 1B | THRASH, PETAL DANCE | 2-3 turns then confused |
| 1C | WHIRLWIND, ROAR, TELEPORT | ends wild battle |
| 1D / 2C / 4D | FURY ATTACK, PIN MISSILE / DOUBLE KICK / TWINEEDLE | 2-5 hits / 2 hits / 2 hits + poison |
| 1F / 25 | BITE, HYPER FANG / STOMP, HEADBUTT | damage + flinch chance (low / high) |
| 20 | SING, SLEEP POWDER, HYPNOSIS, SPORE | sleep |
| 26 | GUILLOTINE, HORN DRILL, FISSURE | one-hit KO |
| 27 / 2B | SOLARBEAM, DIG, SKULL BASH / FLY | charge turn first |
| 28 / 29 | SUPER FANG / SEISMIC TOSS, NIGHT SHADE, SONICBOOM, DRAGON RAGE | half HP / fixed damage |
| 2A | WRAP, BIND, FIRE SPIN, CLAMP | trap 2-5 turns |
| 2D / 30 | JUMP KICK / TAKE DOWN, DOUBLE-EDGE | crash on miss / recoil |
| 2E 2F 40 41 4F | MIST / FOCUS ENERGY / LIGHT SCREEN / REFLECT / SUBSTITUTE | protection / setup |
| 31 / 4C | SUPERSONIC, CONFUSE RAY / CONFUSION, PSYBEAM | confuse / damage + confuse chance |
| 38 | RECOVER, SOFTBOILED, REST | heal |
| 42 / 43 | POISONPOWDER, TOXIC / STUN SPORE, THUNDER WAVE | poison / paralyse (status only) |
| 50 / 51 / 54 / 55 / 56 | HYPER BEAM / RAGE / LEECH SEED / SPLASH / DISABLE | recharge / rage / seed / nothing / disable |

## 2. Scope (in order)

1. `src/pokeagent/knowledge/moves.py`: the effect table above as data (`EFFECTS: dict[int, Effect]` with
   `kind` (damage / status / stat / setup / special), `target` (self / foe), `stat`, `stages`, `chance`
   (low = ~10%, high = ~30% as Gen 1 does), `hits`, `charge`, `recharge`, `fixed`, `heal`, `ohko`, `ends_wild`),
   and `describe(move) -> str` (one line of context per move, e.g. "THUNDER WAVE: ELECTRIC status - paralyses the
   foe; fails on GROUND"). A test asserts every effect id present in `kb/rom_tables.json` is in `EFFECTS` (skips
   without the KB).
2. Extend the ROM drain (`tools/rom_tables.py`, writing `kb/rom_tables.json` - still gitignored) with, each
   verified on the cartridge by sanity checks written into the tool:
   - **Species base data** (base stats, types, catch rate, base exp, growth rate, level-1 moves): check
     Charmander HP 39 / FIRE, Pidgey NORMAL/FLYING, Geodude ROCK/GROUND, Onix ROCK/GROUND.
   - **Learnsets and evolutions** (level-up moves, evolve level): check Charmander learns EMBER at 9 and evolves
     at 16, Bulbasaur VINE WHIP at 13.
   - **Wild encounter tables per map** (grass rate, 10 slots species+level): check Route 1 has PIDGEY and
     RATTATA at levels 2-5.
   - **Trainer parties**: check Brock = GEODUDE L12, ONIX L14.
   - **Items** (name, price): check POTION 300.
   Offsets come from pret/pokered's symbol file; fetch the published symbols the same way the existing tool's
   offsets were derived and record each offset + its check in `docs/KNOWLEDGE.md`. Any check that fails is a stop:
   do not write a table you could not verify.
3. Battle use (small, on top of Battle_Types once merged; if not merged, only the scoring hooks):
   `move_scores` values non-damage moves by effect instead of 0 - e.g. sleep/paralyse high when the goal is to
   **catch** (catch logic already weakens first), foe stat-down low in fights that end in 2-3 turns, fixed-damage
   = user level, two-turn/recharge moves discounted, multi-hit expected hits, drain counts heal when HP is low.
   Keep it a table of multipliers (named constants), not new rules; record which effect drove each choice in the
   rule string.
4. Planning use: `knowledge/encounters.py` answers "where can I catch X / train vs Y" from the encounter tables;
   `knowledge/trainers.py` answers "what does Brock use" - the planner's pre-gym check reads it (type matchup of
   our team vs the gym's party; report only, no new behaviour yet).
5. Viewer/brain: `pokeagent brain lessons moves` lists every move with `describe()` and what the agent has
   observed using it.

## 3. The work

Data first (items 1-2), each table behind a small query module; behaviour changes (item 3) only through named
multipliers so the RL selector and the review tool can tune them later.

## 4. What NOT to do

- Never commit ROM bytes or `kb/` (gitignored); the tool regenerates it from the cartridge.
- Do not change HP thresholds, flee/potion rules, or catch-decision logic beyond the scoring table.
- No new runtime dependencies; no module over 300 lines.

## 5. Verification

- `uv run pytest -q` green; every sanity check in item 2 passes on the ROM (paste the tool's output).
- A 3,000-step ROM run from `baselines/bedroom.state`: no status move is chosen in a fight it could end by
  damage in <= 2 turns; at least one catch attempt uses a status move when one is known.

## 6. Rules for this run

- Work only on branch `directive/pokeagent-game-knowledge-directive` in a scratchpad worktree with the ROM copied
  in (gitignored). Never commit to `main`. Test command `uv run pytest -q`. Never bare `python`.

## 7. Completion criteria

- [ ] `knowledge/moves.py` effect table + `describe`; every ROM effect id covered
- [ ] Drain: species, learnsets/evolutions, encounters, trainers, items - all checks pass, offsets in KNOWLEDGE.md
- [ ] Effect-aware move scoring; encounters/trainers queries; brain lessons moves
- [ ] Tests and ROM checks in section 5 pass (paste tails)

## 8. Report

Tool output with every check, test tail, line counts, and the ROM run's move-choice summary.
