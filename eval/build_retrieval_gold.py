"""Build the policy-retrieval gold set from the policy *text* (never from retriever output).

For every procedure code the generator can bill, the relevant policy sections are where the policy text
itself governs that service:

* excluded codes: the table-4.1 row whose range contains the code (found by parsing the PDF text) plus the
  prose exclusions section;
* covered codes: the Schedule of Benefits row and the Inclusions bullet for the service, and the rider
  section where coverage depends on a rider.

The code -> service mapping (``CATEGORY``) is a human label written from the CPT descriptor and the policy's
benefit wording. Sections are then *located* in each plan's PDF text with an independent parser
(pypdfium2, not Docling), so plan-specific numbering is honoured.

Usage: python eval/build_retrieval_gold.py data/official
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "datagen"))
from records import official_pools

HEADING = re.compile(r"^\s*(\d+(?:\.\d+)?)\.?\s+([A-Z][^\n]{2,80})$")
RANGE_LINE = re.compile(r"\b([0-9A-Z]{5})\s*-\s*([0-9A-Z]{5})\b")

# Human labels: CPT -> service category (from the CPT descriptor).
CATEGORY = {
    "99213": "office_visit", "99214": "office_visit", "99215": "office_visit",
    "71046": "diagnostic", "71250": "diagnostic", "70553": "diagnostic", "72148": "diagnostic",
    "85025": "diagnostic", "80053": "diagnostic", "36415": "diagnostic", "93000": "diagnostic",
    "93306": "diagnostic",
    "44970": "surgery", "27447": "surgery", "43239": "surgery", "33533": "surgery", "47562": "surgery",
    "29827": "surgery",
    "99284": "emergency", "99291": "critical_care", "90837": "mental_health", "59400": "maternity",
}
# Where the policy text governs each category: anchor regexes searched in the plan's PDF text.
ANCHORS = {   # benefit-table row (section 1), inclusion bullet (section 3), rider heading (section 5)
    "office_visit": [r"Specialist Copay", r"^\s*\*\s*(Outpatient physician visits|Physician services: office visits)"],
    "diagnostic": [r"Diagnostic Lab & Imaging", r"^\s*\*\s*Diagnostic (services|imaging)"],
    "surgery": [r"Outpatient Surgery", r"^\s*\*\s*(Surgical services|Outpatient surgery)"],
    "emergency": [r"Emergency Room \(ER\)", r"^\s*\*\s*Emergency (room services|care)"],
    "critical_care": [r"Inpatient Hospitalization", r"^\s*\*\s*Inpatient (hospitalization|hospital services)"],
    "mental_health": [r"Mental Health / Substance Use \(outpatient\)", r"^\s*\*\s*Mental health and substance use"],
    "maternity": [r"^\s*\*\s*Maternity (care|and newborn care)", r"^\s*(\d+(\.\d+)?\s+)?Maternity Rider\s*$"],
}


def section_lines(pdf_path: Path) -> list[tuple[str, str]]:
    """(section_no, line) for every line after the table of contents."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    text = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith("1. Schedule of Benefits")]
    body = lines[starts[1] if len(starts) > 1 else 0:]          # skip the table of contents
    out, cur = [], "0"
    for ln in body:
        m = HEADING.match(ln)
        if m and not re.search(r"\s\d+\s*$", ln):
            cur = m.group(1)
        out.append((cur, ln))
    return out


def build(root: Path) -> dict:
    pools = official_pools()
    codes = {c for c, _d, _p in pools["CPT_POOL"]} | {c for c, _d, _p in pools["UNCOVERED_CPT"]} | {"59400"}
    gold: dict = {"_doc": __doc__.split("\n\n")[0], "plans": {}}
    for pdf in sorted((root / "dataset" / "policies").glob("*.pdf")):
        plan = next(p for p in ("gold", "silver") if p in pdf.stem)
        lines = section_lines(pdf)
        ranges = []
        for sec, ln in lines:
            m = RANGE_LINE.search(ln)
            if m and sec.startswith("4"):
                ranges.append((m.group(1), m.group(2), sec))
        excl_sec = next((s for s, ln in lines if "Exclusions" in ln and HEADING.match(ln)), "4")
        entries = {}
        for code in sorted(codes):
            hits = [(a, b, s) for a, b, s in ranges if code.isdigit() and a.isdigit() and int(a) <= int(code) <= int(b)]
            if hits:
                entries[code] = {"category": "excluded", "relevant_sections": sorted({s for *_x, s in hits} | {excl_sec}),
                                 "evidence": [f"{a}-{b}" for a, b, _s in hits]}
                continue
            cat = CATEGORY[code]
            secs, ev = set(), []
            for pat in ANCHORS[cat]:
                found = [(s, ln.strip()) for s, ln in lines if re.search(pat, ln, re.IGNORECASE)]
                if found:
                    secs.add(found[0][0])
                    ev.append(f"§{found[0][0]}: {found[0][1][:70]}")
            entries[code] = {"category": cat, "relevant_sections": sorted(secs), "evidence": ev}
        gold["plans"][plan] = entries
    return gold


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/official")
    g = build(root)
    out = Path(__file__).resolve().parent / "retrieval_gold.json"
    out.write_text(json.dumps(g, indent=1))
    for plan, e in g["plans"].items():
        print(plan, len(e), "codes;", {c: v["relevant_sections"] for c, v in list(e.items())[:30]})
