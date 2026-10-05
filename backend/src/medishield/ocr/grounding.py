"""Ground each LLM-extracted value in the OCR text of the page.

A value is *grounded* when it (or one of its printed renderings, e.g. ``$1,250.00`` for 1250.0 or
``12/15/2025`` for 2025-12-15) is found on an OCR line. Short codes need an exact token match; longer
strings use fuzzy partial matching. Grounded values carry the OCR box, which the UI uses to highlight the
field on the page image. Ungrounded values are possible hallucinations, so they lower confidence.
"""

from __future__ import annotations

import re
from datetime import datetime

from rapidfuzz import fuzz

from medishield.schemas import Box, OcrLine

FUZZY_MIN = 90.0
_NORM = re.compile(r"[^a-z0-9$.,/\-]+")


def norm(s: str) -> str:
    return _NORM.sub(" ", s.lower()).strip()


def _tokens(s: str) -> set[str]:
    return {t.strip(".,") for t in norm(s).split()} | set(re.findall(r"[a-z0-9]+", s.lower()))


def renderings(value: object) -> list[str]:
    """Ways a typed value can be printed on a form."""
    if value is None or value == "":
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        v = float(value)
        return [f"${v:,.2f}", f"{v:,.2f}", f"{v:.2f}"]
    s = str(value).strip()
    out = [s]
    for fmt in ("%Y-%m-%d",):
        try:
            d = datetime.strptime(s, fmt)
            out = [d.strftime("%m/%d/%Y"), d.strftime("%B %d, %Y"), d.strftime("%b %d, %Y"),
                   d.strftime("%d %b %Y").upper(), d.strftime("%m-%d-%Y"), d.strftime("%m/%y"), s]
        except ValueError:
            pass
    if s.upper().startswith("NPI-"):
        out.append(s[4:])
    return out


def _is_code(s: str) -> bool:
    return len(s) <= 8 and bool(re.search(r"\d", s)) and " " not in s


def match_line(value: object, lines: list[OcrLine]) -> tuple[bool, Box | None, float]:
    best: tuple[float, Box | None] = (0.0, None)
    for r in renderings(value):
        nr = norm(r)
        if not nr:
            continue
        for ln in lines:
            if _is_code(r):
                score = 100.0 if (nr in _tokens(ln.text) or r.lower() in ln.text.lower()) else 0.0
            elif len(nr) < 4:
                score = 100.0 if nr in _tokens(ln.text) else 0.0
            else:
                score = fuzz.partial_ratio(nr, norm(ln.text)) if len(norm(ln.text)) >= len(nr) * 0.6 else 0.0
            if score > best[0]:
                best = (score, ln.box)
                if score == 100.0:
                    return True, ln.box, 100.0
    return best[0] >= FUZZY_MIN, (best[1] if best[0] >= FUZZY_MIN else None), round(best[0], 1)
