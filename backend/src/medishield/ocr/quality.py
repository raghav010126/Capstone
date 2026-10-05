"""Deterministic image-quality evidence: sharpness (variance of the Laplacian), blankness, OCR confidence."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from medishield.schemas import OcrLine, QualityMetrics

NORM_WIDTH = 1200          # measure sharpness at a fixed scale so thresholds don't depend on resolution
BLUR_THRESHOLD = 150.0     # conventional variance-of-Laplacian cut-off (not tuned on our labels)
SHARP_REFERENCE = 600.0    # at/above this sharpness contributes fully to the quality score


def sharpness(path: str | Path) -> tuple[float, int, int, float]:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"unreadable image: {path}")
    h, w = img.shape
    scaled = cv2.resize(img, (NORM_WIDTH, max(1, round(h * NORM_WIDTH / w))), interpolation=cv2.INTER_AREA)
    lap = float(cv2.Laplacian(scaled, cv2.CV_64F).var())
    ink = float((scaled < 200).mean())          # share of non-background pixels
    return lap, w, h, ink


def assess(path: str | Path, lines: list[OcrLine]) -> QualityMetrics:
    lap, w, h, ink = sharpness(path)
    blank = ink < 0.002 or not lines
    ocr_mean = float(np.mean([ln.score for ln in lines])) if lines else 0.0
    blur = lap < BLUR_THRESHOLD
    sharp_part = min(1.0, lap / SHARP_REFERENCE)
    quality = 0.0 if blank else round(0.6 * sharp_part + 0.4 * ocr_mean, 3)
    if blur:
        quality = min(quality, 0.5)
    return QualityMetrics(width=w, height=h, sharpness=round(lap, 1), blank=blank, blur_suspected=blur,
                          ocr_mean_score=round(ocr_mean, 4), ocr_lines=len(lines), quality_score=quality)
