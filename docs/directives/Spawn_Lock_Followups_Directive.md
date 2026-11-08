# PokeAgent: spawn_lock follow-ups - no hot spin while the side lock is held, honour wait_s, log unlinkable filesystems once, sweep orphan temp files

## Why this exists

PR #160 (merge 41208f8) fixed the takeover races in `src/pokeagent/resources.py` (token content, write-before-visible
via `os.link`, side-locked takeover). The independent review approved it with four non-blocking findings, quoted:

1. "spawn_lock loop: when `_stale(path)` is True and `_take_over` returns early (side lock held, e.g. crashed taker
   up to 5 s, or persistent unlink failure) the loop does `continue` with NO sleep and NO deadline check, so it spins
   hot and can ignore `wait_s`."
2. "Stress test runs ~9.8-10.4 s, right at the directive's 10 s budget and nothing asserts it."
3. "`os.link` failure other than FileExistsError/PermissionError is mapped to 'busy' forever (e.g. a FS without hard
   links gives permanent LockBusy); log once."
4. "A crash between temp write and unlink leaves `spawn.lock.<pid>.<uuid>.tmp` that nothing cleans."

The code as merged (`src/pokeagent/resources.py`, 281 lines):

```python
def _try_acquire(path: Path) -> str | None:                                   # line 171
    token = f"{os.getpid()}:{uuid.uuid4().hex}"
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(token, encoding="utf-8")
        try:
            os.link(tmp, path)
        except OSError:  # FileExistsError: busy; PermissionError: delete-pending target on Windows
            return None
        return token
    finally:
        _unlink(tmp)

TAKEOVER_STALE_S = 5.0                                                         # line 228

@contextmanager
def spawn_lock(root: Path, wait_s: float = 0.0):                               # line 262
    _runs(root).mkdir(parents=True, exist_ok=True)
    path = _runs(root) / "spawn.lock"
    end = time.monotonic() + wait_s
    while (token := _try_acquire(path)) is None:
        if _stale(path):
            _take_over(path)
            continue
        if time.monotonic() >= end:
            raise LockBusy(f"another swarm holds {path}")
        time.sleep(0.05)
    ...
```

`_unlink(path)` (line 196) retries PermissionError for up to 1 s. `_take_over(path)` (line 231) returns early when
the `.takeover` side lock exists and is younger than `TAKEOVER_STALE_S`. `tests/test_resources.py` is 212 lines; the
stress test is `test_lock_stress_many_threads_many_rounds` (line 148, 12 threads x 20 rounds).

## Scope (in this order)

1. `src/pokeagent/resources.py`: `spawn_lock` loop, `_try_acquire`, a new orphan sweep.
2. `tests/test_resources.py`: three new tests; trim the stress test's budget.

Read first: `src/pokeagent/resources.py` lines 165-281 and `tests/test_resources.py` in full.

## The work

### 1. `resources.py`

- **No hot spin, deadline always checked.** Restructure the loop so every iteration that does not acquire checks the
  deadline and sleeps:
  ```python
  while (token := _try_acquire(path)) is None:
      if _stale(path):
          _take_over(path)          # may return early while another taker holds the side lock
      if time.monotonic() >= end:
          raise LockBusy(f"another swarm holds {path}")
      time.sleep(0.05)
  ```
  A successful takeover costs one 50 ms sleep before the retry; that is acceptable.
- **Unlinkable filesystem: log once, then raise.** In `_try_acquire`, keep returning `None` for `FileExistsError` and
  `PermissionError`. For any other `OSError` from `os.link` (for example `errno.EPERM`/`ENOTSUP` on a filesystem
  without hard links), log once per process at WARNING with the errno and strerror (module logger
  `logging.getLogger(__name__)`; a module-level `_link_warned: set[int]` keyed by errno) and raise `LockBusy` with the
  strerror in the message so the caller fails fast instead of waiting `wait_s`.
- **Orphan sweep.** Add `_sweep_tmp(path: Path) -> None`: for each sibling matching `spawn.lock.*.tmp` whose pid (the
  first dotted field after `spawn.lock.`) is `process_state(pid) == "gone"` OR whose mtime is older than 60 s, unlink
  it (narrow `except OSError: pass` per file is acceptable here; this is best-effort cleanup). Call it once at the top
  of `spawn_lock`, before the loop. Never touch `.takeover` here (that has its own stale rule).
- Keep the file under 300 lines (it is 281; if the sweep pushes it over, move `_sweep_tmp` and `_unlink` into a new
  `src/pokeagent/lockfiles.py` and import them; nothing else moves). No new dependency.

### 2. `tests/test_resources.py`

- `test_spawn_lock_honours_wait_s_while_side_lock_is_held`: create a live-looking `runs/spawn.lock` (content
  `f"{os.getpid()}:deadbeef"`, mtime now) is NOT what we want here; instead create a STALE lock (pid 999999999) and a
  fresh `runs/spawn.lock.takeover` (mtime now, so `_take_over` returns early). `with R.spawn_lock(tmp_path,
  wait_s=0.3)` must raise `LockBusy` after between 0.3 and 1.0 s (measure with `time.monotonic`), proving the deadline
  is checked and there is no hot spin (also assert the loop slept: count `time.sleep` calls via monkeypatch >= 3).
- `test_unlinkable_filesystem_logs_once_and_raises`: monkeypatch `os.link` to raise `OSError(errno.EPERM, "hard links
  not supported")`; the first `spawn_lock` raises `LockBusy` whose message contains "hard links not supported" and
  logs one WARNING (use `caplog`); a second call raises again with no new log line.
- `test_orphan_tmp_files_are_swept`: create `runs/spawn.lock.999999999.abc.tmp` (gone pid) and
  `runs/spawn.lock.<os.getpid()>.def.tmp` with mtime 120 s in the past (old) and
  `runs/spawn.lock.<os.getpid()>.ghi.tmp` fresh (live, must survive); after `with R.spawn_lock(tmp_path): pass` only
  the fresh one remains, plus no `spawn.lock`.
- Stress budget: reduce `test_lock_stress_many_threads_many_rounds` to 12 threads x 12 rounds (or shorten the
  per-round hold from 0.05 s to 0.02 s) so it runs under 5 s, and assert `elapsed < 8.0` so the budget is enforced.
  Keep `test_lock_takeover_is_exclusive` byte-for-byte unchanged.

## What NOT to do

- Do not change the token format, `_stale`, `_take_over`, `_lock_pid`, `TAKEOVER_STALE_S`, or `tools/swarm_lock.py`.
- Do not edit `test_lock_takeover_is_exclusive`.
- Do not touch anything outside `src/pokeagent/resources.py`, the optional new `src/pokeagent/lockfiles.py`, and
  `tests/test_resources.py`.
- Do not install anything. Do not create scratch files outside `.devin-scratch/` (deleting is denied in the sandbox).
- Do not read outside the worktree or search for files this directive does not name; if one is missing, stop and
  say so in the Status row.

## Verification (run exactly these; `uv run python --version` prints `Python 3.12.12`)

```
uv run pytest -q tests/test_resources.py
```
Expected: all pass (21 existing + 3 new), stress test under 8 s.

```
uv run pytest -q tests/test_resources.py::test_lock_takeover_is_exclusive tests/test_resources.py::test_lock_stress_many_threads_many_rounds -p no:cacheprovider
```
Run 5 times; paste the 5 result lines. Expected 5/5 pass.

```
uv run pytest -q
```
Expected tail at main 41208f8 or later: about 1825+ passed, 40 skipped (ROM-gated), 0 failed.

## Rules for this run

- NON-INTERACTIVE: any tool call needing confirmation is rejected and the run ends. Never install, download, fetch,
  or read outside the working directory.
- Work only on the `directive/<slug>` branch the dispatcher created; commit as you go; never commit to or push main;
  never merge.
- If a tool call is blocked, stop and write why in the Status row.

## Completion criteria

- The three new tests exist and pass; `test_lock_takeover_is_exclusive` unchanged; stress test asserts its budget.
- `spawn_lock` has no code path that loops without both a deadline check and a sleep.
- Status row set to Review with the diff stat and the three test tails.

## Report

In the Status row: diff stat, the 5x loop lines, the full-suite tail, and whether `lockfiles.py` was needed.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Queued |
| Assigned to | devin |
| Branch | - |
| Base branch | - |

**Status log**
- 2026-11-07 20:14 · robert-claude-laptop · none → Queued — Claude 2026-11-07: the four non-blocking review findings on PR #160, as a Devin follow-up
<!-- queue:end -->
