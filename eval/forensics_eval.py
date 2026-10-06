"""Measure the tamper detectors in isolation (no model calls).

Samples are made from the 30 official ID cards:
  clean      - the card saved as a JPEG once, or re-saved (a normal scan being re-compressed), or left as a PNG;
  forged     - its expiry date covered and redrawn (see datagen/augment.py), as JPEG and as PNG;
  spliced    - a region copied from another card saved at a lower JPEG quality (the forgery ELA is meant for).

Usage: python eval/forensics_eval.py [--print-scores]
"""

from __future__ import annotations

import io
import json
import random
import sys
import tempfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "datagen"))

import augment
from medishield.forensics import ela, typography
from medishield.ocr.engine import run_ocr


def samples(root: Path):
    render = json.loads((root / "ground_truth" / "render.json").read_text())
    cl = json.loads((root / "ground_truth" / "clusters.json").read_text())
    ids = sorted(d for d in render if d.startswith("id_"))
    rng = random.Random(11)
    tmp = Path(tempfile.mkdtemp(prefix="forensics-"))
    for i, doc in enumerate(ids):
        rec = render[doc]
        png = root / "dataset" / rec["file_path"]
        pid = doc.removeprefix("id_")
        cluster = next(c for c in cl["clusters"] if c["patient_id"] == pid)
        exp = cl["id_expiry"][cluster["cluster_id"]]
        old = f"{exp[5:7]}/{exp[8:10]}/{exp[:4]}"
        box = next((t for t in rec["texts"] if t["text"] == old), None)
        if box is None:                                    # e.g. Medicare cards print no expiry date
            continue
        img = Image.open(png).convert("RGB")
        once = augment.jpeg_bytes(img, rng.choice([85, 90, 95]))
        twice = augment.jpeg_bytes(Image.open(io.BytesIO(augment.jpeg_bytes(img, rng.choice([70, 78, 82])))), rng.choice([90, 93]))
        forged_jpg, _ = augment.forge_expiry(png, box["bbox"], augment.shifted_date(old), rng.choice([72, 78, 84]), rng.choice([88, 92, 95]))
        forged_png, _ = augment.forge_expiry(png, box["bbox"], augment.shifted_date(old), as_jpeg=False)
        donor = Image.open(root / "dataset" / render[ids[(i + 7) % len(ids)]]["file_path"]).convert("RGB")
        donor_j = Image.open(io.BytesIO(augment.jpeg_bytes(donor, rng.choice([50, 60, 70])))).convert("RGB")
        spliced = Image.open(io.BytesIO(once)).convert("RGB")
        spliced.paste(donor_j.crop((250, 330, 440, 390)), (250, 330))          # a region copied from another, harder-compressed JPEG
        files = {"clean_once": once, "clean_resaved": twice, "forged_jpg": forged_jpg, "forged_png": forged_png,
                 "clean_png": png.read_bytes(), "spliced_jpg": augment.jpeg_bytes(spliced, 90)}
        paths = {}
        for k, b in files.items():
            p = tmp / f"{doc}.{k}.{'png' if k.endswith('png') else 'jpg'}"
            p.write_bytes(b)
            paths[k] = p
        yield i, doc, paths


def main() -> None:
    root = REPO / "data" / "official"
    rows = []
    for i, doc, paths in samples(root):
        r = {"i": i, "doc": doc}
        for k in ("clean_once", "clean_resaved", "forged_jpg", "spliced_jpg"):
            res = ela.analyse(paths[k].read_bytes(), with_heatmap=False)
            r["ela_" + k] = res.flagged
        for k in ("clean_png", "forged_png", "clean_once", "clean_resaved", "forged_jpg"):
            r["typo_" + k] = typography.analyse(str(paths[k]), run_ocr(paths[k])).flagged
        rows.append(r)
    n = len(rows)
    count = lambda key: sum(r[key] for r in rows)
    result = {
        "samples_per_group": n,
        "typography": {
            "retyped_date_png": {"caught": count("typo_forged_png"), "of": n},
            "retyped_date_jpeg": {"caught": count("typo_forged_jpg"), "of": n},
            "clean_png_flagged": {"flagged": count("typo_clean_png"), "of": n},
            "clean_jpeg_flagged": {"flagged": count("typo_clean_once") + count("typo_clean_resaved"), "of": 2 * n},
        },
        "ela": {
            "spliced_region_caught": {"caught": count("ela_spliced_jpg"), "of": n},
            "retyped_date_caught": {"caught": count("ela_forged_jpg"), "of": n},
            "clean_jpeg_flagged": {"flagged": count("ela_clean_once") + count("ela_clean_resaved"), "of": 2 * n},
            "verdict": "weak but above chance on flat synthetic documents: advisory only (heatmap and a warning, never a decision)",
        },
        "settings": {"ela_z": ela.Z_THRESHOLD, "ela_min_blocks": ela.MIN_CLUSTER_BLOCKS, "typography_tolerance": typography.TOLERANCE},
    }
    out = REPO / "docs" / "eval_results" / "forensics.json"
    out.write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
