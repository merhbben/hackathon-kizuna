"""Optional deep-learning segmentation of farm plans (PyTorch U-Net).

Status: architecture + training/inference code are provided, but NO trained
weights ship with TuniNō because no labelled corpus of Tunisian farm
plans is publicly available. Until `AGRO_SEGMENTATION_WEIGHTS` points to a
trained checkpoint, the API reports `available=False` and the classical
OpenCV pipeline (plan_reader.detect) is used.

Classes: 0 background, 1 field, 2 path, 3 water, 4 building.
Training data format: directory with images/*.png and masks/*.png (uint8 class ids).
Install the optional extra: pip install -r requirements-ml.txt
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.core.config import get_settings

CLASSES = ["background", "field", "path", "water", "building"]


def torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def status() -> dict:
    w = get_settings().segmentation_weights
    return {"torch_installed": torch_available(), "weights_configured": bool(w and Path(w).exists()),
            "available": torch_available() and bool(w and Path(w).exists()), "classes": CLASSES}


def build_unet(n_classes: int = len(CLASSES)):
    import torch
    from torch import nn

    def block(i, o):
        return nn.Sequential(nn.Conv2d(i, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True),
                             nn.Conv2d(o, o, 3, padding=1), nn.BatchNorm2d(o), nn.ReLU(inplace=True))

    class UNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.e1, self.e2, self.e3, self.e4 = block(3, 32), block(32, 64), block(64, 128), block(128, 256)
            self.pool = nn.MaxPool2d(2)
            self.u3, self.d3 = nn.ConvTranspose2d(256, 128, 2, 2), block(256, 128)
            self.u2, self.d2 = nn.ConvTranspose2d(128, 64, 2, 2), block(128, 64)
            self.u1, self.d1 = nn.ConvTranspose2d(64, 32, 2, 2), block(64, 32)
            self.out = nn.Conv2d(32, n_classes, 1)

        def forward(self, x):
            e1 = self.e1(x)
            e2 = self.e2(self.pool(e1))
            e3 = self.e3(self.pool(e2))
            e4 = self.e4(self.pool(e3))
            d3 = self.d3(torch.cat([self.u3(e4), e3], 1))
            d2 = self.d2(torch.cat([self.u2(d3), e2], 1))
            d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
            return self.out(d1)

    return UNet()


def predict(img_bgr: np.ndarray) -> np.ndarray:
    """Return a class-id mask (H, W). Raises RuntimeError if the model is unavailable."""
    st = status()
    if not st["available"]:
        raise RuntimeError("segmentation_model_unavailable")
    import cv2
    import torch
    model = build_unet()
    model.load_state_dict(torch.load(get_settings().segmentation_weights, map_location="cpu"))
    model.eval()
    h, w = img_bgr.shape[:2]
    side = 512
    x = cv2.resize(img_bgr, (side, side))[:, :, ::-1].astype(np.float32) / 255.0
    t = torch.from_numpy(x.transpose(2, 0, 1).copy())[None]
    with torch.no_grad():
        m = model(t).argmax(1)[0].numpy().astype(np.uint8)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)


def train(data_dir: str, epochs: int = 40, out: str = "data/models/plan_unet.pt") -> dict:
    """Train on a labelled dataset, report per-class IoU on a 20 % hold-out split."""
    import cv2
    import torch
    from torch import nn
    imgs = sorted(Path(data_dir, "images").glob("*.png"))
    if len(imgs) < 10:
        raise ValueError("need at least 10 labelled plans")
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(imgs))
    n_val = max(2, len(imgs) // 5)
    val, tr = idx[:n_val], idx[n_val:]

    def load(i):
        im = cv2.resize(cv2.imread(str(imgs[i])), (512, 512))[:, :, ::-1].astype(np.float32) / 255
        mk = cv2.resize(cv2.imread(str(Path(data_dir, "masks", imgs[i].name)), 0), (512, 512),
                        interpolation=cv2.INTER_NEAREST)
        return torch.from_numpy(im.transpose(2, 0, 1).copy()), torch.from_numpy(mk.astype(np.int64))

    model = build_unet()
    opt = torch.optim.Adam(model.parameters(), 1e-3)
    loss_f = nn.CrossEntropyLoss()
    for _ in range(epochs):
        model.train()
        for i in rng.permutation(tr):
            x, y = load(i)
            opt.zero_grad()
            loss = loss_f(model(x[None]), y[None])
            loss.backward()
            opt.step()
    model.eval()
    inter = np.zeros(len(CLASSES))
    union = np.zeros(len(CLASSES))
    with torch.no_grad():
        for i in val:
            x, y = load(i)
            p = model(x[None]).argmax(1)[0].numpy()
            y = y.numpy()
            for k in range(len(CLASSES)):
                inter[k] += np.logical_and(p == k, y == k).sum()
                union[k] += np.logical_or(p == k, y == k).sum()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out)
    return {"weights": out, "iou": {c: float(inter[k] / union[k]) if union[k] else None for k, c in enumerate(CLASSES)},
            "n_train": len(tr), "n_val": len(val)}
