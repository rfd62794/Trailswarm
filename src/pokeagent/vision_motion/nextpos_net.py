"""Optional torch MLP for next position; ``import pokeagent.vision_motion.nextpos_net``
works without torch - every torch import lives inside a function body."""
from __future__ import annotations

from pokeagent.vision_motion.nextpos import CLASSES, encode


def build(seed: int = 0):
    """Two hidden layers of 32 over ``encode(ctx)`` (28 in) -> 5 classes."""
    import torch
    torch.manual_seed(seed)
    return torch.nn.Sequential(
        torch.nn.Linear(28, 32), torch.nn.ReLU(),
        torch.nn.Linear(32, 32), torch.nn.ReLU(),
        torch.nn.Linear(32, len(CLASSES)))


def train_net(steps, seed: int = 0, epochs: int = 60, lr: float = 0.01,
              max_seconds: float = 60.0):
    """Fit the MLP on ``(ctx, target)`` steps (None targets skipped); CPU, fixed seed."""
    import time

    import numpy as np
    import torch

    pairs = [(encode(c), CLASSES.index(t)) for c, t in steps if t is not None]
    net = build(seed)
    if not pairs:
        return net
    x = torch.tensor(np.stack([p[0] for p in pairs]))
    y = torch.tensor([p[1] for p in pairs])
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    lossf = torch.nn.CrossEntropyLoss()
    t0 = time.perf_counter()
    for _ in range(epochs):
        if time.perf_counter() - t0 > max_seconds:
            break
        opt.zero_grad()
        lossf(net(x), y).backward()
        opt.step()
    net.eval()
    return net


def predict(net, ctx) -> str:
    import numpy as np
    import torch

    with torch.no_grad():
        logits = net(torch.tensor(np.asarray(encode(ctx))))
    return CLASSES[int(logits.argmax())]
