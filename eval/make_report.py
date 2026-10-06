"""Assemble docs/EVAL_REPORT.md from every published result in docs/eval_results/.

Usage: python eval/make_report.py        (also: make report)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))

from report import render

RES = REPO / "docs" / "eval_results"
ORDER = ["official-dev", "official-heldout", "corrected-all", "seed7-all", "seed7_corrected-all", "multilingual-dev", "multilingual-heldout"]
TITLE = {"official-dev": "Official dataset, dev split (prompts were tuned here)",
         "official-heldout": "Official dataset, held-out split (never tuned on)",
         "corrected-all": "Corrected dataset (tampering, name mismatch and blur actually drawn), all documents",
         "seed7-all": "Unseen generalisation set (generator seed 7), all documents",
         "seed7_corrected-all": "Unseen set with the tampering, name mismatch and blur drawn (corrected seed 7), all documents",
         "multilingual-dev": "Spanish and Hindi, dev members", "multilingual-heldout": "Spanish and Hindi, held-out members"}
pct = lambda x: "n/a" if x is None else f"{x * 100:.1f}%"


def load(name: str) -> dict | None:
    p = RES / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    runs = {n: r for n in ORDER if (r := load(n))}
    L = ["# MediShield evaluation report", "",
         (f"_Assembled {datetime.now():%Y-%m-%d %H:%M} from `docs/eval_results/` by `make report`. Every number comes from running "
         "the real pipeline (Claude Sonnet 5.5 / Opus 5.5, RapidOCR, Docling, Qdrant) on labelled documents._"), "",
         ("**How to read this.** Prompts and thresholds were tuned on the *dev* split only. The *held-out* split, the *seed-7* set "
         "(generated with a different random seed and never inspected during development) and the multilingual held-out members "
         "are reported without tuning. Decision accuracy is shown on **all** labels and on the labels that are actually **visible in "
         "the pixels**: the instructors' generator records a few labels (tampered IDs, a name mismatch, a structuring fraud, a blur) "
         "that it never draws, so no system can see them (see `docs/dataset_findings.md`)."), "",
         "## Headline", "",
         "| Run | Docs | Classification | Extraction (claim fields) | Retrieval Recall@3 | Decisions (all labels) | Decisions (visible labels) | Cost / case |",
         "|---|---|---|---|---|---|---|---|"]
    for n, r in runs.items():
        L.append(f"| {TITLE[n].split(',')[0].split(' (')[0]} · {r['split']} | {r['ops']['docs']} | {pct(r['classification']['accuracy'])} | "
                 f"{pct(r['extraction']['rubric_claim_completeness'])} | {pct(r['retrieval']['recall@3'])} | {pct(r['decision']['accuracy_all'])} | "
                 f"{pct(r['decision']['accuracy_visible'])} | ${r['ops']['cold_cost_per_case_usd']:.2f} |")
    L.append("")
    rt, rp, fo = load("redteam"), load("redteam_policy"), load("forensics")
    if rt:
        L += ["## Robustness", "",
              f"- **Prompt-injection red team:** {rt['flips']} decision flips in {rt['attacks']} adversarial documents"
              + (f"; poisoned policy PDF {'held' if rp and rp['held'] else 'FLIPPED'} (excluded code stayed NOT_COVERED)" if rp else "")
              + ". Details: `docs/redteam.md`."]
    if fo:
        t, e = fo["typography"], fo["ela"]
        L += [(f"- **Tamper forensics** (24 ID cards, forged expiry dates): typography check caught {t['retyped_date_png']['caught']}/"
              f"{t['retyped_date_png']['of']} retyped dates in PNGs ({t['clean_png_flagged']['flagged']}/{t['clean_png_flagged']['of']} clean cards flagged); "
              f"ELA caught {e['spliced_region_caught']['caught']}/{e['spliced_region_caught']['of']} spliced regions with "
              f"{e['clean_jpeg_flagged']['flagged']}/{e['clean_jpeg_flagged']['of']} false alarms, so it is advisory only.")]
    ab = {k: load(f"ab/{k}") for k in ("official-dev-always", "official-dev-auto-text-extract")}
    if ab["official-dev-always"] and "official-dev" in runs:
        L += ["", "## OCR-first routing (page images are sent to a model only when OCR is not enough)", "",
              ("Measured on the dev split with the same documents and the same prompts. *Always vision* sends every page image to the model "
              "(classifier, extractor, KYC visual review). *OCR-first* skips the classifier model call when the printed title words settle the "
              "type on a clean OCR page, and skips the KYC visual review when OCR is clean and neither forensic check flags the card. "
              "*OCR-first + text-only extraction* additionally reads fields from OCR text alone first; it is **off** because it saved little "
              "and cost accuracy."), "",
              "| Configuration | Decisions (all) | Decisions (visible) | Claim-field extraction | Cost / case (uncached) | Classifier $ | KYC visual $ | Extractor $ |",
              "|---|---|---|---|---|---|---|---|"]
        for label, r in (("Always vision", ab["official-dev-always"]), ("OCR-first (shipped)", runs["official-dev"]),
                         ("OCR-first + text-only extraction", ab["official-dev-auto-text-extract"])):
            if not r:
                continue
            by = r["ops"]["cold_cost_by_agent"]
            L.append(f"| {label} | {pct(r['decision']['accuracy_all'])} | {pct(r['decision']['accuracy_visible'])} | "
                     f"{pct(r['extraction']['rubric_claim_completeness'])} | ${r['ops']['cold_cost_per_case_usd']:.3f} | "
                     f"${by.get('classifier', 0):.2f} | ${by.get('kyc_visual', 0):.2f} | ${by.get('extractor', 0):.2f} |")
    ml = [r for n, r in runs.items() if n.startswith("multilingual") and r.get("by_language")]
    if ml:
        L += ["", "## Spanish and Hindi", "", "| Split | Language | Docs | Classification | Extraction (all fields) | Decisions | Mean classifier confidence |", "|---|---|---|---|---|---|---|"]
        for r in ml:
            for lang, v in r["by_language"].items():
                L.append(f"| {r['split']} | {lang} | {v['documents']} | {pct(v['classification'])} | {pct(v['extraction_all_fields'])} | "
                         f"{pct(v['decision'])} | {v['mean_classifier_confidence']} |")
    cal = [(n, r["calibration"]) for n, r in runs.items() if r.get("calibration")]
    if cal:
        L += ["", "## Confidence calibration", "",
              ("ECE = expected calibration error (lower is better); Brier = mean squared error of the confidence as a probability of being correct. "
              "The isotonic calibrator is fitted on the dev split and applied unchanged elsewhere."), "",
              "| Run | Docs | Accuracy | ECE raw | ECE calibrated | Brier raw | Brier calibrated |", "|---|---|---|---|---|---|---|"]
        for n, c in cal:
            a = c["all"]
            cc = a.get("calibrated")
            L.append(f"| {n}{' (in-sample)' if c['fitted_on_this_split'] else ''} | {a['n']} | {pct(a['accuracy'])} | {a['raw']['ece']:.3f} | "
                     f"{cc['ece']:.3f} | {a['raw']['brier']:.3f} | {cc['brier']:.3f} |" if cc else f"| {n} | {a['n']} | {pct(a['accuracy'])} | {a['raw']['ece']:.3f} | - | {a['raw']['brier']:.3f} | - |")
    for n, r in runs.items():
        L += ["", "---", "", f"## {TITLE[n]}", ""] + render_run(r)
    (REPO / "docs" / "EVAL_REPORT.md").write_text("\n".join(L) + "\n")
    print(f"wrote docs/EVAL_REPORT.md with {len(runs)} runs")


def render_run(r: dict) -> list[str]:
    body = render(r, level=3)
    return body[2:] if body and body[0].startswith("###") else body            # drop the repeated title line


if __name__ == "__main__":
    main()
