"""``pokeagent bytecheck build|scan|staged``. Exit 0 clean/suspect, 1 LEAK, 2 usage/no index."""
from __future__ import annotations

import argparse
import json
import sys
import subprocess
from pathlib import Path

from pokeagent.bytecheck import policy
from pokeagent.bytecheck.fingerprint import (
    DEFAULT_INDEX, Index, IndexError_, build_index, load_index, save_index)
from pokeagent.bytecheck.scan import scan_blob, scan_bytes

BLOCKED_SUFFIXES = (".gb", ".gbc", ".gba", ".sgb")    # ROM images: never committed
ROM_SUFFIXES = BLOCKED_SUFFIXES + (".sav",)
MEDIA_SUFFIXES = (".png", ".gif", ".mp4", ".webm", ".jpg", ".jpeg")


def profile_for(path: str) -> str:
    low = path.lower()
    if low.endswith(".state"):
        return "state"
    return "media" if low.endswith(MEDIA_SUFFIXES) else "commit"


def _cmd_build(args) -> int:
    from pokeagent.cli import _resolve_game, rom_sha1_check   # reuse check-rom's SHA-1 logic
    ref = Path(args.ref)
    if not ref.is_file():
        print(f"reference not found: {ref}")
        return 2
    spec = _resolve_game(args)
    if spec is None:
        return 2
    size, sha1, match = rom_sha1_check(ref, spec)
    print(f"sha1: {sha1} ({'match' if match else 'MISMATCH vs ' + spec.rom_sha1[0]})")
    if not match and not args.allow_mismatch:
        print("refusing to index a file that is not the known ROM (--allow-mismatch to override)")
        return 1
    idx = build_index(ref.read_bytes())
    out = save_index(idx, Path(args.index))
    print(f"indexed {idx.distinct} windows of {size} bytes -> {out} (hashes only; keep out of git)")
    return 0


def _report(items, idx: Index, as_json: bool, skipped=(), warnings=()) -> int:
    """``items``: (path, profile, data|None). ``data`` None means the content could not be read: that fails loudly."""
    rows, worst, unreadable = [], policy.CLEAN, []
    for path, prof, data in items:
        if data is None:
            unreadable.append(path)
            rows.append({"path": path, "profile": prof, "verdict": "UNREADABLE"})
            continue
        res = scan_blob(data, idx, str(path)) if not str(path).lower().endswith(ROM_SUFFIXES) \
            else scan_bytes(data, idx, str(path))
        v = policy.verdict(res, prof)
        if str(path).lower().endswith(ROM_SUFFIXES) and v != policy.LEAK:
            v = policy.SUSPECT      # a ROM/save-looking file name is never CLEAN
        rows.append({**res.to_dict(), "profile": prof, "verdict": v})
        if v == policy.LEAK or (v == policy.SUSPECT and worst == policy.CLEAN):
            worst = v
    if unreadable and worst != policy.LEAK:
        worst = "ERROR"
    if as_json:
        out = {"verdict": worst, "files": rows, "skipped": [{"path": p, "reason": "submodule"} for p in skipped],
               "warnings": list(warnings)}
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        for w in warnings:      # never loose stdout text in --json mode; plain mode keeps stdout for verdicts only
            print(w, file=sys.stderr)
        for p in skipped:
            print(f"{'SKIPPED':8} {p}: skipped (submodule)")
        for r in rows:
            if r["verdict"] == "UNREADABLE":
                print(f"{'ERROR':8} {r['path']} [{r['profile']}] cannot read the staged content: NOT scanned")
                continue
            print(f"{r['verdict']:8} {r['path']} [{r['profile']}] windows={r['matched_windows']} "
                  f"coverage={r['coverage']:.4%} longest_run={r['longest_run']}B ({r['view']})")
            for run in r["top_runs"][:3]:
                print(f"           run @{run['offset']} len {run['length']} (ref @{run['ref_offset']})")
        print(f"overall: {worst}")
    return {policy.LEAK: 1, "ERROR": 2}.get(worst, 0)


def _load(args) -> Index | None:
    try:
        return load_index(Path(args.index))
    except IndexError_ as e:
        print(f"error: {e}")
        return None


def _cmd_scan(args) -> int:
    idx = _load(args)
    if idx is None:
        return 2
    missing = [p for p in args.paths if not Path(p).is_file()]
    if missing:
        print(f"error: not a file: {', '.join(missing)}")
        return 2
    return _report([(p, args.profile or profile_for(p), Path(p).read_bytes()) for p in args.paths], idx, args.json)


def _git(top: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", top, *args], capture_output=True, check=True).stdout


def _staged_files() -> tuple[str, list[str]]:
    """(repo toplevel, staged paths relative to it) - independent of the current directory."""
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True).stdout.decode().strip()
    out = _git(top, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return top, [p for p in out.decode().split("\0") if p]


def _gitlinks(top: str) -> set[str]:
    """Staged submodule entries (mode 160000): they have no blob to read."""
    out = _git(top, "ls-files", "-s", "-z").decode()
    links = set()
    for ent in out.split("\0"):
        meta, _, path = ent.partition("\t")
        if meta.startswith("160000"):
            links.add(path)
    return links


def _staged_blob(top: str, path: str) -> bytes | None:
    """The staged (index) content of ``path``; None when it cannot be read."""
    try:
        return _git(top, "show", f":0:{path}")
    except (subprocess.CalledProcessError, OSError):
        return None


def _cmd_staged(args) -> int:
    try:
        top, files = _staged_files()
        links = _gitlinks(top)
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"error: cannot list staged files (not a git repository?): {e}")
        return 2
    skipped = [p for p in files if p in links]
    files = [p for p in files if p not in links]
    blocked = [p for p in files if p.lower().endswith(BLOCKED_SUFFIXES)]
    if blocked:      # a ROM file never goes into git, whatever the index says (checked before the index is even needed)
        for p in blocked:
            print(f"BLOCKED  {p}: ROM files must never be committed")
        print("overall: BLOCKED")
        return 1
    idx = _load(args)
    if idx is None:
        return 0 if args.skip_if_no_index else 2
    if not files and not skipped:
        print("bytecheck: nothing staged")
        return 0
    warnings = [f"warning: {p} is a save file: treated as SUSPECT, check it holds no ROM bytes"
                for p in files if p.lower().endswith(".sav")]
    return _report([(p, args.profile or profile_for(p), _staged_blob(top, p)) for p in files], idx, args.json,
                   skipped=skipped, warnings=warnings)


def register(sub) -> None:
    p = sub.add_parser("bytecheck", help="detect ROM bytes in files (see docs/BYTECHECK.md)")
    bsub = p.add_subparsers(dest="bytecheck_cmd", required=True)

    def common(sp, profile=True):
        sp.add_argument("--index", default=str(DEFAULT_INDEX), metavar="PATH",
                        help=f"fingerprint index (default {DEFAULT_INDEX})")
        if profile:
            sp.add_argument("--profile", choices=sorted(policy.PROFILES),
                            help="artifact kind; default by file extension")
            sp.add_argument("--json", action="store_true")

    b = bsub.add_parser("build", help="build the local index from the ROM")
    b.add_argument("--ref", required=True, metavar="ROM")
    b.add_argument("--allow-mismatch", action="store_true", help="index even if SHA-1 is unknown")
    from pokeagent.game import add_game_argument
    add_game_argument(b)
    common(b, profile=False)
    b.set_defaults(func=_cmd_build)

    s = bsub.add_parser("scan", help="scan files; exit 1 on LEAK")
    s.add_argument("paths", nargs="+")
    common(s)
    s.set_defaults(func=_cmd_scan)

    t = bsub.add_parser("staged", help="scan git-staged files (usable as a pre-commit hook)")
    t.add_argument("--skip-if-no-index", action="store_true",
                   help="exit 0 instead of 2 when no index exists")
    common(t)
    t.set_defaults(func=_cmd_staged)
