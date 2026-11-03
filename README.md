# PokeAgent

An agent that plays Pokemon Red on its own through PyBoy. Each step it reads
the game state from RAM, asks a model backend for one button press, presses
it, and logs what it was thinking. Real runs open the PyBoy window so you can
watch it play; the terminal shows its reasoning per step.

## Setup

```
uv sync
```

Put the ROM at `roms/Pokemon Red.gb` (or point `--rom` / `$POKEAGENT_ROM` at
it). The verified ROM is Pokemon Red (UE), SHA-1
`EA9BCAE617FDF159B045185467AE58B2E4A48B9A`. The ROM is never committed.

## Commands

```
uv run pokeagent check-rom                 # verify the ROM's SHA-1 and that it boots
uv run pokeagent state                     # boot headless, print the RAM state summary
uv run pokeagent run --backend stub --steps 20    # dry run, no model needed
uv run pokeagent run --backend claude --steps 50  # real run, PyBoy window opens
```

Useful flags: `--headless` (no window, full speed), `--state PATH` (resume
from a snapshot), `--runs-dir DIR`, `--model haiku|sonnet|...` for the claude
backend.

Every step prints a block like:

```
--- step 12/50  map=0x26 pos=(3,6) party=0 badges=0 battle=no money=3000
thinking: I'm in the bedroom facing the stairs; going down should lead outside.
button:   DOWN       note: stairs are at the top-right of the bedroom
```

Run artifacts land in `runs/<timestamp>/`: `log.jsonl` (one line per step),
`notes.txt` (the agent's own memory, read back every step), `state_NNNN.state`
snapshots every 10 steps and at the end, and `summary.json`.

Exit codes: 0 = step cap reached, 2 = three backend failures in a row,
130 = interrupted with Ctrl+C.

## Cost warning

A `--backend claude` run makes **one `claude -p` call per step**. There is no
unbounded mode: `--steps` is required for a real backend, so `--steps 50`
means 50 model calls against your subscription. Try `--backend stub` first to
see the loop work for free.

## Tests

```
uv run pytest -q
```

All tests run without a ROM or a model (FakeEmulator + StubBackend). Tests
needing a real ROM skip unless `POKEAGENT_ROM` points at one.
