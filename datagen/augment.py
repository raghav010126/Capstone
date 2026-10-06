"""Corrected dataset: make the labels the instructors' generator forgot to draw actually visible.

The official generator records tampered IDs, a name-mismatch fraud and a blurry prescription in ``metadata.json`` but
never renders them (see docs/dataset_findings.md F2, F3, F5). This script derives ``data/corrected`` from
``data/official`` by editing *the finished images* the way a forger would, and patches the ground-truth records to match:

* tampered IDs   - the expiry date is covered and redrawn in a different size and ink, and the card is saved as a JPEG
                   twice (original scan, then the edited file), so Error Level Analysis can see the edit;
* name mismatch  - the printed name is replaced by the altered name the generator had already chosen;
* blurry Rx      - the Gaussian blur the generator meant to apply is applied.

The structuring fraud (a UB-04 form without the structuring line) is not re-rendered; it stays labelled "not visible".
Unchanged files are hard-linked, so the corrected set costs almost no disk space.

Usage: python datagen/augment.py data/official data/corrected
"""

from __future__ import annotations

import io
import json
import os
import random
import shutil
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import resolve_font

TAMPER_INK = (20, 20, 120)           # what generate_docs._id_drivers_license(tampered=True) intended
TAMPER_SIZE = 22
BLUR_RADIUS = 1.2


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(resolve_font("arialbd.ttf" if bold else "arial.ttf") or "", size)


def _background(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Median colour of a thin frame just outside ``box`` (the card background there)."""
    x0, y0, x1, y1 = box
    px = []
    for x in range(max(0, x0 - 6), min(img.width, x1 + 7), 3):
        px += [img.getpixel((x, max(0, y0 - 5))), img.getpixel((x, min(img.height - 1, y1 + 5)))]
    for y in range(y0, y1, 3):
        px += [img.getpixel((max(0, x0 - 5), y)), img.getpixel((min(img.width - 1, x1 + 6), y))]
    return tuple(sorted(c[i] for c in px)[len(px) // 2] for i in range(3))   # per-channel median


def overwrite_text(img: Image.Image, bbox: list[float], new_text: str, size: int, ink: tuple[int, int, int],
                   bold: bool = True, dx: int = 0) -> tuple[Image.Image, list[int]]:
    """Cover the text in ``bbox`` with the local background and draw ``new_text`` in its place."""
    img = img.convert("RGB").copy()
    x0, y0, x1, y1 = (round(v) for v in bbox)
    pad = 4
    cover = (x0 - pad, y0 - pad, x1 + pad + 24, y1 + pad)
    d = ImageDraw.Draw(img)
    d.rectangle(cover, fill=_background(img, cover))
    font = _font(bold, size)
    d.text((x0 + dx, y0 - 2), new_text, font=font, fill=ink)
    l, t, r, b = d.textbbox((x0 + dx, y0 - 2), new_text, font=font)
    return img, [l, t, r, b]


def jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, subsampling=0)
    return buf.getvalue()


def forge_expiry(png_path: Path, expiry_box: list[float], new_text: str, first_q: int = 78, final_q: int = 92,
                 as_jpeg: bool = True) -> tuple[bytes, list[int]]:
    """The tampering pipeline. JPEG route: scan saved lossy -> edited -> saved again (different compression history for
    the edited patch). PNG route: the same edit on a lossless file (no compression evidence, only typography)."""
    img = Image.open(png_path).convert("RGB")
    if as_jpeg:
        img = Image.open(io.BytesIO(jpeg_bytes(img, first_q))).convert("RGB")          # the original, already-lossy scan
    img, box = overwrite_text(img, expiry_box, new_text, TAMPER_SIZE, TAMPER_INK, dx=8)
    if as_jpeg:
        return jpeg_bytes(img, final_q), box
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), box


def shifted_date(mdy: str, years: int = 2) -> str:
    m, d, y = (int(x) for x in mdy.split("/"))
    try:
        return date(y + years, m, d).strftime("%m/%d/%Y")
    except ValueError:
        return date(y + years, m, 28).strftime("%m/%d/%Y")


def _link_tree(src: Path, dst: Path) -> None:
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if p.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
        else:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(p, dst / rel)
            except OSError:
                shutil.copy2(p, dst / rel)


def _replace(path: Path, data: bytes) -> None:
    if path.exists():
        path.unlink()                    # never write through a hard link into the official set
    path.write_bytes(data)


def build(src: Path, dst: Path) -> dict:
    if dst.exists():
        shutil.rmtree(dst)
    _link_tree(src, dst)
    gt = dst / "ground_truth"
    # every file that gets (re)written below must be a private copy: writing through a hard link would silently modify the
    # official dataset too
    for rel in ("ground_truth/render.json", "ground_truth/clusters.json", "ground_truth/labels.json",
                "ground_truth/fields.json", "dataset/metadata.json"):
        f = dst / rel
        data = f.read_bytes()
        f.unlink()
        f.write_bytes(data)
    meta = json.loads((dst / "dataset" / "metadata.json").read_text())
    render = json.loads((gt / "render.json").read_text())
    cl = json.loads((gt / "clusters.json").read_text())
    clusters = {c["cluster_id"]: c for c in cl["clusters"]}
    rng = random.Random(7)
    changed = {"tampered": [], "name_mismatch": [], "blurred": []}

    for m in meta:
        doc, c = m["doc_id"], clusters.get(m["case_cluster_id"])
        rec = render[doc]
        path = dst / "dataset" / m["file_path"]
        if m["category"] == "id_documents" and "tampered_id" in m["edge_flags"]:
            exp_iso = cl["id_expiry"][c["cluster_id"]]
            old = f"{exp_iso[5:7]}/{exp_iso[8:10]}/{exp_iso[:4]}"
            box = next(t for t in rec["texts"] if t["text"] == old)
            new = shifted_date(old)
            data, new_box = forge_expiry(path, box["bbox"], new, first_q=rng.choice([74, 78, 82]), final_q=rng.choice([90, 92, 94]))
            jpg = path.with_suffix(".jpg")
            _replace(jpg, data)
            path.unlink()
            m["file_path"] = str(Path(m["file_path"]).with_suffix(".jpg"))
            rec["file_path"] = m["file_path"]
            box["text"], box["bbox"], box["font_size"], box["fill"] = new, [float(v) for v in new_box], TAMPER_SIZE, list(TAMPER_INK)
            cl["id_expiry"][c["cluster_id"]] = f"{new[6:]}-{new[:2]}-{new[3:5]}"
            changed["tampered"].append(doc)
        elif m["fraud_reason"] == "name_mismatch" and m["category"] == "id_documents":
            true_name = next(t for t in rec["texts"] if t["text"].upper() == c["name"].upper() and t["font_size"] >= 18)
            img = Image.open(path).convert("RGB")
            img, new_box = overwrite_text(img, true_name["bbox"], c["id_display_name"].upper(), int(true_name["font_size"]), tuple(true_name["fill"]))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            _replace(path, buf.getvalue())
            true_name["text"], true_name["bbox"] = c["id_display_name"].upper(), [float(v) for v in new_box]
            changed["name_mismatch"].append(doc)
        elif m.get("blur_simulated") and rec["render"]["blur_radius"] is None and m["category"] != "unknown":
            img = Image.open(path).convert("RGB").filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            _replace(path, buf.getvalue())
            rec["render"]["blur_radius"] = BLUR_RADIUS
            changed["blurred"].append(doc)

    (dst / "dataset" / "metadata.json").write_text(json.dumps(meta, indent=4))
    (gt / "render.json").write_text(json.dumps(render))
    (gt / "clusters.json").write_text(json.dumps(cl))
    return changed


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/official")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "data/corrected")
    out = build(src, dst)
    print({k: v for k, v in out.items()})
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
    import truth

    truth.build(dst)            # labels + field ground truth recomputed from the patched render records
