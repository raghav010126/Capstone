"""Typography consistency: is every date on the card set in the same size?

A value that was covered and retyped is rarely set in exactly the original size. The OCR boxes locate each date-like
value; the glyphs inside are then measured directly in the pixels. The deciding measure is the ink's width per character:
height proved unreliable (crops are clipped by neighbouring text and dark bands) and is reported only. A date whose width
per character deviates from the card's *other* dates by more than the tolerance is reported. Colour differences are common
by design (a red date of birth), so colour is reported but never decides.

Works on any file type, so it covers PNG scans that have no compression history for ELA to use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from medishield.schemas import OcrLine

DATE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
TOLERANCE = 0.12             # relative deviation (height or width per character) from the other dates
MIN_DATES = 2


@dataclass
class TypographyResult:
    flagged: bool = False
    suspects: list[dict] = field(default_factory=list)
    detail: str = ""


def measure(gray: np.ndarray, rgb: np.ndarray, box: tuple[int, int, int, int], n_chars: int) -> dict | None:
    """Ink height, width per character and ink colour of one text line."""
    x0, y0, x1, y1 = box
    pad = 3
    sub = gray[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
    if sub.size == 0:
        return None
    bg = np.median(sub)
    ink = np.abs(sub - bg) > 70
    rows, cols = np.where(ink.any(axis=1))[0], np.where(ink.any(axis=0))[0]
    if len(rows) < 4 or len(cols) < 8:
        return None
    colour = rgb[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad][ink].mean(axis=0)
    return {"height": float(rows[-1] - rows[0] + 1), "char_width": float(cols[-1] - cols[0] + 1) / n_chars,
            "ink": tuple(int(v) for v in colour)}


def analyse(path: str, lines: list[OcrLine]) -> TypographyResult:
    dates = [ln for ln in lines if DATE.fullmatch(ln.text.strip())]
    if len(dates) < MIN_DATES:
        return TypographyResult(detail=f"{len(dates)} date value(s): nothing to compare")
    rgb = np.asarray(Image.open(path).convert("RGB"))
    gray = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
    ms = [(ln, measure(gray, rgb, ln.box, len(ln.text.strip()))) for ln in dates]
    ms = [(ln, m) for ln, m in ms if m]
    if len(ms) < MIN_DATES:
        return TypographyResult(detail="dates could not be measured")
    suspects = []
    for i, (ln, m) in enumerate(ms):
        others = [o for j, (_, o) in enumerate(ms) if j != i]
        dh = m["height"] / np.median([o["height"] for o in others]) - 1            # reported, not used: crops clip
        dw = m["char_width"] / np.median([o["char_width"] for o in others]) - 1    # stable: decides
        if abs(dw) > TOLERANCE:
            suspects.append({"text": ln.text, "box": ln.box, "height_vs_other_dates": round(float(dh), 2),
                             "width_vs_other_dates": round(float(dw), 2), "ink": m["ink"]})
    return TypographyResult(flagged=bool(suspects), suspects=suspects,
                            detail=(f"{len(suspects)} date value(s) set in a different size than the card's other dates"
                                    if suspects else "all dates share one type size"))
