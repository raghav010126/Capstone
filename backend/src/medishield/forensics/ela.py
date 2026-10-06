"""Error Level Analysis (ELA) for JPEG manipulation.

A JPEG that is re-saved loses a little more detail everywhere, but a region pasted in or redrawn after the last save has
a different compression history from the rest of the page, so re-compressing the file at a fixed quality and looking at
what changes exposes it. Text and edges always change more than flat areas, so the error is normalised by local edge
energy before blocks are compared; a block is suspicious when its normalised error is a robust outlier among the blocks
that actually contain content.

Measured weak on flat synthetic documents (see docs/eval_results/forensics.json), so it is ADVISORY: it feeds the reviewer-facing heatmap and a warning, never a decision. Only JPEG files carry compression history. PNG and other lossless formats return ``applicable=False`` (see
``typography`` for those).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

RESAVE_QUALITY = 90
BLOCK = 16
MIN_CONTENT_GRAD = 6.0        # blocks flatter than this carry no evidence either way
Z_THRESHOLD = 6.0
MIN_CLUSTER_BLOCKS = 3


@dataclass
class ElaResult:
    applicable: bool
    score: float = 0.0                       # strongest cluster's mean robust z (0 when nothing stands out)
    flagged: bool = False
    regions: list[tuple[int, int, int, int]] = field(default_factory=list)      # x0, y0, x1, y1 in image pixels
    heatmap_png: bytes | None = None
    detail: str = ""


def is_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


def _block_mean(a: np.ndarray, b: int = BLOCK) -> np.ndarray:
    h, w = (a.shape[0] // b) * b, (a.shape[1] // b) * b
    return a[:h, :w].reshape(h // b, b, w // b, b).mean(axis=(1, 3))


def analyse(data: bytes, with_heatmap: bool = True) -> ElaResult:
    if not is_jpeg(data):
        return ElaResult(applicable=False, detail="not a JPEG: no compression history to analyse")
    rgb = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=RESAVE_QUALITY)
    again = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    a = np.asarray(rgb, dtype=np.float32)
    ela = np.abs(a - np.asarray(again, dtype=np.float32)).mean(axis=2)
    gray = cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    grad = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))

    heat = None
    if with_heatmap:
        norm = np.clip(ela * (255.0 / max(ela.max(), 1e-6)) * 4, 0, 255).astype(np.uint8)
        col = cv2.applyColorMap(norm, cv2.COLORMAP_INFERNO)
        out = io.BytesIO()
        Image.fromarray(cv2.cvtColor(col, cv2.COLOR_BGR2RGB)).save(out, format="PNG")
        heat = out.getvalue()

    e, g = _block_mean(ela), _block_mean(grad)
    content = g > MIN_CONTENT_GRAD
    if content.sum() < 30:
        return ElaResult(applicable=True, heatmap_png=heat, detail="too little content to judge")
    ratio = np.log((e + 0.05) / (g + 10.0))                   # error relative to how much edge the block contains
    vals = ratio[content]
    med = np.median(vals)
    mad = max(float(np.median(np.abs(vals - med))) * 1.4826, 0.15)
    z = np.where(content, (ratio - med) / mad, 0.0)
    # two-sided: pasted material can show LOWER error (it was compressed harder before) as well as higher
    hot = ((np.abs(z) > Z_THRESHOLD) & content).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hot, connectivity=8)
    regions, scores = [], []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= MIN_CLUSTER_BLOCKS:
            regions.append((int(x * BLOCK), int(y * BLOCK), int((x + w) * BLOCK), int((y + h) * BLOCK)))
            scores.append(float(np.abs(z[labels == i]).mean()))
    score = max(scores, default=0.0)

    return ElaResult(applicable=True, score=round(score, 2), flagged=bool(regions), regions=regions, heatmap_png=heat,
                     detail=(f"{len(regions)} region(s) with a different compression history (z={score:.1f})" if regions
                             else "uniform compression history"))
