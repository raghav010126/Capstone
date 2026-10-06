"""Confidence calibration: does a confidence of 0.8 mean the decision is right 80% of the time?

* ``reliability`` - equal-width bins of confidence vs observed accuracy (the reliability diagram).
* ``ece`` / ``brier`` - expected calibration error (bin-weighted gap) and the Brier score (mean squared error of the
  confidence as a probability of being correct).
* ``Isotonic`` - monotone calibration map fitted with pool-adjacent-violators; fitted on the dev split and applied
  unchanged to held-out / seed-7 data (never refitted on them).
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


def reliability(conf, correct, bins: int = 10) -> list[dict]:
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in itertools.pairwise(edges):
        m = (conf >= lo) & ((conf < hi) if hi < 1 else (conf <= hi))
        if m.any():
            out.append({"lo": round(float(lo), 2), "hi": round(float(hi), 2), "n": int(m.sum()),
                        "mean_conf": round(float(conf[m].mean()), 4), "accuracy": round(float(correct[m].mean()), 4)})
    return out


def ece(conf, correct, bins: int = 10) -> float:
    n = len(conf)
    return round(sum(b["n"] / n * abs(b["accuracy"] - b["mean_conf"]) for b in reliability(conf, correct, bins)), 4) if n else 0.0


def brier(conf, correct) -> float:
    conf, correct = np.asarray(conf, float), np.asarray(correct, float)
    return round(float(((conf - correct) ** 2).mean()), 4) if len(conf) else 0.0


@dataclass
class Isotonic:
    """Non-decreasing step function ``x -> calibrated probability``."""
    xs: list[float]
    ys: list[float]

    @classmethod
    def fit(cls, conf, correct) -> Isotonic:
        order = np.argsort(conf, kind="stable")
        x = np.asarray(conf, float)[order]
        y = np.asarray(correct, float)[order]
        # pool adjacent violators: merge neighbouring blocks until the block means are non-decreasing
        blocks = [[float(v), 1.0, float(xv), float(xv)] for v, xv in zip(y, x, strict=True)]      # mean, weight, x_min, x_max
        out: list[list[float]] = []
        for b in blocks:
            out.append(b)
            while len(out) > 1 and out[-2][0] > out[-1][0]:
                m2, m1 = out.pop(), out.pop()
                w = m1[1] + m2[1]
                out.append([(m1[0] * m1[1] + m2[0] * m2[1]) / w, w, m1[2], m2[3]])
        return cls(xs=[(b[2] + b[3]) / 2 for b in out], ys=[b[0] for b in out])

    def __call__(self, conf) -> np.ndarray:
        return np.interp(np.asarray(conf, float), self.xs, self.ys)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"xs": self.xs, "ys": self.ys}))

    @classmethod
    def load(cls, path: Path) -> Isotonic | None:
        return cls(**json.loads(path.read_text())) if path.exists() else None


def summary(conf, correct, calibrator: Isotonic | None) -> dict:
    out = {"n": len(conf), "accuracy": round(float(np.mean(correct)), 4) if len(conf) else None,
           "raw": {"ece": ece(conf, correct), "brier": brier(conf, correct), "bins": reliability(conf, correct)}}
    if calibrator is not None and len(conf):
        cal = calibrator(conf)
        out["calibrated"] = {"ece": ece(cal, correct), "brier": brier(cal, correct), "bins": reliability(cal, correct)}
    return out
