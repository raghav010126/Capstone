"""RapidOCR (PP-OCR on onnxruntime) wrapper with an on-disk result cache keyed by image hash."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from functools import lru_cache
from pathlib import Path

from medishield.config import get_settings
from medishield.schemas import OcrLine

_lock = threading.Lock()          # one onnx session, serialised (it is not documented as thread-safe)
OCR_VERSION = "rapidocr-ppocrv6-1"


@lru_cache
def _engine(lang: str = "default"):
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    if lang == "devanagari":
        return RapidOCR(params={"Rec.lang_type": LangRec.DEVANAGARI, "Rec.model_type": ModelType.MOBILE,
                                "Rec.ocr_version": OCRVersion.PPOCRV5})
    return RapidOCR()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


DEVANAGARI = re.compile(r"[\u0900-\u097F]")
RETRY_BELOW = 0.95            # a first pass this confident is not worth a second look


def _lines(res) -> list[OcrLine]:
    out: list[OcrLine] = []
    if res.txts is not None:
        for i, (txt, score, quad) in enumerate(zip(res.txts, res.scores, res.boxes, strict=True)):
            xs, ys = [float(p[0]) for p in quad], [float(p[1]) for p in quad]
            out.append(OcrLine(id=i, text=str(txt), score=round(float(score), 4),
                               box=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
    return out


def _mean(lines: list[OcrLine]) -> float:
    return sum(ln.score for ln in lines) / len(lines) if lines else 0.0


def run_ocr(path: str | Path) -> list[OcrLine]:
    """OCR one page. The default model reads English and Spanish (including accents). When it is unsure, the page is read
    again with the Devanagari model and that reading is used only if it actually found Devanagari text and is at least as
    confident - so English pages (and everything cached from them) are never affected."""
    digest = file_sha256(path)
    cache = get_settings().cache_dir / "ocr" / f"{digest}-{OCR_VERSION}.json"
    if cache.exists():
        return [OcrLine(**x) for x in json.loads(cache.read_text())]
    with _lock:
        lines = _lines(_engine()(str(path)))
        if _mean(lines) < RETRY_BELOW:
            alt = _lines(_engine("devanagari")(str(path)))
            if any(DEVANAGARI.search(ln.text) for ln in alt) and _mean(alt) >= _mean(lines) - 0.02:
                lines = alt
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([ln.model_dump() for ln in lines]))
    return lines
