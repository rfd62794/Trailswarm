"""Edit a save state's RAM (pokeagent.surgery) and stamp the result synthetic.

    uv run python tools/state_edit.py IN.state --out OUT.state [--rom ROM] [--heal] [--money N] [--respawn M]
        [--give ID:QTY ...] [--take ID:QTY ...] [--set-hp SLOT:HP ...] [--set-level SLOT:LEVEL ...]
        [--pos MAP:X:Y --unsafe-pos] [--dry-run] [--force]

Numbers accept decimal or 0x hex (`--give 0x13:1`, `--respawn 0x05`). The output fingerprint gets
`synthetic: true` plus `edited` (the edits applied) and `parent` (the input state) - a synthetic state is for
drills and A/B only and the curriculum never lets it start a segment or count as a best. The goals sidecar is
deliberately NOT copied: it holds the parent's respawn, which read_respawn prefers over the fingerprint.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pokeagent import statefp, surgery  # noqa: E402

DEFAULT_OUT_DIR = ROOT / "runs" / "edited"


def make_emulator(rom: Path):
    """The emulator the tool drives (a seam so tests can inject a FakeEmulator)."""
    from pokeagent.emulator import PyBoyEmulator
    return PyBoyEmulator(Path(rom), headless=True)


def _num(s: str) -> int:
    return int(s, 16) if s.lower().startswith("0x") else int(s)


def _num_pair(s: str) -> tuple[int, int]:
    a, sep, b = s.partition(":")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected ID:QTY or SLOT:VALUE, got {s!r}")
    return _num(a), _num(b)


def _max_pp():
    """move id -> base PP from the ROM-drained moves table (kb/rom_tables.json); None when there is no table."""
    from pokeagent.knowledge import kb
    moves = kb.table(None, "moves")
    if not moves:
        return None

    def pp_of(move_id: int) -> int | None:
        row = moves.get(str(move_id)) or {}
        try:
            return int(row["pp"])
        except (KeyError, TypeError, ValueError):
            return None
    return pp_of


def _growth():
    """species id -> growth group from the ROM-drained species table (kb/rom_tables.json); None without it."""
    from pokeagent.knowledge import kb
    species_by_dex, dex_of = kb.table(None, "species_by_dex"), kb.table(None, "dex_of_internal")
    if not species_by_dex:
        return None

    def growth_of(species: int) -> str | None:
        row = species_by_dex.get(str(int(dex_of.get(str(species), 0) or 0))) or {}
        return row.get("growth")
    return growth_of


def _legality_inputs():
    """(kb, catalog, hm) the legality checker reads: the ROM-drained tables when present, else Nones."""
    from pokeagent.knowledge import hm_compat, items_catalog, kb
    return kb.ROM_KB, items_catalog.load(), hm_compat.load()


def _respawns_seen():
    """Respawn town ids organic states carry (envelope over the state dirs); empty when there is no data."""
    from pokeagent import envelope
    env = envelope.build([ROOT / "runs" / "checkpoints", ROOT / "runs" / "legs" / "states"])
    return envelope.respawns_seen(env)


def _edits(a) -> dict:
    edits: dict = {}
    if a.heal:
        edits["heal"] = True
    if a.set_hp:
        edits["set_hp"] = {slot: hp for slot, hp in a.set_hp}
    if a.set_level:
        edits["set_level"] = {slot: lv for slot, lv in a.set_level}
    if a.money is not None:
        edits["money"] = a.money
    if a.respawn is not None:
        edits["respawn"] = a.respawn
    if a.give:
        edits["give"] = [list(p) for p in a.give]
    if a.take:
        edits["take"] = [list(p) for p in a.take]
    if a.pos is not None:
        edits["position"] = {"map": a.pos[0], "x": a.pos[1], "y": a.pos[2], "unsafe_pos": a.unsafe_pos}
    return edits


def _pos(s: str) -> tuple[int, int, int]:
    parts = s.split(":")
    try:
        vals = [_num(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError(f"--pos must be MAP:X:Y numbers, got {s!r}") from None
    if len(vals) != 3:
        raise argparse.ArgumentTypeError(f"--pos must be MAP:X:Y, got {s!r}")
    return tuple(vals)


def _under_runs(out: Path, name: str) -> bool:
    parts = out.resolve().parts
    return any(parts[k - 1] == "runs" and parts[k] == name for k in range(1, len(parts)))


def _refuse(a, out: Path) -> str | None:
    if out.resolve() == a.state.resolve():
        return "OUT must differ from IN"
    if _under_runs(out, "checkpoints") or _under_runs(out, "segments"):
        return "OUT must not live under runs/checkpoints/ or runs/segments/ (a synthetic state is never a chain state)"
    if out.exists() and not a.force:
        return f"{out} exists (use --force to overwrite)"
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("state", type=Path, metavar="IN.state")
    ap.add_argument("--out", type=Path, default=None, help="output state (default runs/edited/<IN.name>)")
    ap.add_argument("--rom", type=Path, default=ROOT / "roms" / "Pokemon Red.gb")
    ap.add_argument("--heal", action="store_true", help="full HP, clear status, restore PP (needs kb move table)")
    ap.add_argument("--money", type=_num, metavar="N")
    ap.add_argument("--respawn", type=_num, metavar="M", help="blackout respawn town id 0..10")
    ap.add_argument("--give", type=_num_pair, nargs="+", action="append", default=[], metavar="ID:QTY")
    ap.add_argument("--take", type=_num_pair, nargs="+", action="append", default=[], metavar="ID:QTY")
    ap.add_argument("--set-hp", type=_num_pair, nargs="+", action="append", default=[], metavar="SLOT:HP")
    ap.add_argument("--set-level", type=_num_pair, nargs="+", action="append", default=[], metavar="SLOT:LEVEL")
    ap.add_argument("--pos", type=_pos, default=None, metavar="MAP:X:Y", help="move within the current map")
    ap.add_argument("--unsafe-pos", action="store_true",
                    help="required for --pos. UNSAFE: desyncs the view (the map view pointer 0xD35F and scroll are not "
                         "shifted); A/B drills must not use it")
    ap.add_argument("--dry-run", action="store_true", help="apply in memory and print the writes; save nothing")
    ap.add_argument("--force", action="store_true", help="overwrite an existing OUT")
    ap.add_argument("--allow-illegal", action="store_true",
                    help="save even when the edit makes the state illegal (stamps legal.ok: false with the violations)")
    a = ap.parse_args(argv)
    for flag in ("give", "take", "set_hp", "set_level"):
        setattr(a, flag, [p for group in getattr(a, flag) for p in group])

    out = a.out or DEFAULT_OUT_DIR / a.state.name
    why = _refuse(a, out)
    if why:
        print(f"refused: {why}", file=sys.stderr)
        return 2

    edits = _edits(a)
    emu = make_emulator(a.rom)
    try:
        from pokeagent import legality, lineage
        from pokeagent.ramstructs import read_party
        emu.load_state(a.state)
        kb, catalog, hm = _legality_inputs()
        before = legality.check(emu, kb, catalog=catalog, hm=hm)
        money_before = statefp.fingerprint(emu).get("money")
        hp_before = [m.hp for m in read_party(emu)]
        try:
            writes = surgery.apply(emu, edits, max_pp=_max_pp(), growth=_growth())
        except surgery.SurgeryError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
        for addr, old, new in writes:
            print(f"0x{addr:04X} 0x{old:02X} -> 0x{new:02X}")
        after = legality.check(emu, kb, catalog=catalog, hm=hm)
        new_violations = [v for v in after.violations if v not in before.violations]
        if a.dry_run:
            print(f"legality: ok={after.ok} violations={after.violations} warnings={after.warnings}")
            print(f"dry run: {len(writes)} writes; nothing saved")
            return 0
        if new_violations and not a.allow_illegal:
            print(f"refused: the edit makes the state illegal: {'; '.join(new_violations)} "
                  f"(use --allow-illegal to save anyway)", file=sys.stderr)
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        emu.save_state(out)
        fp = statefp.stamp(emu, out, source_run=f"edit:{a.state.name}")
        parent_fp = statefp.read(a.state) or {}
        parent_lineage = statefp.lineage(a.state)
        context = {"money_before": money_before, "parent_lineage": parent_lineage}
        eclass = ("shortcut" if parent_lineage != "organic" and parent_fp.get("edit_class") != "organic_equivalent"
                  else lineage.edit_class(edits, {**context, "hp": hp_before}, catalog, _respawns_seen()))
        fp.update(synthetic=True, edited=edits, parent=a.state.name, lineage=lineage.SYNTHETIC,
                  edit_class=eclass, edit_context=context,
                  legal={"ok": not after.violations, "violations": after.violations,
                         "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        statefp.write(out, fp)
        print(f"saved {out} ({len(writes)} writes, stamped synthetic/{eclass}, legal.ok={not after.violations})")
        return 0
    finally:
        emu.close()


if __name__ == "__main__":
    raise SystemExit(main())
