"""Run the instructors' dataset generators *unmodified* inside a recording harness.

The scripts in ``datagen/official/`` are vendored byte-for-byte. This harness:

1. maps their Windows-only font names (``arial.ttf``, ``C:\\Windows\\Fonts\\segoesc.ttf`` ...) to fonts that
   exist on macOS / Linux, so text renders at the intended size instead of Pillow's tiny bitmap fallback;
2. seeds the global ``random`` / ``numpy`` RNGs (used by the scan effect) so output is pixel-deterministic;
3. optionally replaces the content seed (official = 42) to produce unseen generalisation sets;
4. records every string drawn on each saved image - text, font size, colour and its box in *final* pixel
   coordinates (tracking paste / crop / convert / filter and the scan-effect rotation) - plus render facts
   (was the scan effect applied, rotation angle, was blur actually applied) into ``ground_truth.json``.

Usage:  python datagen/harness.py --seed 42 --out data/official
"""

from __future__ import annotations

import argparse
import json
import math
import ntpath
import os
import random
import re
import sys
import weakref
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OFFICIAL = Path(__file__).resolve().parent / "official"
OFFICIAL_SEED = 42

# ── 1. Font mapping ───────────────────────────────────────────────────────────
_MAC = "/System/Library/Fonts/Supplemental"
_LINUX = "/usr/share/fonts/truetype"
FONT_MAP: dict[str, list[str]] = {
    "arial.ttf": [f"{_MAC}/Arial.ttf", f"{_LINUX}/liberation/LiberationSans-Regular.ttf",
                  f"{_LINUX}/dejavu/DejaVuSans.ttf"],
    "arialbd.ttf": [f"{_MAC}/Arial Bold.ttf", f"{_LINUX}/liberation/LiberationSans-Bold.ttf",
                    f"{_LINUX}/dejavu/DejaVuSans-Bold.ttf"],
    "ariali.ttf": [f"{_MAC}/Arial Italic.ttf", f"{_LINUX}/liberation/LiberationSans-Italic.ttf",
                   f"{_LINUX}/dejavu/DejaVuSans-Oblique.ttf"],
    "cour.ttf": [f"{_MAC}/Courier New.ttf", f"{_LINUX}/liberation/LiberationMono-Regular.ttf",
                 f"{_LINUX}/dejavu/DejaVuSansMono.ttf"],
    # handwriting-style signature fonts
    "segoesc.ttf": [f"{_MAC}/Brush Script.ttf", f"{_LINUX}/dejavu/DejaVuSerif-Italic.ttf"],
    "bradhitc.ttf": [f"{_MAC}/Bradley Hand Bold.ttf", f"{_LINUX}/dejavu/DejaVuSerif-Italic.ttf"],
    "segoepr.ttf": [f"{_MAC}/Apple Chancery.ttf", f"{_LINUX}/dejavu/DejaVuSerif-Italic.ttf"],
}


def resolve_font(name: str) -> str | None:
    for cand in FONT_MAP.get(ntpath.basename(name).lower(), []):
        if os.path.exists(cand):
            return cand
    return None


_orig_truetype = ImageFont.truetype


def _truetype(font=None, size=10, *args, **kwargs):
    if isinstance(font, str):
        font = resolve_font(font) or font
    return _orig_truetype(font, size, *args, **kwargs)


# ── 2. Text recording registry (keyed by image identity) ─────────────────────
_REG: dict[int, tuple[weakref.ref, dict]] = {}


def _entry(img: Image.Image, create: bool = False) -> dict | None:
    hit = _REG.get(id(img))
    if hit is not None and hit[0]() is img:
        return hit[1]
    if not create:
        return None
    rec = {"texts": [], "render": {}}
    _REG[id(img)] = (weakref.ref(img), rec)
    return rec


def _inherit(dst: Image.Image, src: Image.Image, fn=None) -> None:
    rec = _entry(src)
    if rec is None:
        return
    out = _entry(dst, create=True)
    texts = rec["texts"] if fn is None else [t for t in (fn(t) for t in rec["texts"]) if t]
    out["texts"].extend(texts)
    out["render"].update(rec["render"])


def _shift(dx: float, dy: float, clip: tuple[int, int] | None = None):
    def f(t):
        x0, y0, x1, y1 = t["bbox"]
        nb = [x0 + dx, y0 + dy, x1 + dx, y1 + dy]
        if clip and (nb[2] <= 0 or nb[3] <= 0 or nb[0] >= clip[0] or nb[1] >= clip[1]):
            return None
        return {**t, "bbox": nb, "quad": [[x + dx, y + dy] for x, y in t["quad"]]}
    return f


_orig_text = ImageDraw.ImageDraw.text


def _text(self, xy, text, fill=None, font=None, anchor=None, *args, **kwargs):
    _orig_text(self, xy, text, fill, font, anchor, *args, **kwargs)
    img = getattr(self, "_image", None)
    if img is None or not isinstance(text, str) or not text.strip():
        return
    keep = {k: kwargs[k] for k in ("spacing", "align", "stroke_width") if k in kwargs}
    try:
        x0, y0, x1, y1 = self.textbbox(xy, text, font=font, anchor=anchor, **keep)
    except Exception:
        return
    _entry(img, create=True)["texts"].append({
        "text": text,
        "bbox": [x0, y0, x1, y1],
        "quad": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "font_size": getattr(font, "size", None),
        "fill": list(fill) if isinstance(fill, tuple) else fill,
    })


_orig_paste = Image.Image.paste


def _paste(self, im, box=None, mask=None):
    _orig_paste(self, im, box, mask)
    if isinstance(im, Image.Image):
        dx, dy = (box[0], box[1]) if isinstance(box, tuple) and len(box) >= 2 else (0, 0)
        _inherit(self, im, _shift(dx, dy))


_orig_crop = Image.Image.crop


def _crop(self, box=None):
    out = _orig_crop(self, box)
    if box is not None:
        _inherit(out, self, _shift(-box[0], -box[1], clip=out.size))
    return out


def _passthrough(name):
    orig = getattr(Image.Image, name)

    def wrapper(self, *a, **k):
        out = orig(self, *a, **k)
        if isinstance(out, Image.Image) and out is not self:
            _inherit(out, self)
        return out

    wrapper._orig = orig  # type: ignore[attr-defined]
    return wrapper


# ── 3. Rotation transform (mirrors PIL.Image.rotate(expand=True)) ─────────────
def rotation_forward(w: int, h: int, angle: float):
    """Return f(x, y) mapping source pixel coords to coords in ``img.rotate(angle, expand=True)``."""
    a = -math.radians(angle % 360.0)
    m = [round(math.cos(a), 15), round(math.sin(a), 15), 0.0,
         round(-math.sin(a), 15), round(math.cos(a), 15), 0.0]

    def tf(x, y):
        return m[0] * x + m[1] * y + m[2], m[3] * x + m[4] * y + m[5]

    cx, cy = w / 2.0, h / 2.0
    m[2], m[5] = tf(-cx, -cy)
    m[2] += cx
    m[5] += cy
    xs, ys = zip(*(tf(x, y) for x, y in ((0, 0), (w, 0), (w, h), (0, h))))
    nw = math.ceil(max(xs)) - math.floor(min(xs))
    nh = math.ceil(max(ys)) - math.floor(min(ys))
    m[2], m[5] = tf(-(nw - w) / 2.0, -(nh - h) / 2.0)
    # m maps output -> input; invert the 2x3 affine to map input -> output
    inv = np.linalg.inv(np.array([[m[0], m[1], m[2]], [m[3], m[4], m[5]], [0, 0, 1.0]]))
    return lambda x, y: (inv[0, 0] * x + inv[0, 1] * y + inv[0, 2], inv[1, 0] * x + inv[1, 1] * y + inv[1, 2])


def _rotate_texts(texts, w, h, angle):
    fwd = rotation_forward(w, h, angle)
    out = []
    for t in texts:
        quad = [list(fwd(x, y)) for x, y in t["quad"]]
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        out.append({**t, "quad": quad, "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    return out


def wrap_scan_effect(orig):
    """Record the rotation angle / blur radius the scan effect draws from the global RNG."""

    def wrapper(img, blur=False):
        draws: list[float] = []
        real_uniform = random.uniform

        def spy(a, b):
            v = real_uniform(a, b)
            draws.append(v)
            return v

        random.uniform = spy
        try:
            out = orig(img, blur=blur)
        finally:
            random.uniform = real_uniform
        src = _entry(img)
        rec = _entry(out, create=True)
        if src is not None:
            rec["texts"].extend(_rotate_texts(src["texts"], img.width, img.height, draws[0]))
            rec["render"].update(src["render"])
        rec["render"].update({"scan_effect": True, "rotation_deg": draws[0],
                              "blur_radius": draws[1] if blur and len(draws) > 1 else None})
        return out

    return wrapper


# ── 4. Running the official scripts ───────────────────────────────────────────
GROUND: dict[str, dict] = {}
_orig_save = Image.Image.save


def _save(self, fp, format=None, **params):
    _orig_save(self, fp, format, **params)
    if isinstance(fp, (str, os.PathLike)):
        rec = _entry(self) or {"texts": [], "render": {}}
        GROUND[os.path.abspath(fp)] = {
            "width": self.width, "height": self.height,
            "render": {"scan_effect": False, "rotation_deg": None, "blur_radius": None, **rec["render"]},
            "texts": [{**t, "bbox": [round(v, 1) for v in t["bbox"]],
                       "quad": [[round(x, 1), round(y, 1)] for x, y in t["quad"]]} for t in rec["texts"]],
        }


def install_patches() -> None:
    ImageFont.truetype = _truetype
    ImageDraw.ImageDraw.text = _text
    Image.Image.paste = _paste
    Image.Image.crop = _crop
    for name in ("convert", "filter", "copy"):
        setattr(Image.Image, name, _passthrough(name))
    Image.Image.save = _save


def run_script(name: str, cwd: Path, seed: int, pixel_seed: int, env: dict[str, str] | None = None,
               hooks=None) -> dict:
    """Execute an official script as ``__main__`` with an optional content-seed override."""
    src = (OFFICIAL / name).read_text(encoding="utf-8")
    if seed != OFFICIAL_SEED and name == "generate_docs.py":
        pattern = rf"^rng = random\.Random\({OFFICIAL_SEED}\)$"
        src, n = re.subn(pattern, f"rng = random.Random({seed})", src, flags=re.M)
        assert n == 1, "content-seed line not found exactly once"
    head, sep, main = src.partition('\nif __name__ == "__main__":\n')
    ns: dict = {"__name__": "__harness__", "__file__": str(OFFICIAL / name)}
    random.seed(pixel_seed)
    np.random.seed(pixel_seed)
    old_cwd, old_env = os.getcwd(), dict(os.environ)
    os.chdir(cwd)
    os.environ.update(env or {})
    try:
        exec(compile(head, str(OFFICIAL / name), "exec"), ns)
        if hooks:
            hooks(ns)
        if sep:
            body = "if True:\n" + main
            exec(compile(body, str(OFFICIAL / name), "exec"), ns)
    finally:
        os.chdir(old_cwd)
        os.environ.clear()
        os.environ.update(old_env)
    return ns


def _json_default(o):
    if isinstance(o, datetime):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(type(o))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=OFFICIAL_SEED, help="content seed (official = 42)")
    ap.add_argument("--out", type=Path, required=True, help="output root; images go to <out>/dataset/")
    args = ap.parse_args(argv)

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    install_patches()
    pixel_seed = 10_000 + args.seed
    captured: dict = {}

    def docs_hooks(ns):
        ns["add_scan_effect"] = wrap_scan_effect(ns["add_scan_effect"])
        ns["_SIG_CANDIDATES"] = [p for p in (resolve_font(c) for c in ns["_SIG_CANDIDATES"]) if p]
        orig_clusters = ns["generate_patient_clusters"]

        def clusters_spy(*a, **k):
            clusters, blurry = orig_clusters(*a, **k)
            captured["clusters"], captured["blurry_doc_idx"] = clusters, blurry
            return clusters, blurry

        ns["generate_patient_clusters"] = clusters_spy
        orig_exp = ns["_exp_dates"]

        def exp_spy(c, expired):
            exp, color = orig_exp(c, expired)
            captured.setdefault("id_expiry", {})[c["cluster_id"]] = exp.strftime("%Y-%m-%d")
            return exp, color

        ns["_exp_dates"] = exp_spy

    print(f"[harness] generate_docs.py  (content seed {args.seed})")
    run_script("generate_docs.py", out, args.seed, pixel_seed, hooks=docs_hooks)
    print("[harness] generate_gold_policy.py / generate_silver_policy.py")
    run_script("generate_gold_policy.py", out, args.seed, pixel_seed,
               env={"POLICY_OUT_DIR": str(out / "dataset" / "policies")})
    run_script("generate_silver_policy.py", out, args.seed, pixel_seed)
    print("[harness] generate_unknown.py")
    run_script("generate_unknown.py", out, args.seed, pixel_seed)

    ds = out / "dataset"
    meta = json.loads((ds / "metadata.json").read_text())
    # normalise file paths to dataset-relative POSIX (D writes absolute, U writes relative)
    ground_docs = {}
    for m in meta:
        p = Path(m["file_path"])
        abs_p = (p if p.is_absolute() else out / p).resolve()
        m["file_path"] = abs_p.relative_to(ds).as_posix()
        g = GROUND.get(str(abs_p))
        if g is None:
            raise SystemExit(f"no render record for {abs_p}")
        ground_docs[m["doc_id"]] = {"category": m["category"], "file_path": m["file_path"], **g}
    (ds / "metadata.json").write_text(json.dumps(meta, indent=2))
    (out / "ground_truth").mkdir(exist_ok=True)
    (out / "ground_truth" / "render.json").write_text(json.dumps(ground_docs, indent=1))
    (out / "ground_truth" / "clusters.json").write_text(json.dumps(
        {"content_seed": args.seed, "blurry_doc_idx": captured["blurry_doc_idx"],
         "id_expiry": captured.get("id_expiry", {}),
         "clusters": captured["clusters"]}, indent=2, default=_json_default))
    print(f"[harness] {len(meta)} documents, ground truth -> {out / 'ground_truth'}")


if __name__ == "__main__":
    sys.exit(main())
