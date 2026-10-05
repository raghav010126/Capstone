"""RapidOCR (PP-OCR on onnxruntime) wrapper with an on-disk result cache keyed by image hash."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from functools import lru_cache
from pathlib import Path

from medishield.config import get_settings
from medishield.schemas import OcrLine

_lock = threading.Lock()          # one onnx session, serialised (it is not documented as thread-safe)
OCR_VERSION = "rapidocr-ppocrv6-1"


@lru_cache
def _engine():
    from rapidocr import RapidOCR

    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    return RapidOCR()


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_ocr(path: str | Path) -> list[OcrLine]:
    digest = file_sha256(path)
    cache = get_settings().cache_dir / "ocr" / f"{digest}-{OCR_VERSION}.json"
    if cache.exists():
        return [OcrLine(**x) for x in json.loads(cache.read_text())]
    with _lock:
        res = _engine()(str(path))
    lines: list[OcrLine] = []
    if res.txts is not None:
        for i, (txt, score, quad) in enumerate(zip(res.txts, res.scores, res.boxes)):
            xs, ys = [float(p[0]) for p in quad], [float(p[1]) for p in quad]
            lines.append(OcrLine(id=i, text=str(txt), score=round(float(score), 4),
                                 box=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([ln.model_dump() for ln in lines]))
    return lines
