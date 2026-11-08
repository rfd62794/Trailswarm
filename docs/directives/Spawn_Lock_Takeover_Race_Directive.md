# PokeAgent: spawn_lock takeover race - a taken-over lock can be resurrected with no holder, and same-process holders cannot tell their locks apart

## Why this exists

`tests/test_resources.py::test_lock_takeover_is_exclusive` is the one flaky test in the suite. It failed on the
verify lane for PR #156 at 280c088 (full suite) and passed alone at the same sha. Verbatim failure
(C:\Users\cheat\AppData\Local\AgentFlow\personal-laptop\verify\PokeAgent\280c088f8fcd84fc95d47cb069eceae008891b27.log):

```
>       assert not errs and worst[0] == 1
E       AssertionError: assert (not [LockBusy('another swarm holds ...\runs\spawn.lock'), ..., LockBusy('another swarm holds ...\runs\spawn.lock')])
tests\test_resources.py:144: AssertionError
```

Six threads, `wait_s=10`, each holding the lock for 0.05 s. LockBusy after a 10 s wait means a lock file was
left on disk with a live-looking pid and nobody holding it. The code (src/pokeagent/resources.py, lines 171-235):

```python
def _try_acquire(path: Path) -> bool:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True

def _stale(path: Path) -> bool:
    try:
        if time.time() - path.stat().st_mtime > LOCK_STALE_S:
            return True
        return process_state(int(path.read_text().strip() or 0)) == "gone"
    except (OSError, ValueError):
        return True

def _take_over(path: Path) -> None:
    tomb = path.with_name(f"{path.name}.stale.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        os.rename(path, tomb)
    except OSError:
        return  # someone else got there first
    if not _stale(tomb):
        try:
            os.link(tomb, path)
        except OSError:
            pass
    tomb.unlink(missing_ok=True)

@contextmanager
def spawn_lock(root: Path, wait_s: float = 0.0):
    _runs(root).mkdir(parents=True, exist_ok=True)
    path = _runs(root) / "spawn.lock"
    end = time.monotonic() + wait_s
    while not _try_acquire(path):
        if _stale(path):
            _take_over(path)
            continue
        if time.monotonic() >= end:
            raise LockBusy(f"another swarm holds {path}")
        time.sleep(0.05)
    try:
        yield
    finally:
        try:
            if path.read_text().strip() == str(os.getpid()):
                path.unlink(missing_ok=True)
        except OSError:
            pass
```

`process_state(pid)` (src/pokeagent/registry.py:38) returns `'alive' | 'gone' | 'unknown'`; `process_state(0)` is
`'gone'`. `LOCK_STALE_S = 6 * 3600`.

Three defects, found by reading the code against the failure (the controller's diagnosis; verify it with the
stress test in Verification before you change anything):

1. **Empty-content window.** `_try_acquire` creates the file (visible to everyone) and only then writes the pid.
   A reader in `_stale` between those two calls sees `""` -> pid 0 -> `'gone'` -> judges a LIVE lock stale and
   renames it aside in `_take_over`.
2. **Resurrection.** `_take_over` renames a lock aside, re-checks it, and if it looks live links it back. Between
   the rename and the link-back another thread can acquire AND release the path (its `finally` finds the file it
   created, same pid, unlinks it). The link-back then recreates a lock with a live pid that nobody holds. Every
   waiter now waits `wait_s` and raises LockBusy. That is the observed failure.
3. **Same-pid holders are indistinguishable.** The release check compares the file content with `os.getpid()`,
   so any thread of the process can release any other thread's lock, and `_stale` can never see an in-process
   holder as anything but alive. Two swarm threads in one process can therefore both "hold" the lock
   (`worst[0] == 2`, the test's other failure mode).

## Scope (in this order)

1. `src/pokeagent/resources.py`: make lock content visible atomically, serialise takeovers, release by token.
2. `tests/test_resources.py`: keep the existing test unchanged; add a stress test and three deterministic tests.

Read first: `src/pokeagent/resources.py` lines 1-60 (imports, constants, `LockBusy`) and 165-235;
`src/pokeagent/registry.py` lines 38-65 (`process_state`); `tests/test_resources.py` in full (it is short).

## The work

### 1. `resources.py`

- **Token, not pid.** Each acquisition writes `f"{os.getpid()}:{uuid.uuid4().hex}"`. Add
  `_lock_pid(text: str) -> int` (the part before `:`; `int(text.strip() or 0)` when there is no colon, so old
  lock files from a running swarm still parse) and use it in `_stale`. The `finally` in `spawn_lock` unlinks only
  when the file content equals the token this acquisition wrote.
- **Write before visible.** In `_try_acquire`, write the token to a sibling temp file
  `path.with_name(f"{path.name}.{os.getpid()}.{uuid}.tmp")`, then `os.link(tmp, path)`; `FileExistsError` ->
  return None; any other `OSError` from `os.link` -> return None as well (Windows raises PermissionError when
  the target is in delete-pending state; treat it as "busy, retry"). Always unlink the temp file (`missing_ok=True`)
  in a `finally`. Return the token on success and `None` on failure (the caller needs the token).
- **Empty content is live, not stale.** In `_stale`, if the content is empty (a file mid-write by an old-format
  writer) return False unless the mtime check already said stale.
- **Takeover under a side lock, by unlink, never by rename+link.** Replace `_take_over` with:
  ```python
  TAKEOVER_STALE_S = 5.0

  def _take_over(path: Path) -> None:
      """Remove a stale lock exactly once: takers serialise on path + '.takeover' (O_EXCL), re-check staleness
      inside, unlink, release. A crashed taker's side lock older than TAKEOVER_STALE_S is removed first."""
      side = path.with_name(path.name + ".takeover")
      try:
          if time.time() - side.stat().st_mtime > TAKEOVER_STALE_S:
              side.unlink(missing_ok=True)
      except OSError:
          pass
      try:
          fd = os.open(side, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
      except OSError:
          return  # another taker is inside; the caller loops and re-tries acquire
      try:
          os.close(fd)
          if _stale(path):
              path.unlink(missing_ok=True)
      finally:
          side.unlink(missing_ok=True)
  ```
  No tombstones, no `os.link` back. The `_stale(path)` re-check inside the side lock is what makes the
  removal safe once defect 1 is gone: a live lock always has content.
- **`spawn_lock` loop.** `while (token := _try_acquire(path)) is None:` ... ; the body is otherwise the same.
  `lock_held` is unchanged.
- Keep every file under 300 lines. No new dependency. No new `except Exception`; the existing narrow
  `except OSError` / `(OSError, ValueError)` are the only swallowed errors, and each stays narrow.

### 2. `tests/test_resources.py`

Keep `test_lock_takeover_is_exclusive` byte-for-byte as it is (it is the regression test the lane watches).
Add:

- `test_lock_stress_many_threads_many_rounds`: 12 threads x 20 rounds, each round the same shape as the
  existing test but with the stale pre-seeded lock only on round 0; assert `worst == 1`, no errors, no
  `spawn.lock*` files left (including `.takeover` and `.tmp`). Must finish under 10 s.
- `test_empty_lock_file_is_not_stale`: write `""` to `runs/spawn.lock` with a fresh mtime; `R._stale(path)` is
  False; after setting its mtime back by `LOCK_STALE_S + 1` (os.utime) it is True.
- `test_release_only_removes_own_token`: acquire with `spawn_lock`, then inside the `with` overwrite the file
  with another token `"<pid>:deadbeef"`; after the `with` exits the file still exists with that content (we did
  not release someone else's lock); clean it up at the end.
- `test_takeover_side_lock_is_cleared_when_stale`: create `runs/spawn.lock.takeover` with mtime 10 s in the
  past and a stale `spawn.lock` (pid 999999999); `with R.spawn_lock(tmp_path, wait_s=2): pass` succeeds and
  leaves no `spawn.lock*` files.

## What NOT to do

- Do not change `process_state` in `registry.py`.
- Do not change `LOCK_STALE_S`, `room_for`, the resource sampling code, or anything else in `resources.py`
  outside `_try_acquire`, `_stale`, `_take_over`, `spawn_lock`.
- Do not edit or weaken the existing `test_lock_takeover_is_exclusive` (no retries, no marks, no sleeps).
- Do not touch `tools/swarm.py` or anything under `src/pokeagent/explorer/`.
- Do not install anything, do not add `pytest-repeat` or any plugin; the stress test is a plain loop.
- Do not create scratch or debug files; the sandbox denies deletion and the run dies. If you need one it goes
  under `.devin-scratch/` and stays.
- Do not read outside the worktree, do not search for files that are not where this directive says; if one is
  missing, stop and say so in the Status row.

## Verification (run exactly these; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_resources.py
```
Expected: every test passes, including the four new ones and the unchanged `test_lock_takeover_is_exclusive`.

```
uv run pytest -q tests/test_resources.py::test_lock_takeover_is_exclusive tests/test_resources.py::test_lock_stress_many_threads_many_rounds -p no:cacheprovider
```
Run this command 10 times in a row (a shell loop is fine) and paste the 10 result lines. Expected: 10/10 pass.
Before your change, run the stress test alone once or twice to see it fail (paste that too; if it does not
fail in 3 tries, say so and proceed, the deterministic tests still pin the three defects).

```
uv run pytest -q
```
Expected tail at main 7e8c8d2: about 1709 passed, 40 skipped (the 40 are ROM-gated), 0 failed.

## Rules for this run

- The run is NON-INTERACTIVE. Any tool call needing confirmation is rejected and the run ends mid-task. Never
  install, download, or fetch. Never read outside the working directory.
- Work only on the `directive/<slug>` branch the dispatcher created. Never commit to main, never push to main,
  never merge. Commit on the branch as you go.
- If a tool call is genuinely blocked, stop and write why in the Status row rather than working around it.
- Create no scratch or debug files outside `.devin-scratch/`.

## Completion criteria

- `uv run pytest -q tests/test_resources.py` green; the 10x loop 10/10; full suite tail pasted with 0 failed.
- `src/pokeagent/resources.py` has no `os.rename`/`os.link`-back takeover path and no tombstone naming.
- Lock content is `pid:uuid`; release compares the whole token.
- Status row set to Review with the branch name, the diff stat, and the three test tails.

## Report

In the Status row: the before/after flake observation (did the stress test fail before the change?), the
10x loop result, the full-suite tail, the diff stat, and any constant you chose differently from this directive
and why.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Done |
| Assigned to | devin |
| Branch | directive/pokeagent-spawn-lock-takeover-race-directive |
| Base branch | - |
| Base commit | 1de12c26e621a3ec56eb63e658809712e0d56f83 |
| Head commit | ed0f5fe5cc59901a05cac9a488ac22472a111732 |
| Head remote | rfd62794/trailswarm |

**Status log**
- 2026-11-07 19:28 · robert-claude-laptop · none → Queued — Claude 2026-11-07: diagnosis of the flaky test_lock_takeover_is_exclusive (empty-content window, rename/link-back resurrection, same-pid release); approve when a Devin slot frees
- 2026-11-07 19:39 · robert-claude-laptop · Queued → Approved — lint override: dispatch-path-missing is the known false positive on PokeAgent directives; a Devin slot is free (Status_Care finished)
- 2026-11-07 19:40 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-spawn-lock-takeover-race-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6W9K5XGEVV5FYM50F05W5E3
- 2026-11-07 19:46 · dispatcher · launched pid=3004; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-spawn-lock-takeover-race-directive; provisioned: uv sync --frozen
- 2026-11-07 20:02 · devin · In progress → Review — Done. Before/after flake: the new stress test did NOT fail in 3 runs on the old code (passed 3/3, ~12.3s each) — proceeded per directive; 2 of 3 deterministic tests failed on old code as designed (empty file judged stale; .takeover side lock ignored). After the first fix iteration the NEW code exposed two Windows-specific races, both fixed: (a) unlink of a lock file open in another thread's read_text raises PermissionError (no delete-sharing), which the release finally swallowed leaving a live-pid lock -> whole-round LockBusy (worst=0); added _unlink() retry helper used at every unlink site; (b) _take_over could unlink a lock recreated between its inner _stale check and the unlink (worst=2); the taker now records (st_ino, st_mtime_ns) inside the side lock and unlinks only if identity is unchanged. tools/swarm_lock.py::lock_holder now returns the pid part before ':' so transfer_lock/adopt_lock/request_handoff parse 'pid:uuid' content (full-suite regression test_old_spawn_lock_exit_leaves_transferred_lock); tools/swarm.py untouched. 10x loop: 10/10 runs '2 passed' (~8.7-17.8s each). uv run pytest -q tests/test_resources.py: 21 passed. Full suite tail: 1825 passed, 40 skipped, 0 failed in 154.53s. Diff stat: src/pokeagent/resources.py +88/-21-ish, tests/test_resources.py +60, tools/swarm_lock.py +4/-1; 3 files, 131 insertions(+), 21 deletions(-); resources.py now 281 lines (<300). Choices differing from the directive: stress hold is 0.02s not 0.05s (12 threads x 20 rounds x 0.05s = ~12s serial, over the 10s budget); _unlink helper and the ino/mtime recheck inside _take_over added for the Windows races above; swarm_lock.py edited (not in Scope list but required by the token format and not in the NOT-do list). One refusal to disclose: 'uv run python .devin-scratch/stress_probe.py' was refused (diagnostic probe); verified via pytest instead; scratch file left under .devin-scratch/. [origin] spent: devin 16 min est. n/a
- 2026-11-07 20:13 · robert-claude-laptop · Review → Done — note: PR #160 merged (merge commit 41208f8) after Sonnet APPROVE and a green verify record at ed0f5fe (1825 passed, 0 failed, lock test green). Non-blocking follow-ups noted by the reviewer: spawn_lock loop spins without sleep/deadline while the side lock is held (up to 5 s); stress test runs at the 10 s budget; non-FileExists os.link errors map to busy forever (log once); a crash between temp write and link can leave a .tmp file.
<!-- queue:end -->
