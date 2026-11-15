"""View a relabelled Dataset as semantic classes the split/template/net code can use.

Every row's key collapses to ``("sprite", -1, <semantic index>)`` so tiles and
sprites share ONE class table and a class means the same thing in every tileset.
``images``, ``coarse``, ``area``, ``weight``, ``w``, ``h`` and ``ids`` are kept, so
the area split and the image-id leak check work unchanged.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from pokeagent.vision_model.data import Dataset
from pokeagent.vision_model.semantic import SEMANTIC


def as_semantic(ds: Dataset) -> Dataset:
    """The same dataset with ``label`` replaced by the semantic class index."""
    if ds.semantic is None:
        raise ValueError("no semantic labels: run tools/vision_relabel.py first")
    return dataclasses.replace(
        ds, label=ds.semantic.astype(np.int32),
        kind=np.zeros(len(ds.label), np.int8), bank=np.full(len(ds.label), -1, np.int32))


def class_name(key: tuple) -> str:
    """The semantic name of a ``("sprite", -1, idx)`` row key."""
    return SEMANTIC[key[2]]
