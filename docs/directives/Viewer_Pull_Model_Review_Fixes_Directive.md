# PokeAgent: Viewer Pull Model review fixes (PR #167) - a magic for the frame-slot layout, telemetry tests, web frames on demand, logged fallbacks, a real grade column

## Why this exists

PR #167 (branch `directive/pokeagent-viewer-pull-model-directive`, head d4eb21e, built from
`docs/directives/Viewer_Pull_Model_Directive.md`) came back CHANGES-NEEDED with findings quoted below. The cadence
model, visible-set frame reads, swarm page and headless tests passed (143 viewer tests). It merges cleanly onto
main.

**Branch rule for this run:** your run branch is created FROM the PR branch (the coordinator approves this row with
that base branch), so PR #167's files are already in your worktree. Do NOT run `git merge`, `git rebase` or `git stash`
(the sandbox refuses them). Commit and push to your own run branch only; the coordinator fast-forwards it onto PR
#167's branch. Never push to main; never open a PR. Tests stay headless (`dpg.create_context()` only; never a viewport,
never input).

## The findings and what to do

1. **"telemetry.py slot_layout: the v1-vs-v2 'size double-guard' does not work on Windows. A v1-size slot (16 +
   160*144*3 = 69136 bytes) reports len 69136 on the creating side but 69632 on the ATTACHING side (shared memory is
   page-rounded), which already exceeds the v2 minimum (69152). So v1 detection rests only on bytes 16..19 !=
   02 00 00 00. A v1 publisher whose first pixel bytes spell 02 00 00 00 would be read as v2: frames read at offset 32
   and the heartbeat's 8 bytes written at offset 24 into the publisher's frame data."** -> Write a magic u32 at the
   reserved offset 20 (`SLOT_MAGIC = 0x504B4147`) in the v2 publisher header; `slot_layout` returns 2 only when
   layout == 2 AND magic matches; keep the size check as a secondary guard; everything else is v1. Document the v2
   header layout (offsets 0..32) in the module docstring.
2. **No telemetry tests:** add to `tests/test_frame_slots.py` (or a new `tests/test_frame_slot_layout.py`): a v2
   publisher round trip (header fields, frame at offset 32); a manually built v1 slot (16-byte header, frame at 16)
   read correctly even when its first pixel bytes are 02 00 00 00; the heartbeat is written only on v2 slots and
   leaves `seq`, width/height/pid, layout, magic and every frame byte untouched (compare bytes before/after); a stale
   vs fresh heartbeat as `FramePublisher` will read it (Agent_Footprint consumes it).
3. Compatibility note (no code): an OLD viewer reading a NEW v2 publisher reads frames 16 bytes late. Put one line in
   KNOWLEDGE.md: upgrade viewers before agents, or restart the World view after this merge.
4. **"The --web page regresses: viewer/web.py reads model.frame(aid) for every agent (/data 'frame' flag and
   /frame.png), but frames are now fetched only for the Dear PyGui window's visible set, so web cards for off-screen
   agents get 'no frame'/404."** -> Let the web server declare its own wants (a `set_wants` contribution merged with the
   window's, at `CARD_FRAME_HZ` for agents a web client requested within the last `WEB_WANT_S = 5` s), or fetch a frame
   on demand inside `/frame.png` (one shared-memory read, heartbeat written). Test: a web request for an off-screen
   agent returns a frame after the next poll and the want expires.
5. **Silent excepts in viewer/swarm_rows.py:** the `import seg_store` fallback (`_ss = None`), `_segments_doc` and
   `_layout_keys` all `except Exception` and return blanks with no log. -> Log once each via the module logger (a torn
   read during the supervisor's save is a legitimate reason; say so in the comment); narrow to (OSError, ValueError,
   KeyError) where that is what the callee raises. Replace the `sys.path` mutation that finds `tools/` with the same
   mechanism `review/segments.py` uses, or better, import the store through a small `pokeagent.segments_io` shim if
   one exists; if none exists, keep the hack but centralise it in one helper used by both modules and leave a comment.
6. **Grade column:** "_grade reads stats[key]['grade'], but #161's scorecard computes grades on the fly
   (segment_grades.grade_all) and never writes a 'grade' into segments.json, so the column stays n/a." -> Call
   `segment_grades.grade_all` (merged in PR #161) in `swarm_rows` at the 1 Hz cadence (cache its result for the
   poll), and show the grade letter/word it returns; test with a fixture segments.json.
7. Nits: SwarmPage docstring says SWARM_PANE (tag is SWARM_PAGE); add the window-level test "World view, Stadium
   hidden, nothing focused => visible_frame_set() == {}".

## What NOT to do

- Do not change the cadence constants, the visible-set logic, the swarm page layout, or the card/Stadium/health code
  beyond the items above. No change to `snapshot.py`, adapters, `control_server.py`.
- Every file under `src/pokeagent/viewer/`, `src/pokeagent/world/` and `src/pokeagent/telemetry.py` under 300 lines.
- No new dependency; no scratch files outside `.devin-scratch/`; never read outside the worktree.

## Verification (exact commands; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_viewer*.py tests/test_world_view.py tests/test_frame_slots.py tests/test_frame_slot_layout.py tests/test_viewer_web*.py
```
Expected: all pass (adjust to the files that exist; the ROM-gated skip in test_world_view.py:303 remains).

```
uv run pytest -q
```
Expected tail: ~1990+ passed, 40 skipped (ROM-gated), 0 failed.

```
wc -l src/pokeagent/telemetry.py src/pokeagent/viewer/*.py src/pokeagent/viewer/ui/*.py src/pokeagent/world/*.py
```
Expected: each under 300.

## Rules for this run

- NON-INTERACTIVE: a tool call that needs confirmation ends the run. Never install, download, fetch, or read outside
  the working directory. Never create a viewport.
- Branch only (see the branch rule); commit as you go; never commit to or push main; never merge.
- If blocked, stop and write why in the Status row.

## Completion criteria

- Items 1, 2, 4, 5, 6 applied with tests; item 3 noted in KNOWLEDGE.md; item 7 done; suites green; sizes under 300.
- Status row set to Review with head sha, diff stat, wc -l line, test tails.

## Report

Head sha, diff stat, wc -l line, test tails, the magic value and header layout you documented.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 22:01 · robert-claude-laptop · none → Queued — Review fixes for PR #167 (Sonnet: frame-slot layout guard, telemetry tests, web frames, logged fallbacks, real grade column); approve with base_branch = the PR branch
<!-- queue:end -->
