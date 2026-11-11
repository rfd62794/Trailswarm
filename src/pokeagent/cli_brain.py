"""``pokeagent brain``: inspect the whole model and perform safe surgery on it.

JSON output by default (sorted keys, stable for diffing); ``--text`` for humans.
Reads ``runs/maps.json`` (``--maps PATH``) and the edit journal ``memory_edits.jsonl``
beside it; edits are appended to the journal, never written into maps.json directly -
``apply --backup`` is the only fold, and it refuses while any agent is alive. All logic
lives in ``pokeagent.brain`` / ``pokeagent.explorer.edits``; this file is argparse + emit.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import pokeagent.brain as brain
from pokeagent.brain import fileops, text
from pokeagent.explorer import edits as edit_journal
from pokeagent.game.stores import store_path
from pokeagent.qdecode import BUTTONS
from pokeagent.qmodels import load_model

MAPS_DEFAULT = store_path("runs/maps.json").as_posix()  # POKEAGENT_GAME read once at import (a process runs one game)


def _emit(obj, args, text_out: str | None = None) -> None:
    if getattr(args, "text", False) and text_out is not None:
        print(text_out)
    else:
        print(json.dumps(obj, indent=1, sort_keys=True))


def _err(args, msg: str) -> int:
    if getattr(args, "text", False):
        print(f"error: {msg}")
    else:
        print(json.dumps({"error": msg}, indent=1, sort_keys=True))
    return 1


def _auto_int(text_value: str) -> int:
    try:
        return int(text_value, 0)
    except ValueError:
        return int(text_value)


def _parse_value(text_value: str | None):
    if text_value is None:
        return None
    for fn in (json.loads, ast.literal_eval):
        try:
            return fn(text_value)
        except (ValueError, SyntaxError):
            continue
    return text_value


def _cmd_maps(args) -> int:
    s = brain.maps_summary(fileops.effective_data(args.maps)[0])
    _emit(s, args, text.maps_text(s))
    return 0


def _cmd_map(args) -> int:
    try:
        v = brain.map_view(fileops.effective_data(args.maps)[0], args.map, args.overlay)
    except ValueError as e:
        return _err(args, str(e))
    _emit(v, args, text.map_text(v))
    return 0


def _cmd_tile(args) -> int:
    data, jpath = fileops.effective_data(args.maps)
    facts = brain.tile_facts(data, args.map, args.x, args.y,
                             edits=edit_journal.read_journal(jpath))
    _emit(facts, args, text.tile_text(facts))
    return 0


def _cmd_find(args) -> int:
    q = {"map": args.map, "kind": args.kind, "text": args.text, "item": args.item, "warps_to": args.warps_to}
    _emit(brain.find(fileops.effective_data(args.maps)[0], q), args)
    return 0


def _cmd_diff(args) -> int:
    try:
        out = brain.diff(fileops.load_maps(args.a), fileops.load_maps(args.b))
    except Exception as e:
        return _err(args, str(e))
    _emit(out, args, text.diff_text(out))
    return 0


def _cmd_lessons(args) -> int:
    try:
        _emit(brain.lessons(fileops.effective_data(args.maps)[0], args.kind), args)
    except ValueError as e:
        return _err(args, str(e))
    return 0


def _cmd_edit(args) -> int:
    try:
        mid, key, value = edit_journal.prepare(args.op, args.map, args.key, _parse_value(args.value))
    except ValueError as e:
        return _err(args, str(e))
    data, jpath = fileops.effective_data(args.maps)
    prior = edit_journal.prior_state(data, args.op, mid, key, value)
    rec = edit_journal.append_edit(jpath, op=args.op, map_id=mid, key=key, value=value,
                                   note=args.note, by=args.by, prior=prior)
    _emit({"ok": True, "edit": rec}, args,
          f"edit {rec['id']}: {args.op} map={mid} key={key} value={value}")
    return 0


def _cmd_edits(args) -> int:
    recs = edit_journal.read_journal(fileops.journal_for(args.maps))
    if args.map is not None:
        recs = [e for e in recs if str(e.get("map")) == str(args.map)]
    _emit({"count": len(recs), "edits": recs}, args, text.edits_text(recs))
    return 0


def _cmd_undo(args) -> int:
    jpath = fileops.journal_for(args.maps)
    journal = edit_journal.read_journal(jpath)
    target = next((e for e in reversed(journal) if e.get("id") == args.id), None)
    if target is None:
        return _err(args, f"no journal edit with id {args.id!r}")
    rec = edit_journal.append_edit(jpath, op="undo", map_id=target.get("map"), key=target.get("key"),
                                   value=args.id, note=args.note or f"undo {args.id}", by=args.by)
    _emit({"ok": True, "edit": rec}, args, f"edit {rec['id']}: undo {args.id}")
    return 0


def _cmd_apply(args) -> int:
    try:
        out = fileops.fold_journal(args.maps, dry_run=not args.backup)
    except (RuntimeError, FileNotFoundError) as e:
        return _err(args, str(e))
    _emit(out, args,
          f"folded {out.get('applied', 0)} edit(s) into {args.maps}; backup {out.get('backup')}"
          if out.get("ok") and not out.get("dry_run") else None)
    return 0


def _cmd_q(args) -> int:
    path = Path(args.model)
    if not path.is_file():
        return _err(args, f"model not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        schema = args.schema or raw.get("schema")
        n_actions = args.actions or raw.get("actions", 6)
        table = load_model(path, schema, n_actions)
        if args.patch_save or args.set is not None:
            if args.patch_save:  # ported from tools/qview.py --patch-save
                a_idx = BUTTONS.index("A")
                hits = [k for k in table if len(tuple(k)) >= 14 and tuple(k)[9] == 1 and tuple(k)[13] == 3]
                for k in hits:
                    table[k][a_idx] = min(table[k][a_idx], -2.0)
                backup = fileops.write_q_with_backup(path, table, schema, n_actions)
                _emit({"ok": True, "patched": len(hits), "backup": str(backup)}, args,
                      f"patched {len(hits)} SAVE-cursor states in {path}")
            else:
                obs_s, act_s, val_s = args.set
                obs = ast.literal_eval(obs_s)
                key = tuple(obs) if isinstance(obs, (list, tuple)) else obs
                if key not in table:
                    table[key] = [0.0] * n_actions
                idx = BUTTONS.index(act_s) if act_s.isalpha() else int(act_s)
                table[key][idx] = float(val_s)
                backup = fileops.write_q_with_backup(path, table, schema, n_actions)
                _emit({"ok": True, "set": {"obs": obs_s, "action": act_s, "value": float(val_s)},
                       "backup": str(backup)}, args, f"set {obs_s} {act_s} = {val_s}")
            return 0
        if args.obs is not None:
            _emit(brain.q_state(path, args.obs), args)
        else:
            _emit(brain.q_summary(path, top=args.top), args)
        return 0
    except Exception as e:
        return _err(args, str(e))


def _add_commands(bsub) -> None:
    """Attach every brain subcommand to a subparsers object."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--maps", default=MAPS_DEFAULT, metavar="PATH",
                        help="maps.json path (journal + agents dir beside it)")
    common.add_argument("--text", action="store_true", help="human-readable output (default: stable JSON)")

    bsub.add_parser("maps", parents=[common], help="per-map and global memory summary").set_defaults(func=_cmd_maps)

    m = bsub.add_parser("map", parents=[common], help="legend-glyph grid of one map")
    m.add_argument("map", type=_auto_int, help="map id (decimal or 0x..)")
    m.add_argument("--overlay", default=None,
                   help="per-tile overlay: visits | encounters | fails | outcomes:<goal>")
    m.set_defaults(func=_cmd_map)

    t = bsub.add_parser("tile", parents=[common], help="every fact about one tile, incl. journal edits")
    t.add_argument("map", type=_auto_int)
    t.add_argument("x", type=int)
    t.add_argument("y", type=int)
    t.set_defaults(func=_cmd_tile)

    f = bsub.add_parser("find", help="search memory: kind/text/item/warps_to")
    f.add_argument("--maps", default=MAPS_DEFAULT, metavar="PATH")
    f.add_argument("--map", type=_auto_int, default=None)
    f.add_argument("--kind", default=None, help="legend kind (wall, warp, trainer, ...)")
    f.add_argument("--text", default=None, help="substring of interaction text/choices")
    f.add_argument("--item", default=None, help="substring of item records")
    f.add_argument("--warps-to", type=_auto_int, default=None, dest="warps_to", help="warps leading to map N")
    f.set_defaults(func=_cmd_find)

    d = bsub.add_parser("diff", help="what changed between two maps.json snapshots")
    d.add_argument("a", metavar="A.json")
    d.add_argument("b", metavar="B.json")
    d.add_argument("--text", action="store_true")
    d.set_defaults(func=_cmd_diff)

    l = bsub.add_parser("lessons", parents=[common], help="summarised battle/damage/tile/beat tables")
    l.add_argument("kind", nargs="?", default="all", choices=["all", "battle", "damage", "tiles", "beats"])
    l.set_defaults(func=_cmd_lessons)

    e = bsub.add_parser("edit", parents=[common], help="append a surgery edit to the journal")
    e.add_argument("op", choices=edit_journal.DIRECT_EDITS)
    e.add_argument("map", type=_auto_int)
    e.add_argument("key", help="'x,y,DIR' for edges, 'x,y' for tiles/npcs")
    e.add_argument("--value", default=None, help="JSON value ([m,x,y] warp, [x,y] jump, bool, kind)")
    e.add_argument("--note", required=True)
    e.add_argument("--by", default="cli")
    e.set_defaults(func=_cmd_edit)

    ed = bsub.add_parser("edits", parents=[common], help="list journal entries")
    ed.add_argument("--map", type=_auto_int, default=None)
    ed.set_defaults(func=_cmd_edits)

    u = bsub.add_parser("undo", parents=[common], help="append an undo edit inverting journal id")
    u.add_argument("id")
    u.add_argument("--note", default=None)
    u.add_argument("--by", default="cli")
    u.set_defaults(func=_cmd_undo)

    ap = bsub.add_parser("apply", parents=[common], help="fold the journal into maps.json (--backup executes)")
    ap.add_argument("--backup", action="store_true",
                    help="actually fold: backup maps.json to <dir>/backups/ first; refuses while agents live")
    ap.set_defaults(func=_cmd_apply)

    q = bsub.add_parser("q", help="inspect or patch a tabular Q-model (backs up before any write)")
    q.add_argument("model", metavar="Q.json")
    q.add_argument("--obs", default=None, help="observation tuple, e.g. '(1,18,10,0,1,0,3,1,3,1,9,10,11,3)'")
    q.add_argument("--set", nargs=3, metavar=("OBS", "ACTION", "VALUE"), default=None,
                   help="set Q(obs, action) = value, then save")
    q.add_argument("--patch-save", action="store_true",
                   help="set A <= -2 at every START-menu state whose cursor sits on SAVE")
    q.add_argument("--top", type=int, default=10, help="top states to show in the summary")
    q.add_argument("--schema", default=None)
    q.add_argument("--actions", type=int, default=None)
    q.add_argument("--text", action="store_true")
    q.set_defaults(func=_cmd_q)


def register(sub) -> None:
    """Attach the ``brain`` subcommand tree to the main CLI's subparsers."""
    bp = sub.add_parser("brain", help="inspect the map memory and perform journaled surgery (JSON out)")
    _add_commands(bp.add_subparsers(dest="brain_command", required=True))


def main(argv: list[str] | None = None) -> int:
    """Standalone entry for tools/brain.py: same commands, no 'brain' prefix."""
    parser = argparse.ArgumentParser(prog="pokeagent brain")
    _add_commands(parser.add_subparsers(dest="brain_command", required=True))
    args = parser.parse_args(argv)
    return args.func(args)
