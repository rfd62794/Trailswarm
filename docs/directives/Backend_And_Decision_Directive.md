# PokeAgent: model backends and reply parsing - `Backend` protocol, `StubBackend`, `ClaudeCliBackend`, `parse_reply`

**Read first:** `docs/superpowers/specs/2026-11-02-pokeagent-design.md` (the design; this directive is build step 2 of 3
and is independent of step 1 - it touches none of the same files).

## 1. Why this exists

The agent loop (directive 3) asks a model for one button per step and shows its reasoning on the console. The
call must be isolated (no tools, no session), bounded (timeout), and its reply parsed tolerantly, because a
model that answers in prose or fenced JSON must not crash a 50-step run. Nothing of this exists yet.

Verified on the laptop 2026-11-02: `claude` is at `C:\Users\cheat\.local\bin\claude.exe`. The exact command, with
the prompt on stdin, returned `{"button":"A"}`:

```
claude -p --tools "" --no-session-persistence --model haiku --output-format text
```

`--tools ""` disables every built-in tool; `--no-session-persistence` keeps the call stateless. Devin's run
cannot call `claude` (needs network and confirmation), so `ClaudeCliBackend` is tested with a fake subprocess
runner injected at construction.

Reply protocol the model is asked for (the prompt is directive 3's job; the parser is yours):

```json
{"thinking": "one or two sentences of reasoning", "button": "A", "note": "optional text to remember"}
```

**Worktree layout (pasted so you never need to list it; a recursive listing such as
`Get-ChildItem -Recurse` or `find` is refused by the sandbox and ends the run):**

```
.gitignore  pyproject.toml  uv.lock  .venv/
src/pokeagent/__init__.py
tests/test_smoke.py
docs/directives/*.md   docs/superpowers/specs/2026-11-02-pokeagent-design.md
```

`src/pokeagent/emulator.py` and `ram.py` may or may not exist (directive 1 runs in parallel); you do not need
them. Use `git status`, `git ls-files`, or read a named file; nothing else to discover.

## 2. Scope

Create, in order:

1. `src/pokeagent/decision.py` - `Decision` dataclass, `VALID_BUTTONS`, `parse_reply(text: str) -> Decision`.
2. `src/pokeagent/backend.py` - `Backend` protocol, `BackendError`, `StubBackend`, `ClaudeCliBackend`.
3. `tests/test_decision.py`, `tests/test_backend.py`.

## 3. The work

### `decision.py`

`VALID_BUTTONS = ("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "START", "SELECT", "NONE")` - kept local; do not
import from `emulator.py` (directive 1 may not have landed).

`Decision` (frozen dataclass): `button: str` (uppercased, in `VALID_BUTTONS`), `thinking: str = ""`,
`note: str = ""`, `error: str = ""`, `raw: str = ""`.

`parse_reply(text)`:
- Strip markdown fences (```` ```json ... ``` ````) and surrounding prose; find the first `{...}` object with a
  balanced-brace scan (not a greedy regex) and `json.loads` it.
- `button` case-insensitive; `thinking` truncated to 1000 characters; `note` truncated to 500.
- Any failure (no object, bad JSON, unknown or missing button) returns
  `Decision("NONE", error="<short reason>", raw=text[:500])`, keeping any `thinking` that did parse. Never raise.

### `backend.py`

- `class BackendError(Exception)`.
- `Backend` protocol: `choose(prompt: str) -> str` (raw text; parsing is the caller's job) and `name: str`.
- `StubBackend(replies: list[str] | None = None, default: str = '{"thinking": "stub", "button": "A"}')` -
  returns replies in order, then `default` forever; records `prompts: list[str]`. `name = "stub"`.
- `ClaudeCliBackend(model: str = "haiku", timeout_s: int = 120, runner=None, cwd: Path | None = None)`:
  - Finds the executable with `shutil.which("claude")` at construction; `None` -> `BackendError("claude CLI not on PATH")`.
  - Command: `[exe, "-p", "--tools", "", "--no-session-persistence", "--model", model, "--output-format", "text"]`.
  - `runner` defaults to `subprocess.run`; call it with `input=prompt, capture_output=True, text=True,
    timeout=timeout_s, cwd=cwd, encoding="utf-8"`. Tests inject a fake runner that records the call.
  - `subprocess.TimeoutExpired` -> `BackendError(f"timeout after {timeout_s}s")`; non-zero return code ->
    `BackendError(f"exit {rc}: {stderr[:200]}")`; otherwise return `stdout`.
  - `name = f"claude:{model}"`.

## 4. What NOT to do

- Do not call the real `claude` binary in tests; do not require it to be installed for tests to pass (patch
  `shutil.which` in the tests that construct the backend).
- Do not build an Anthropic SDK backend, retries, or a failure counter (that is the loop's job in directive 3).
- Do not touch `emulator.py`, `ram.py`, `pyproject.toml`, `uv.lock`.
- Do not download, install, or read outside the worktree.

## 5. Verification

- `uv run pytest -q` -> green, at least 14 new tests. Include: plain JSON with all three fields; fenced JSON;
  JSON inside prose; lowercase button; unknown button -> `NONE` with `error` and preserved `thinking`; missing
  button; empty string; note and thinking truncation; `StubBackend` order and default; `ClaudeCliBackend` command
  line exactly as above (assert the list); timeout -> `BackendError`; non-zero exit -> `BackendError` with
  stderr; missing executable -> `BackendError`.
- `uv run python -c "from pokeagent.decision import parse_reply; print(parse_reply('ok: {\"button\":\"up\"}'))"`
  prints a `Decision` with `button='UP'`.

## 6. Rules for this run

- NON-INTERACTIVE: any tool call that needs confirmation ends the run. No installs, downloads, fetches, or reads
  outside the worktree. If something expected is missing, stop and write that in the Status row; do not hunt.
- Test command is exactly `uv run pytest -q`. Never bare `python`.
- Work only on branch `directive/pokeagent-backend-and-decision-directive`. Never commit to `main`, never push
  to it, never merge.
- Create no scratch or debug files; if unavoidable, under `.devin-scratch/` and it stays.
- Keep every new module under 200 lines.

## 7. Completion criteria

- [ ] `decision.py` with `Decision`, `VALID_BUTTONS`, `parse_reply`
- [ ] `backend.py` with `BackendError`, `Backend`, `StubBackend`, `ClaudeCliBackend`
- [ ] `tests/test_decision.py`, `tests/test_backend.py`
- [ ] `uv run pytest -q` green (paste the tail in the report)
- [ ] Status row moved to Review with the branch name

## 8. Report

Test tail, line counts per new file, and any decision not written in the design.

<!-- queue:start -->
## Queue

| Field | Value |
|---|---|
| Status | Blocked |
| Assigned to | devin |
| Branch | directive/pokeagent-backend-and-decision-directive |
| Base branch | - |
| Base commit | 0014c10bb4d1bef55b63ef0e395aa14b8ba783e9 |

**Status log**
- 2026-11-02 21:54 · robert-claude-laptop · none → Queued — build step 2 of 3; independent of step 1, runs in parallel
- 2026-11-02 21:56 · robert-claude-laptop · Queued → Approved — lint override: greenfield directive: the cited paths are the files it creates (section 2 says Create), not files it reads; dispatch-path-missing is a false positive here
- 2026-11-02 21:56 · dispatcher · Approved → In progress — dispatched devin on personal-laptop in C:\GitHub\.worktrees\PokeAgent--pokeagent-backend-and-decision-directive; lane=default; model=swe-2-high; persona=steady-builder; agent_id=01M6FNCTAN9S6DQA116B87KQJV
- 2026-11-02 22:00 · dispatcher · launched pid=30568; worktree C:\GitHub\.worktrees\PokeAgent--pokeagent-backend-and-decision-directive; provisioned: uv sync --frozen
- 2026-11-02 22:00 · dispatcher · In progress → Blocked — dispatch died at spawn: Directive is clear: create `decision.py`, `backend.py`, and their tests. Let me check the worktree layout.warning: rejected a tool call that requires confirmation. Running in non-interactive mode. Use --permission-mode dangerous to auto-approve all tools.
<!-- queue:end -->
