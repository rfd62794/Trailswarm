"""Panel 4 and the architecture table: read straight from a loaded TinyNet. Torch is
imported inside the functions only."""
from __future__ import annotations

import numpy as np
from PIL import Image

from pokeagent.vision_model.view_draw import banner, hstrip, up, vstack


def _norm(a: np.ndarray) -> np.ndarray:
    lo, hi = float(a.min()), float(a.max())
    return ((a - lo) / (hi - lo + 1e-9) * 255).astype(np.uint8)


def conv1_filters(model, k: int = 14, cols: int = 8) -> Image.Image:
    """The first conv layer's 3x3 RGB filters, each min-max normalised, upscaled k times."""
    w = model.features[0].weight.detach().cpu().numpy()          # (out, 3, 3, 3)
    tiles = [up(_norm(f.transpose(1, 2, 0)), k) for f in w]
    rows = [hstrip(tiles[i:i + cols], 3) for i in range(0, len(tiles), cols)]
    return vstack([banner(cols * (3 * k + 3), f"conv1: {len(w)} filters, 3x3 RGB, each stretched to full range")] + rows, 3)


def activation_maps(model, crops, k: int = 10) -> Image.Image:
    """Per crop: the crop, then the channel-mean activation after each conv+ReLU stage
    (16x16, 8x8 and 4x4 maps), each stretched to full range."""
    import torch

    rows = []
    with torch.no_grad():
        for c in crops:
            pad = np.zeros((16, 16, 3), np.uint8)
            pad[:c.shape[0], :c.shape[1]] = c
            x = torch.from_numpy(pad).float().div(255).permute(2, 0, 1)[None]
            maps = [up(pad, k)]
            for end in (2, 5, 8):
                m = model.features[:end](x)[0].mean(0).numpy()
                maps.append(up(_norm(m), 16 * k // m.shape[0]))
            rows.append(hstrip(maps, 4))
    return vstack([banner(700, "crop | after conv1 | after conv2 | after conv3 (mean over channels)")] + rows, 4)


def architecture(model) -> list:
    """[(layer, output shape, params)] from a real forward pass on one 16x16 crop."""
    import torch

    rows, hooks = [], []
    for name, mod in model.named_modules():
        if name and not list(mod.children()):
            hooks.append(mod.register_forward_hook(
                lambda m, i, o, n=name: rows.append(
                    (f"{n} {m.__class__.__name__}", tuple(o.shape[1:]),
                     sum(p.numel() for p in m.parameters())))))
    with torch.no_grad():
        model.eval()(torch.zeros(1, 3, 16, 16))
    for h in hooks:
        h.remove()
    rows.insert(len(rows) - 2, ("(global average pool over H,W)", (rows[-3][1][0],), 0))
    return rows
