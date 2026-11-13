# bytecheck: "does this file contain game bytes?"

One module (`pokeagent.bytecheck`) for save-state fixtures, media (screenshots/video), map
exports/atlases, publish bundles and git commits.

## What it guarantees
Every 32-byte window (stride 1) of the ROM is hashed (64-bit) if it has enough entropy (>= 8
distinct byte values and <= 24 bytes of 0x00/0xFF). A scanned file gets the same treatment; any
**exact** run of ROM bytes of >= 32 bytes is found. Output: matched windows, coverage of the ROM,
longest contiguous run, top run offsets. PNGs are also scanned as decoded RGBA pixels; other types
(video included) are scanned as file bytes only.

## What it does not
- Only exact byte runs. Compressed, re-encoded, re-paletted, or lightly modified ROM data is **not** detected.
- Not a legal determination. Thresholds in `policy.py` are **untuned** guesses.
- The sha1 check says the ROM is the known one, not that a target is safe.

## Verdicts (`policy.py`, untuned)
LEAK if longest run >= N bytes or coverage >= X; SUSPECT above the lower pair; else CLEAN.
Profiles: `state` (16384 B / 5%, suspect 2048 B / 1%: VRAM and WRAM legitimately hold ROM-derived tile
data and tables), `media` and `export` (256 B / 1%, suspect 64 B / 0.1%), `commit` (128 B / 0.5%,
suspect 48 B / 0.05%). The CLI picks a profile by extension unless `--profile` is given.

## Use
```
uv run pokeagent bytecheck build --ref "roms/Pokemon Red.gb"   # checks SHA-1 via check-rom logic
uv run pokeagent bytecheck scan out/*.png tests/fixtures/rom_states/*.state [--profile state] [--json]
uv run pokeagent bytecheck staged                              # git-staged files
```
Exit codes: 0 clean/suspect, 1 LEAK (or SHA-1 mismatch on build), 2 usage / no index.

The index (hashes + offsets, never ROM bytes) is `runs/bytecheck/index.npz`; `runs/` is gitignored.
Build it locally; never commit it.

## Pre-commit hook (documented, NOT installed)
`.git/hooks/pre-commit`:
```
#!/bin/sh
exec uv run pokeagent bytecheck staged --skip-if-no-index
```
Without `--skip-if-no-index`, a missing index exits 2 and blocks the commit. Files named
`.gb/.gbc/.sav` are never CLEAN.
