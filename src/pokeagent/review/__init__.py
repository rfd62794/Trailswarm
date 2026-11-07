"""Operator review tools: loading, event extraction, loop detection, rule summary, rendering.

Shared by ``pokeagent review run | swarm | replay | diff`` (see ``pokeagent.cli_review``).
Everything here is read-only over ``runs/``; nothing in this package starts an emulator.
"""
