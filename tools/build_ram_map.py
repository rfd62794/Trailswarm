"""Regenerate src/pokeagent/data/ram_map.json from pret's pokered.sym (+ optional wram.asm).

usage: uv run python tools/build_ram_map.py <pokered.sym> [--wram wram.asm]

Every WRAM (0xC000-0xDFFF) and HRAM (0xFF80-0xFFFE) label becomes an entry. Verified flags and
evidence already in ram_map.json / ram_names.json are carried over (never downgraded); hand
corrections live in data/ram_overrides.json and are applied last.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "src" / "pokeagent" / "data"
SOURCE = "pokered.sym (pret/pokered, symbols branch)"
MAX_UNKNOWN_SIZE = 256   # distance to the next label is capped here when wram.asm gives no size
CONSTS = {"NUM_CHANNELS": 4, "SCREEN_AREA": 360, "NAME_LENGTH": 11, "PARTY_LENGTH": 6}
REGION_RULES = [
    ("audio", r"^w(Channel|Sound|Music|Audio|Mute|Frequency|Noise|Pitch|Vibrato|Duty|Note|Volume|Square|Wave|Sfx|UnusedMusic|DisableAudio)"),
    ("sprites", r"^w(Sprite|Spr[A-Z0-9]|OAM|Shadow)"),
    ("party", r"^w(BoxMon|BoxData|BoxMons|PartyMon|Party|EnemyPartyMon|EnemyParty|DayCare|Daycare)"),
    ("battle", r"^w(BattleMon|EnemyMon|PlayerMove|EnemyMove|Battle|PlayerBattle|EnemyBattle|Opponent|CurOpponent|Trainer|EnemyTrainer|Critical|Damage|Escape|Caught|SafariBall|IsInBattle|PlayerSub|EnemySub|PlayerBide|EnemyBide|PlayerConfuse|EnemyConfuse|PlayerToxic|EnemyToxic|PlayerDisabled|EnemyDisabled|PlayerUsed|EnemyUsed|PlayerNumAttacks|EnemyNumAttacks|PlayerStatsToDouble|EnemyStatsToDouble|PlayerStatsToHalve|EnemyStatsToHalve|PlayerMonNumber|EnemyMonPartyPos|PlayerSelectedMove|EnemySelectedMove|MoveDidntMiss|MoveMissed|AIMove|AILayer|AI)"),
    ("menu", r"^w(CurrentMenu|MaxMenu|TopMenu|MenuItem|MenuWatch|MenuCursor|Menu|ListMenu|ListScroll|ListCount|PrintItem|ItemList|LastMenu|Option|TextBoxID|PrevWatched|SwapMon|Hlist|ListType)"),
    ("text", r"^w(TileMap|Text|String|Dialog|NameBuffer|Nick|FontLoaded|Letter|Textbox|TilesetTextBox|Dex(Max|Weight))"),
    ("event_flags", r"^w(EventFlags|MissableObject|ObtainedHiddenItems|BeatGym|CompletedInGameTrade|Event|Flag|Fossil|HiddenObject|Obtained(Badges)?)|Flags"),
    ("pokedex", r"^w(Pokedex|Dex)"),
    ("items", r"^w(NumBag|Bag|NumBox|Box|PlayerMoney|PlayerCoins|CurItem|ItemQuantity|Item|Pc|PC|CurBox|Stored)"),
    ("link", r"^w(Link|Serial|Parent|Cable|Trade|Exchange)"),
    ("map", r"CurScript$|^w(Cur(Map|rentMap|Tileset|Block)|Map|Warp|NumberOfWarps|NumSigns|NumSprites|Sign|Tileset|Tile|YCoord|XCoord|YBlock|XBlock|Overworld|Last(Map|Warp)|Dest|Special|Sprite|OAM|Shadow|Door|Fly|Connection|North|South|East|West|Player(Y|X|Dir|Moving|Last)|Grass|Water|Fishing|Repel|Walk|Moving|Simulated|Joy|Auto|Forced|Cut|Bird)"),
    ("player", r"^w(Player|Play|Rival|Starter|Option|LastBlackout|Safari|Status)"),
    ("scratch", r"^w(Buffer|Tmp|Temp|Scratch|Unused|Unknown|Filler|Copy|Save|Stack|Dummy|Sram|Hall|Vram|Compress|Decomp|Frame|Pic|Mon(Pic|Front|Back))"),
]
RANGE_RULES = [(0xC000, 0xC0FF, "audio"), (0xC100, 0xC3FF, "sprites"), (0xC400, 0xC6FF, "text"),
               (0xCC20, 0xCC5F, "menu"), (0xCF00, 0xD0FF, "battle"), (0xD158, 0xD2F6, "party"),
               (0xD2F7, 0xD35F, "player"), (0xD360, 0xD4FF, "map"), (0xD747, 0xD887, "event_flags")]


def region_of(addr: int, name: str) -> str:
    if addr >= 0xFF80:
        return "hram"
    for region, pat in REGION_RULES:
        if re.search(pat, name):
            return region
    for lo, hi, region in RANGE_RULES:
        if lo <= addr <= hi:
            return region
    return "other"


def parse_sym(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^([0-9a-f]{2}):([0-9a-f]{4}) (\S+)$", line)
        if not m or "." in m.group(3) or m.group(1) != "00":
            continue
        addr = int(m.group(2), 16)
        if 0xC000 <= addr <= 0xDFFF or 0xFF80 <= addr <= 0xFFFE:
            out.append((addr, m.group(3)))
    return out


def parse_wram_sizes(path: Path | None) -> dict[str, int]:
    """True sizes from `wLabel:: ds N` / db / dw lines where N is a literal or a known constant."""
    sizes: dict[str, int] = {}
    if path is None:
        return sizes
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^(\w+)::?\s+(ds|db|dw)\b\s*([^;]*)", line)
        if not m:
            continue
        name, op, arg = m.group(1), m.group(2), m.group(3).strip()
        if op in ("db", "dw"):
            unit = 1 if op == "db" else 2
            sizes[name] = unit * (arg.count(",") + 1 if arg else 1)
            continue
        expr = re.sub(r"\$([0-9a-fA-F]+)", lambda x: str(int(x.group(1), 16)), arg)
        expr = re.sub(r"[A-Z_]{3,}", lambda x: str(CONSTS.get(x.group(0), "X")), expr)
        if expr and re.fullmatch(r"[\d\s*+\-()]+", expr):
            sizes[name] = int(eval(expr, {"__builtins__": {}}))  # noqa: S307 - digits/operators only
    return sizes


def build(labels: list[tuple[int, str]], sizes: dict[str, int]) -> list[dict]:
    labels = sorted(labels, key=lambda t: (t[0], t[1]))
    addrs = sorted({a for a, _ in labels})
    nxt = {a: min(addrs[i + 1] if i + 1 < len(addrs) else 0x10000, 0xE000 if a < 0xE000 else 0xFFFF)
           for i, a in enumerate(addrs)}
    entries = []
    for addr, name in labels:
        dist = nxt[addr] - addr
        true = sizes.get(name)
        size = true if true and true <= dist else (dist if true else min(dist, MAX_UNKNOWN_SIZE))
        entries.append({"name": name, "addr": f"0x{addr:04X}", "size": max(size, 1),
                        "encoding": "u8" if size == 1 else "bytes", "region": region_of(addr, name),
                        "verified": False, "source": SOURCE, "sym": name})
    return entries


def carry(entries: list[dict], prior: list[dict], curated: bool = False) -> list[dict]:
    """Merge prior verified/evidence/encoding/note by name (or sym); keep prior-only names too."""
    by_key = {e["name"]: e for e in entries}
    for p in prior:
        e = by_key.get(p["name"]) or by_key.get(p.get("sym", ""))
        if e is None:
            e = dict(p, region=p.get("region") or region_of(int(p["addr"], 16), p["name"]))
            entries.append(e)
            by_key[e["name"]] = e
            continue
        for k in ("evidence", "note"):
            if p.get(k):
                e[k] = p[k]
        if p.get("verified"):
            e["verified"] = True
        if p.get("trust"):
            e["trust"] = p["trust"]
        if p.get("encoding") and p["encoding"] != "bytes":
            e["encoding"] = p["encoding"]
        if p["name"] != e["name"]:
            e["alias"] = p["name"]
        if curated and p.get("size") and e["addr"] == p["addr"] and p["size"] > e["size"]:
            e["size"] = p["size"]
    return entries


def apply_overrides(entries: list[dict], overrides: dict[str, dict]) -> None:
    by_name = {e["name"]: e for e in entries}
    for name, patch in overrides.items():
        if name in by_name:
            by_name[name].update(patch)


def write_map(path: Path, entries: list[dict]) -> None:
    body = ",\n".join(json.dumps(e, separators=(", ", ": ")) for e in entries)
    path.write_text("[\n" + body + "\n]\n", encoding="utf-8")


# The four seed caveat rows: verified entries that are stale in some states. Each clause is
# appended to the row's existing note as `; valid when ...` and the patch keeps the row's
# verified/evidence; a rebuild re-applies these from ram_overrides.json.
CAVEATS = {
    "wBattleMon": "valid when wIsInBattle != 0 and wBattleMon species byte != 0 (stale at battle start: species 0, HP/level/PP leftovers)",
    "wPlayerMonNumber": "valid when wIsInBattle != 0 (stale outside battle)",
    "wGrassRate": "valid when the byte is nonzero; zero means the current map has no grass table",
    "wGrassMons": "valid when wGrassRate != 0; otherwise the previous map's slots remain",
}


def _with_trust(e: dict) -> dict:
    """The same row with ``trust`` inserted right after ``verified``, derived when absent."""
    if "trust" in e:
        return e
    out = {}
    for k, v in e.items():
        out[k] = v
        if k == "verified":
            out["trust"] = "verified" if v else "sym"
    return out


def migrate_trust(map_path: Path, overrides_path: Path) -> list[str]:
    """Give every row a ``trust`` tier in place, with no sym file: derive it from ``verified``,
    write the four caveat patches into ram_overrides.json (so a rebuild keeps them), validate,
    and rewrite the map. Returns trust.validate problems; an empty list means the map was written."""
    import sys
    sys.path.insert(0, str(DATA.parents[1]))  # src/
    from pokeagent.ramlab import trust

    entries = [_with_trust(e) for e in json.loads(map_path.read_text(encoding="utf-8"))]
    by_name = {e["name"]: e for e in entries}
    ov = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    for name, clause in CAVEATS.items():
        patch = ov.setdefault(name, {})
        note = patch.get("note") or by_name.get(name, {}).get("note", "")
        if "valid when" not in note:
            note = f"{note}; {clause}" if note else clause
        patch["note"], patch["trust"] = note, "caveat"
    overrides_path.write_text(json.dumps(ov, indent=1) + "\n", encoding="utf-8")
    apply_overrides(entries, ov)
    problems = trust.validate(entries)
    if not problems:
        write_map(map_path, entries)
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sym", type=Path, nargs="?", help="pokered.sym; not needed for --migrate-trust")
    ap.add_argument("--wram", type=Path)
    ap.add_argument("--out", type=Path, default=DATA / "ram_map.json")
    ap.add_argument("--migrate-trust", action="store_true",
                    help="add trust tiers + caveat overrides to the existing map (no sym file)")
    args = ap.parse_args()
    if args.migrate_trust:
        problems = migrate_trust(args.out, DATA / "ram_overrides.json")
        if problems:
            print("trust validation failed:")
            print("\n".join(f"  - {p}" for p in problems))
            raise SystemExit(1)
        print(f"migrated trust tiers -> {args.out}")
        return
    if args.sym is None:
        ap.error("a sym file is required unless --migrate-trust")
    entries = build(parse_sym(args.sym), parse_wram_sizes(args.wram))
    for p, curated in ((DATA / "ram_names.json", True), (args.out, False)):
        if p.exists():
            entries = carry(entries, json.loads(p.read_text(encoding="utf-8")), curated)
    ov = DATA / "ram_overrides.json"
    if ov.exists():
        apply_overrides(entries, json.loads(ov.read_text(encoding="utf-8")))
    entries.sort(key=lambda e: (int(e["addr"], 16), e["name"]))
    write_map(args.out, entries)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["region"]] = counts.get(e["region"], 0) + 1
    print(f"{len(entries)} entries ->", args.out)
    print(dict(sorted(counts.items())))


if __name__ == "__main__":
    main()
