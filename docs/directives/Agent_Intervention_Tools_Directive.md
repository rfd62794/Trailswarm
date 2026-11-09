# PokeAgent: agent intervention tools - read any live agent's situation at a glance and nudge it safely

**Read first:** `src/pokeagent/control_server.py` (view ControlServer: GET /snapshot, POST /command, token header
`X-PokeAgent-Token`), `src/pokeagent/agent_registry.py` (`runs/agents/<id>.json`: id, pid, port, token, frame_slot),
`src/pokeagent/human_hold.py`, `tools/explore_demo.py` (command handlers, EmuBridge), `src/pokeagent/mcp_server.py`,
`docs/directives/Live_Control_Directive.md` (params/restart/stall feed; do not duplicate it).
**Builder:** a Claude builder on the laptop. **Do not list the tree recursively**; use `git ls-files`.

## 1. Why this exists

Robert (2026-11-06): "I definitely want you to be able to nudge agents in the future, we need to build tools to make
that easier, as well as to make your translation of the agent situation and intervention easier."

What happened on 2026-11-06 ~01:00: the most advanced swarm agent (explore-20120, Mt Moon B2F, goal through_mt_moon)
was stuck in a wild battle using an ANTIDOTE ("It won't have any effect") with WARTORTLE at 11/57 HP and no potion.
Claude had to hand-write a script against /snapshot and /command, read the battle menu from `sees.rows`, and press
B/RIGHT/A. It lost: a remote human press holds the agent only ~3 s (`HumanHold.idle_s`), so between Claude's presses
the agent re-opened the bag; then the stall watchdog killed the agent. Problems: (a) no compact "what is this agent
doing and is it stuck" view across agents; (b) no lease that stops the agent deciding while Claude drives; (c) no
verified macros (run from battle, back out of a menu, use item X on Pokemon Y, walk to tile); (d) no way to tell the
swarm watchdog "Claude is intervening, don't kill it".

## 2. Scope (in order)

1. **Situation digest** `src/pokeagent/intervene/digest.py` (pure, from a snapshot dict): one line per agent and a
   detailed block for one agent: map name (kb name, not id) + x,y, goal stage, mode (overworld/battle/menu/text),
   battle summary (wild/trainer, our lead species L HP/max, enemy species L HP), party HP, money, key bag items
   (potions, balls, rope), last 8 decisions (rule + button), and **stuck signals** with a reason: same rule repeated
   >= N, no new tile in M steps, item loop ("won't have any effect" text repeated), box text repeated, stall-guard
   fired. Rank agents by progress (furthest goal stage first) so "the closest agent" is row 1.
2. **Lease** command `claude_hold` on the view ControlServer: `{cmd:"claude_hold", seconds:int (1..600)}` sets a
   hold the agent's decision loop respects exactly like HumanHold (no own decisions while active), `hold_release`
   ends it; the snapshot exposes `claude_hold_s`. Presses with `source:"claude"` refresh the lease. The swarm stall
   watchdog (`tools/swarm_watch.py` / swarm_continuous) must not count a held agent as stalled and must not kill it
   while the lease is active (log "skipped: claude hold").
3. **Macros** `src/pokeagent/intervene/macros.py`, each a small screen-verified procedure that reads the screen
   (box text / battle menu cursor via existing screentext/RAM readers) before every press, with a press cap and a
   clear result: `back_out` (B until overworld or battle main menu), `battle_run`, `battle_fight(move_name)`,
   `use_item(item_name, on=species|slot)`, `switch(slot)`, `goto(map, x, y)` (uses the existing ctx.goto / planner
   path), `wait(frames)`. Executed agent-side through the EmuBridge under the lease, not by remote press-by-press.
   New command `{cmd:"macro", name:str, args:object}` returning `{ok, result, presses, final_screen}`.
4. **CLI** `tools/agentctl.py` (uv run): `ls` (digest table, ranked), `show <agent|closest|stuck>`, `hold <agent>
   [s]`, `release <agent>`, `press <agent> BUTTON...`, `macro <agent> NAME [k=v...]`, `nudge <agent|closest>`
   (= hold 120 s, back_out, then battle_run if a wild battle is open, else release - prints before/after digest).
   Agent selectors `closest` and `stuck` resolve from the digest.
5. **MCP tools** in `mcp_server.py` (or a sibling module if it would pass 300 lines): `agents_digest`,
   `agent_show`, `agent_hold`, `agent_release`, `agent_macro`, `agent_nudge` - so Claude can call them directly.
6. **Journal**: every intervention appends to `runs/interventions.jsonl` (`{ts, agent, by, action, args, result,
   digest_before, digest_after}`) and the agent's decisions.jsonl marks those steps `driver: "claude"`.

## 3. The work

Pure logic (digest, stuck signals, macro step functions over a fake screen) fully unit-tested. Macros must verify
the screen before each press and stop (not guess) when the screen is not what they expect. Every module <= 300
lines; `tools/explore_demo.py` is already over 300 - add the new handlers in a new module it imports, do not grow it.

## 4. What NOT to do

- Do not change any behaviour/policy module or tuning constant; no params registry (Live Control owns that).
- Never touch `C:\Github\PokeAgent` runs/ of the live swarm in tests; use tmp dirs and a scratch agent on ports 9600+.
- No GUI windows (headless only). No new dependencies. Never commit ROM bytes, states or kb.

## 5. Verification

- `uv run pytest -q` green (plain, no -n). Tests: digest from recorded snapshot fixtures (battle, overworld, item
  loop -> stuck reason), ranking, lease blocks decisions and expires, watchdog skips a held agent, each macro on a
  fake screen sequence including the "unexpected screen -> stop" path, CLI selector resolution.
- ROM: one scratch headless agent (`tools/explore_demo.py --headless`, port 9600+, its own maps copy) from
  `runs/checkpoints/to_mt_moon.state`; run `agentctl ls`, `show`, then `nudge` during a wild battle: it must run
  from the battle under the lease while the agent makes no own decisions; paste the before/after digests.

## 6. Rules for this run

Branch `feat/agent-intervention-tools` in a scratchpad worktree off main. Never commit to main. Headless only. The
laptop is shared overnight: one ROM run at a time, plain pytest.

## 7. Completion criteria

- [ ] digest + stuck signals; [ ] claude_hold lease + watchdog skip; [ ] macros; [ ] agentctl CLI; [ ] MCP tools;
  [ ] interventions journal; [ ] tests and ROM check pasted

## 8. Report

The `agentctl ls` output against the scratch agent, the nudge before/after, test tail, and anything that did not fit.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | claude |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-09 00:48 · agentflow-tick · none → Queued — suggested by heartbeat: Code appears built; verify merge state, run the ROM nudge check, resolve journal name, then close. Do not rebuild.
<!-- queue:end -->
