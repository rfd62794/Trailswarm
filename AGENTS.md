# PokeAgent - notes for agents

Verify command: uv run pytest -q -p no:cacheprovider -rfEs

- Python 3.12 via `uv run` only. The full suite is about 3000 tests, about 4 minutes serial (no pytest-xdist in this env).
- ROM-dependent tests skip when `roms/` is absent; ROM checks run on the laptop only. Never commit or publish ROMs,
  save states, recorded datasets or weights (all live under gitignored `roms/` and `runs/`), and never state where a
  game copy came from.
- Work on a branch; merges go through `uv run agentflow merge PokeAgent <PR> --apply` (merge commit, pinned head).
- Tests never open a window or send GUI input.
