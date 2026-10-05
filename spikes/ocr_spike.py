"""Spike: can RapidOCR (onnxruntime, arm64) read the generated documents? Scored vs harness ground truth."""
import json, re, sys, time
from pathlib import Path
from rapidocr import RapidOCR

root = Path("data/official"); gt = json.loads((root / "ground_truth/render.json").read_text())
docs = sys.argv[1:] or ["claim_PT_19116", "claim_PT_17665", "id_PT_67125", "discharge_PT_19116",
                         "rx_PT_39451", "amend_PT_99733", "unknown_bank_statement_001"]
norm = lambda s: re.sub(r"[^a-z0-9$./-]", "", s.lower())
engine = RapidOCR()
for d in docs:
    g = gt[d]; t0 = time.time()
    res = engine(str(root / "dataset" / g["file_path"]))
    dt = time.time() - t0
    ocr_blob = norm(" ".join(res.txts if res.txts is not None else []))
    toks = [norm(w) for t in g["texts"] for w in t["text"].split()]
    toks = [w for w in toks if len(w) >= 3 and not set(w) <= set("_-.")]
    hit = sum(w in ocr_blob for w in toks)
    miss = [w for w in toks if w not in ocr_blob][:8]
    print(f"{d:28s} {dt:5.1f}s  boxes={(0 if res.boxes is None else len(res.boxes)):3d}  token recall={hit/len(toks):6.1%} ({hit}/{len(toks)})  e.g. missed {miss}")
