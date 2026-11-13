"""``pokeagent bytecheck build|scan|staged``. Exit 0 clean/suspect, 1 LEAK, 2 usage/no index."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from pokeagent.bytecheck import policy
from pokeagent.bytecheck.fingerprint import (
    DEFAULT_INDEX, Index, IndexError_, build_index, load_index, save_index)
from pokeagent.bytecheck.scan import scan_bytes, scan_file

ROM_SUFFIXES = (".gb", ".gbc", ".sav")
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


def _report(paths_profiles, idx: Index, as_json: bool) -> int:
    rows, worst = [], policy.CLEAN
    for path, prof in paths_profiles:
        res = scan_file(Path(path), idx) if not str(path).lower().endswith(ROM_SUFFIXES) \
            else scan_bytes(Path(path).read_bytes(), idx, str(path))
        v = policy.verdict(res, prof)
        if str(path).lower().endswith(ROM_SUFFIXES) and v != policy.LEAK:
            v = policy.SUSPECT      # a ROM/save-looking file name is never CLEAN
        rows.append({**res.to_dict(), "profile": prof, "verdict": v})
        if v == policy.LEAK or (v == policy.SUSPECT and worst == policy.CLEAN):
            worst = v
    if as_json:
        print(json.dumps({"verdict": worst, "files": rows}, indent=2, sort_keys=True))
    else:
        for r in rows:
            print(f"{r['verdict']:8} {r['path']} [{r['profile']}] windows={r['matched_windows']} "
                  f"coverage={r['coverage']:.4%} longest_run={r['longest_run']}B ({r['view']})")
            for run in r["top_runs"][:3]:
                print(f"           run @{run['offset']} len {run['length']} (ref @{run['ref_offset']})")
        print(f"overall: {worst}")
    return 1 if worst == policy.LEAK else 0


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
    return _report([(p, args.profile or profile_for(p)) for p in args.paths], idx, args.json)


def _staged_files() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                         capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def _cmd_staged(args) -> int:
    idx = _load(args)
    if idx is None:
        return 0 if args.skip_if_no_index else 2
    files = _staged_files()
    if not files:
        print("bytecheck: nothing staged")
        return 0
    return _report([(p, args.profile or profile_for(p)) for p in files if Path(p).is_file()],
                   idx, args.json)


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
