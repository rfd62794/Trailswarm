"""The ``brain_*`` MCP tools: read the learned world model; edits go to the journal only.

Mixin for ``mcp_server._Tools`` - every method is a thin wrapper over ``pokeagent.brain``
and ``pokeagent.explorer.edits``. maps.json is never written here: ``brain_edit`` /
``brain_undo`` append to ``memory_edits.jsonl`` beside it, and agents fold the journal on
load/save or via the ``reload_edits`` control command.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pokeagent.brain as brain
from pokeagent.brain import fileops
from pokeagent.explorer import edits as edit_journal


class BrainTools:
    """brain_* tool implementations; expects ``self.maps_path`` from the host class."""

    def _brain_data(self) -> dict[str, Any]:
        return fileops.effective_data(self.maps_path)[0]

    def brain_maps(self) -> dict[str, Any]:
        """Summarise the whole map memory: per-map visited/blocked/warps/interactions/encounters plus global tables."""
        return brain.maps_summary(self._brain_data())

    def brain_map(self, map_id: int, overlay: str | None = None) -> dict[str, Any]:
        """Legend-glyph grid of one map, optionally with a per-tile overlay (visits|encounters|fails|outcomes:<goal>)."""
        return brain.map_view(self._brain_data(), map_id, overlay)

    def brain_tile(self, map_id: int, x: int, y: int) -> dict[str, Any]:
        """Every fact the model holds about one tile, including journal edits that touch it."""
        data, jpath = fileops.effective_data(self.maps_path)
        return brain.tile_facts(data, map_id, x, y, edits=edit_journal.read_journal(jpath))

    def brain_find(
        self, map_id: int | None = None, kind: str | None = None, text: str | None = None,
        item: str | None = None, warps_to: int | None = None,
    ) -> dict[str, Any]:
        """Search map memory by legend kind, interaction text, item name, or warp destination."""
        return brain.find(self._brain_data(),
                          {"map": map_id, "kind": kind, "text": text, "item": item, "warps_to": warps_to})

    def brain_diff(self, a_path: str, b_path: str) -> dict[str, Any]:
        """Structural diff between two maps.json snapshot files."""
        return brain.diff(fileops.load_maps(a_path), fileops.load_maps(b_path))

    def brain_lessons(self, kind: str = "all") -> dict[str, Any]:
        """Summarised battle, damage, tile-type and beat tables (kind: all|battle|damage|tiles|beats)."""
        return brain.lessons(self._brain_data(), kind)

    def _journal_append(self, op: str, map_id, key, value, note: str, by: str) -> dict[str, Any]:
        jpath = fileops.journal_for(self.maps_path)
        if op == "undo":  # undo records carry the target's id in value; prepare() rejects them
            rec = edit_journal.append_edit(jpath, op="undo", map_id=map_id, key=key,
                                           value=value, note=note, by=by)
            return {"ok": True, "edit": rec}
        try:
            mid, k, v = edit_journal.prepare(op, map_id, key, value)
        except ValueError as e:
            return {"error": str(e)}
        prior = edit_journal.prior_state(self._brain_data(), op, mid, k, v)
        rec = edit_journal.append_edit(jpath, op=op, map_id=mid, key=k, value=v,
                                       note=note, by=by, prior=prior)
        return {"ok": True, "edit": rec}

    def brain_edit(
        self, op: str, map_id: int, key: str, note: str,
        value: Any = None, by: str = "mcp",
    ) -> dict[str, Any]:
        """Append a surgery edit to the journal (wall_add/remove, warp_add/remove, jump_add/remove,
        interaction_clear, npc_trainer/forget, tile_kind, visited_clear). Journal only - maps.json is
        never written here; agents pick it up via reload_edits or on next load/save."""
        if op not in edit_journal.DIRECT_EDITS:
            return {"error": f"unknown op {op!r}; use {sorted(edit_journal.DIRECT_EDITS)}"}
        return self._journal_append(op, map_id, key, value, note, by)

    def brain_undo(self, edit_id: str, note: str | None = None, by: str = "mcp") -> dict[str, Any]:
        """Append an undo edit inverting the journal entry with id `edit_id`."""
        jpath = fileops.journal_for(self.maps_path)
        journal = edit_journal.read_journal(jpath)
        target = next((e for e in reversed(journal) if e.get("id") == edit_id), None)
        if target is None:
            return {"error": f"no journal edit with id {edit_id!r}"}
        return self._journal_append("undo", target.get("map"), target.get("key"),
                                    edit_id, note or f"undo {edit_id}", by)
