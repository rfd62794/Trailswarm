# CLI and tools

Everything runs through `uv run` from the repo root. `pokeagent` is one CLI with subcommands; the three
tools under `tools/` are the watched/headless explorer and the swarm. See docs/OPERATING.md for how a run
is launched and watched, and which commands open a window.

## `pokeagent` subcommands

| Command | What it does |
|---|---|
| `run` | Run the agent loop: `--backend {stub,claude}` (`stub` = no model; `claude` = one `claude -p` call per step), `--steps N` (required for a real backend), `--headless`. |
| `check-rom` | Verify the ROM's SHA-1 and that it boots. |
| `state` | Boot headless and print the RAM state summary. |
| `mcp` | Serve the emulator as MCP tools over stdio (configured in `.mcp.json`). |
| `view` | Dear PyGui viewer for registered agents. `--fake N` shows animated fake agents with no ROM. |
| `world` | The same viewer in World mode; `--png OUT` renders the map to a PNG headless instead. |
| `states` | The save-state ledger (below). |
| `rewind` | Play a finished run back (below). |
| `hex` | WRAM mapping and screen-text tools (boots headless). |
| `brain` | Inspect the map memory and perform journaled surgery (JSON out). |
| `review` | Operator run/swarm/replay/diff review tools (text, `--json`). |
| `bytecheck` | Detect ROM bytes in files - see docs/BYTECHECK.md. |

### view / world

```
pokeagent view [--root DIR] [--fake N] [--fps N] [--mode {tiles,world}]
               [--source DIR] [--game NAME] [--preset NAME] [--genre NAME]
pokeagent world [--root DIR] [--fake N] [--png OUT] [--rom ROM] [--base PNG]
                [--layers LAYERS] [--model JSON] [--no-tint] [--scale S]
                [--interiors {inset,inplace,inplace-full,auto,stretch}] [--mode {tiles,world}]
```

`--mode` picks the start view (world is the default; Tab swaps). `--layers` names learning layers for the
PNG export (heat, walls, warps, disagree, ...). `--interiors` controls how indoor maps are drawn in.

### states - the save-state ledger

```
pokeagent states {list,check,promote,restamp,retire,library}
pokeagent states list [--map M] [--bad] [--dir D]
pokeagent states library {build,list,validate}
```

`list` prints one row per state (name, map, position, respawn, party, HP%, money, source run, status).
`check` fails on stale/missing sidecars and party-rule violations. `promote`/`retire` move states between
lineage tiers and the retired dir. `library build` scans the state dirs and writes
`runs/states/library.json`; `library list` prints the entries; `library validate` re-runs the party rules
and prints RETIRABLE lines. See docs/TRAINING.md for what the library feeds.

### rewind - finished-run playback

```
pokeagent rewind RUN [--runs DIR] [--at STEP] [--segments] [--moments] [--json]
```

Plays a finished run back from its own logs: per-step frames (`--at`), activity segments (`--segments`),
and moments (`--moments`). Text by default, `--json` for machine use; exit 2 on an unknown run. Needs no
ROM and opens no window. It shows what happened, not why.

### hex / brain / review / bytecheck

```
pokeagent hex {dump,diff,find,screen}
pokeagent brain {maps,map,tile,find,diff,lessons,edit,edits,undo,apply,q}
pokeagent review {run,swarm,diff,replay,segments}
pokeagent bytecheck {build,scan,staged}
```

`hex` dumps/diffs/searches WRAM and decodes the visible tile map to text. `brain` reports and edits the
shared map memory (`apply --backup` is the fold into maps.json). `review` gives run timelines, swarm
roll-ups, a two-run diff, a determinism replay and the segment scorecard. `bytecheck` builds the local
ROM-fingerprint index and scans files or staged changes - docs/BYTECHECK.md.

## The three tools

### `tools/explore_demo.py` - one explorer run

```
uv run python tools/explore_demo.py [--headless] [--tag TAG] [--stop-at-goal GOAL]
    [--stop-at-map MAP] [--maps PATH] [--runs-dir DIR] [--control-port PORT]
    [--starter {any,random,bulbasaur,charmander,squirtle}] [--train-level N]
    [--explore-rate F] [--cell-dump DIR] [--cell-from CID] [--cell-steps N]
```

One learning-explorer run. Without `--headless` it opens a Tk window (game screen + console); with it,
no window and full speed. `--tag` stores an opaque label in the run's meta.json. `--stop-at-goal` /
`--stop-at-map` bound a segment run. `--cell-*` are the Go-Explore harvest/return flags. It also accepts
the shared run flags of `explore_headless.py` (`--bandit`, `--novelty`, `--par-follow`, the drill flags).

### `tools/explore_headless.py` - the headless check harness

```
uv run python tools/explore_headless.py [--state PATH] [--steps N] [--seed N]
    [--stop-at-goal GOAL] [--starter NAME] [--bandit] [--bandit-path PATH]
    [--par-follow] [--role NAME] [--novelty] [--save-leg-states]
    [--drill-leg MAP:X,Y->X,Y] [--drill-grind MAP] [--drill-steps N]
    [--drill-min-hp N] [--drill-goto]
```

Always headless: runs the explorer engine for N steps and prints one JSON object of metrics (text pace,
interaction types, goals reached). The `--drill-*` flags run defined leg/grind drills.

### `tools/swarm.py` - parallel headless agents

```
uv run python tools/swarm.py [--agents N] [--steps N] [--continuous]
    [--plan curriculum] [--suite NAME] [--segment GOAL] [--drills F]
    [--save-leg-states] [--roles] [--bandit] [--bandit-share F]
    [--par-follow] [--par-share F] [--novelty] [--upgrade] [--duration H]
    [--stop-now] [--port-base N] [--no-share-frames]
```

N headless explorers sharing `runs/maps.json`. `--continuous` refills slots as agents exit;
`--plan curriculum` picks each slot's segment by need; `--upgrade` adopts a running supervisor's agents.
Stop a continuous swarm with Ctrl+C or by creating `runs/swarm.stop`.
