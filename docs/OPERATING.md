# Operating: how a run is launched and watched

Flag details live in docs/CLI.md; this page is the workflow and the window model.

## One run

- Watched: `uv run python tools/explore_demo.py` opens a Tk window (game screen, the decision console,
  the SEES/REMEMBERS panes and the dialog line). Arrow keys, a/s/Enter/Shift steer; `p` pauses the agent,
  `t` cycles turbo. Human presses are learned as demonstrations too.
- Headless: add `--headless` for no window at full speed. Bound the run with `--steps N`,
  `--stop-at-goal GOAL` (a segment run) or `--stop-at-map MAP` (a split sub-segment). `--tag TAG` stores
  an opaque label in the run's meta.json - the convention for a long run is `--tag marathon-<name>`,
  just a label for finding the run later.
- The check harness: `uv run python tools/explore_headless.py` is always headless and prints one JSON
  metrics object. Its drill flags (`--drill-leg`, `--drill-grind`, `--drill-steps`, `--drill-min-hp`,
  `--drill-goto`, `--save-leg-states`) run defined leg and grind drills.
- Go-Explore cells: `explore_demo.py --cell-dump DIR` harvests returnable cells mid-run;
  `--cell-from CID --cell-steps N` mark a run that returned from an archived cell (the driver is
  `tools/go_explore.py`). With the flags off the run is byte-identical to a plain one.

## A swarm

`uv run python tools/swarm.py --agents N --steps M` runs one batch of parallel headless agents, each with
its own copy of `runs/maps.json`, then merges what they learned back into it. `--continuous` keeps N
slots refilled as agents exit; `--plan curriculum` hands each free slot a segment by need (docs/SEGMENTS.md);
`--drills F` gives a share of refills to leg drills; `--upgrade` adopts a running supervisor's agents
without draining it. Stop a continuous swarm with Ctrl+C or by creating `runs/swarm.stop` (`--stop-now`
kills running agents instead of letting them finish).

A stall watchdog frees a slot when an agent is alive but stuck (`tools/swarm_watch.py`): no new
transition for 120 seconds, or 600 presses with no new goal and fewer than 6 new tiles (1,500 presses in
caves). Trainers are exempt from the tile check; XP or level gains count as progress; a run under a
Claude lease is never killed.

## Watching live

- `uv run pokeagent view` - the Dear PyGui desktop viewer: a grid of registered agents, a focus view per
  agent, and the World view (`uv run pokeagent world`). `--fake N` animates fake agents with no ROM.
- `uv run pokeagent world --png out.png` - the same world rendered headless to a PNG.
- `uv run python tools/agentctl.py` - read or steer any live agent: `ls`, `show`, `hold`, `nudge`,
  `macro`.

## After the run

- `uv run pokeagent rewind RUN` - play a finished run back: the frame at any step (`--at STEP`), the
  activity segments (`--segments`), the moments (`--moments`); text or `--json`. Pure playback over the
  run's own `transitions.jsonl` / `decisions.jsonl` / `levels.jsonl` - no ROM, no window. It shows what
  happened, not why; the viewer scrubber (slice 2) is not built yet.
- `uv run pokeagent review {run,swarm,diff,replay,segments}` - run timeline, swarm roll-up, two-run diff,
  determinism replay, segment scorecard.
- `uv run pokeagent states ...` and `uv run pokeagent brain ...` - the save ledger and map-memory
  inspection/surgery (docs/CLI.md).

## The window model

| Entry point | Window |
|---|---|
| `pokeagent view`, `pokeagent world` | Dear PyGui - the project's only viewer |
| `pokeagent world --png` | none (headless export) |
| `tools/explore_demo.py` | a Tk window; none with `--headless` |
| `tools/explore_headless.py`, swarm agents | none |
| `pokeagent run`, `pokeagent mcp` | a PyBoy/SDL2 window unless `--headless` is passed |
| `pokeagent state`, `rewind`, `states`, `review`, `hex`, `brain`, `bytecheck`, `check-rom` | none |
| `tools/agent_window.py` | a legacy per-agent Tk runner (RL segment env): one window per agent |

Tests never open a window or send GUI input (AGENTS.md); ROM-dependent tests skip when `roms/` is absent.
