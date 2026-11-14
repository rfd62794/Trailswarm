"""Optional small CNN for the location model; ``import ...location_net`` works without
torch - every torch import lives inside a function body. CPU only, seeded, no pretrained
weights; the only augmentation is a +-10% brightness jitter (never position)."""
from __future__ import annotations

import numpy as np


def build(n_areas: int, cell_out: int = 2, seed: int = 0):
    """Three 3x3 conv blocks (16, 32, 32; ReLU + 2x2 pool), global average pool, then an
    area-class head and a ``cell_out``-wide cell regression head."""
    import torch

    torch.manual_seed(seed)

    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = torch.nn.Sequential(
                torch.nn.Conv2d(1, 16, 3, padding=1), torch.nn.ReLU(),
                torch.nn.MaxPool2d(2),
                torch.nn.Conv2d(16, 32, 3, padding=1), torch.nn.ReLU(),
                torch.nn.MaxPool2d(2),
                torch.nn.Conv2d(32, 32, 3, padding=1), torch.nn.ReLU(),
                torch.nn.MaxPool2d(2))
            self.area = torch.nn.Linear(32, n_areas)
            self.cell = torch.nn.Linear(32, cell_out)

        def forward(self, x):
            z = self.conv(x).mean(dim=(2, 3))
            return self.area(z), self.cell(z)

    return Net()


def param_count(net) -> int:
    return int(sum(p.numel() for p in net.parameters()))


def train_net(images, area_idx, cells, n_areas: int, seed: int = 0, epochs: int = 30,
              lr: float = 0.005, batch: int = 64, max_seconds: float = 300.0,
              cell_out: int = 2):
    """Fit the CNN; returns the net with ``cell_scale`` attached for de-normalisation."""
    import time

    import torch

    torch.manual_seed(seed)
    net = build(n_areas, cell_out, seed)
    x = torch.tensor(np.asarray(images, dtype=np.float32)).unsqueeze(1) / 255.0
    a = torch.tensor(np.asarray(area_idx))
    c = torch.tensor(np.asarray(cells, dtype=np.float32)[:, :cell_out])
    scale = c.max(dim=0).values.clamp(min=1.0)
    cn = c / scale
    gen = torch.Generator().manual_seed(seed)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    ce, mse = torch.nn.CrossEntropyLoss(), torch.nn.MSELoss()
    t0 = time.perf_counter()
    for _ in range(epochs):
        for i in range(0, len(x), batch):
            if time.perf_counter() - t0 > max_seconds:
                net.cell_scale = scale
                net.eval()
                return net
            idx = torch.randperm(len(x), generator=gen)[:batch]
            jit = 1.0 + 0.2 * (torch.rand(len(idx), 1, 1, 1, generator=gen) - 0.5)
            logits, cell = net((x[idx] * jit).clamp(0, 1))
            loss = ce(logits, a[idx]) + mse(cell, cn[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
    net.cell_scale = scale
    net.eval()
    return net


def predict(net, images, batch: int = 256):
    """(area index array, de-normalised cell array)."""
    import torch

    x = torch.tensor(np.asarray(images, dtype=np.float32)).unsqueeze(1) / 255.0
    outs, cells = [], []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            logits, cell = net(x[i:i + batch])
            outs.append(logits.argmax(dim=1))
            cells.append(cell * net.cell_scale)
    return torch.cat(outs).numpy(), torch.cat(cells).numpy()


def bench_ms(net, image, runs: int = 200, warmup: int = 10) -> float:
    """Median milliseconds per frame over ``runs`` inferences after ``warmup`` warm-ups."""
    import time

    import torch

    x = torch.tensor(np.asarray(image, dtype=np.float32)).unsqueeze(0).unsqueeze(0) / 255.0
    with torch.no_grad():
        for _ in range(warmup):
            net(x)
        ts = []
        for _ in range(runs):
            t0 = time.perf_counter()
            net(x)
            ts.append((time.perf_counter() - t0) * 1000.0)
    return float(np.median(ts))
