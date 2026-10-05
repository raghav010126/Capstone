"""Build evaluation ground truth from a generated dataset.

The official generator writes ``expected_decision`` only for the 4 unknown documents, so decisions for the
other 151 are *derived* here with explicit, documented rules (see ``docs/dataset_findings.md``):

* precedence  : UNKNOWN -> ESCALATE, hard failure -> REJECT, fraud / low-confidence -> ESCALATE, else APPROVE
* per document: flags only apply to the document that carries them (as in metadata.json)
* visibility  : every label is checked against what was actually drawn (harness render records), so metrics
                can be reported on all docs and on the subset whose label is visible in the pixels.

Outputs (in ``<root>/ground_truth/``): ``labels.json`` (decisions, reasons, visibility, case roll-ups, splits)
and ``fields.json`` (expected extraction values per document: claims, IDs, discharge summaries,
prescriptions and amendments).

Usage: python eval/truth.py data/official
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HARD_FAIL_FLAGS = {"expired_id", "tampered_id", "uncovered_procedure", "missing_fields"}
UB04_ROOM_DAYS = 3          # generate_ub04_form: discharge = admit + 3 days, always
UB04_ROOM_RATE = 1250.0
TAMPER_INK, TAMPER_SIZE = [20, 20, 120], 22   # _id_drivers_license(tampered=True) - never invoked


def _fmt_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%m/%d/%Y")


def _money(v: float) -> str:
    return f"${v:,.2f}"


def _visible_signals(doc: dict, meta: dict, c: dict | None) -> tuple[bool, str]:
    """Is the reason for this document's label actually rendered?"""
    texts = doc["texts"]
    blob = "\n".join(t["text"] for t in texts)
    reason = meta.get("fraud_reason")
    flags = set(meta["edge_flags"])
    if meta["category"] == "unknown":
        return True, "out-of-distribution document"
    if reason == "name_mismatch":
        shown = c["id_display_name"].lower() in blob.lower()
        return shown, "altered name drawn on ID" if shown else (
            "generate_id_document() never passes display_name -> ID shows the true name")
    if reason == "amount_under_10k":
        shown = "99999" in blob
        return shown, "structuring line 99999 drawn" if shown else (
            "structuring is only injected by the CMS-1500 renderer; this claim is a UB-04")
    if reason == "date_conflict":
        shown = "EXCEEDS CLAIM DATE" in blob
        return shown, "red 'EXCEEDS CLAIM DATE' stamp" if shown else "no stamp found"
    if reason == "proc_diag_mismatch":
        return "59400" in blob, "obstetric CPT 59400 on a non-pregnancy diagnosis"
    if reason in ("readmission_30d", "duplicate_claim"):
        return True, "cross-document signal (needs the rest of the case / claim history)"
    if "tampered_id" in flags:
        shown = any(t["fill"] == TAMPER_INK and t["font_size"] == TAMPER_SIZE for t in texts)
        return shown, "tampered expiry glyphs drawn" if shown else (
            "generate_id_document() never passes tampered=True -> ID renders normally")
    if "expired_id" in flags:
        return "EXPIRED" in blob.upper(), "expired stamp / red expiry date"
    if "uncovered_procedure" in flags:
        return True, "excluded CPT code drawn on claim"
    if "missing_fields" in flags:
        if meta["category"] == "prescriptions" and c and c.get("rx_missing_field_type") == "refills":
            return True, "refills row omitted (absence only, no marker)"
        return ("MISSING" in blob.upper() or "ILLEGIBLE" in blob.upper()), "[MISSING]/[ILLEGIBLE] markers"
    if meta.get("blur_simulated"):
        blurred = doc["render"]["blur_radius"] is not None
        return blurred, "gaussian blur applied" if blurred else (
            "blur only applies inside the 40% random scan-effect branch of save_image(); not applied here")
    return True, "clean document"


def decide(meta: dict) -> tuple[str, list[str]]:
    flags = set(meta["edge_flags"])
    if meta["category"] == "unknown":
        return meta.get("expected_decision", "ESCALATE"), ["unknown_document"]
    hard = sorted(flags & HARD_FAIL_FLAGS)
    if hard:
        return "REJECT", hard
    if meta["fraud_label"]:
        return "ESCALATE", [f"fraud:{meta['fraud_reason']}"]
    if meta.get("blur_simulated"):
        return "ESCALATE", ["low_confidence:blurred_scan"]
    notes = ["warning:expiring_soon_id"] if "expiring_soon_id" in flags else []
    return "APPROVE", notes


def claim_fields(c: dict, doc: dict, meta: dict) -> dict:
    blob = "\n".join(t["text"] for t in doc["texts"])

    def vis(v):
        return v if v and v in blob else None

    form = meta.get("claim_form_type") or c["claim_type"]
    lines = [{"cpt": code, "charge": price} for code, _desc, price in c["cpt_list"]]
    total = sum(price for _c, _d, price in c["cpt_list"])
    if form == "UB04":
        room = UB04_ROOM_DAYS * UB04_ROOM_RATE
        lines = [{"cpt": None, "revenue_code": "0120", "charge": room}] + lines
        total += room
        icds = [c["icd_code"], c["secondary_icd_code"]]
    else:
        icds = [c["icd_code"]]
        if "99999" in blob:                      # structuring line (CMS-1500 only)
            total = 9_875.00
            lines.append({"cpt": "99999", "charge": total})
    assert _money(total) in blob, f"{meta['doc_id']}: total {total} not rendered"
    dos = c["treatment_date"]
    return {
        "form_type": form,
        "patient_name": vis(c["name"]),
        "patient_dob": c["dob"] if c["dob"] in blob else None,
        "policy_number": vis(c["policy"]),
        "claim_number": vis(c["claim_number"]),
        "service_date": dos if _fmt_date(dos) in blob else None,
        "icd_codes": [i for i in icds if i in blob],
        "cpt_codes": [ln["cpt"] for ln in lines if ln["cpt"] and ln["cpt"] in blob],
        "line_charges": [ln["charge"] for ln in lines if _money(ln["charge"]) in blob],
        "total_charge": total,
        "provider_npi": vis(c["npi"]),
        "billing_provider": vis(c["hospital"]),
        "attending_physician": vis(c["doctor"]),
    }


def id_fields(c: dict, doc: dict, expiry: str | None) -> dict:
    blob = "\n".join(t["text"] for t in doc["texts"]).upper()
    exp_shown = expiry is not None and _fmt_date(expiry) in blob
    return {
        "id_type": c["id_type"],
        "name_on_id": c["id_display_name"] if c["id_display_name"].upper() in blob else c["name"],
        "dob": c["dob"] if c["dob"] in blob else None,
        "expiry_date": expiry if exp_shown else None,   # medicare card prints no expiry date
        "policy_number": c["policy"] if c["policy"].upper() in blob else None,
        "reference_date": c["treatment_date"],          # expiry is judged against date of service
    }


_DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
SIG_INK = [18, 18, 80]                   # generate_docs.SIG_INK: handwriting-font ink


def _blob(doc: dict) -> str:
    return "\n".join(t["text"] for t in doc["texts"])


def _iso_from(m: re.Match) -> str:
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"


def _date_after(blob: str, label: str) -> str | None:
    """First mm/dd/yyyy date that follows ``label`` in the drawn text (labels and values may be separate strings)."""
    i = blob.find(label)
    if i < 0:
        return None
    m = _DATE.search(blob, i + len(label))
    return _iso_from(m) if m else None


def discharge_fields(c: dict, doc: dict) -> dict:
    """Admission/discharge dates are drawn from the generator RNG, so they are read back from the render
    record (the hospital-course sentence is present in every layout style)."""
    blob = _blob(doc)
    admit, discharge = _date_after(blob, "was admitted on"), _date_after(blob, "cleared for discharge on")
    assert admit and discharge, f"discharge dates not found for {c['patient_id']}"
    return {
        "patient_name": c["name"] if c["name"] in blob else None,
        "patient_dob": c["dob"] if c["dob"] in blob else None,
        "admit_date": admit,
        "discharge_date": discharge,
        "primary_icd": c["icd_code"] if c["icd_code"] in blob else None,
        "attending_physician": c["doctor"] if c["doctor"] in blob else None,
        "facility": c["hospital"] if c["hospital"].upper() in blob.upper() else None,
    }


def rx_fields(c: dict, doc: dict) -> dict:
    blob = _blob(doc)
    dob_iso = _iso_from(_DATE.search(c["dob"]))
    dates = {_iso_from(m) for m in _DATE.finditer(blob)} - {dob_iso}
    assert len(dates) == 1, f"{c['patient_id']}: expected one Rx date, found {dates}"
    dea_m = re.search(r"DEA[^:]*:\s*([A-Z]{2}\d{7})", blob)
    missing = c.get("rx_missing_field_type")
    return {
        "patient_name": c["name"] if c["name"] in blob else None,
        "patient_dob": c["dob"] if c["dob"] in blob else None,
        "rx_date": dates.pop(),
        "prescriber": c["doctor"] if c["doctor"] in blob else None,
        "prescriber_npi": c["npi"] if c["npi"] in blob else None,
        "dea_number": dea_m.group(1) if dea_m else None,
        "drugs": [rx[0] for rx in c["rx_list"] if rx[0] in blob],
        "missing_field": missing,                       # dea | dosage | refills | drug_name | None
    }


def amendment_fields(c: dict, doc: dict) -> dict:
    blob = _blob(doc)
    texts = doc["texts"]
    handwritten = any(t["fill"] == SIG_INK and t["text"] == c["name"] for t in texts)
    eff = _date_after(blob, "Effective Date")
    return {
        "policy_number": c["policy"] if c["policy"] in blob else None,
        "policyholder": c["name"] if c["name"] in blob else None,
        "dob": c["dob"] if c["dob"] in blob else None,
        "amendment_type": c["amendment"][0],
        "effective_date": eff,
        "handwritten": handwritten,
    }


def make_splits(meta: list[dict], clusters: dict[str, dict]) -> dict[str, list[str]]:
    """Stratified cluster split (dev for prompt iteration, heldout for reporting) + a 20-doc test set."""
    strata: dict[str, list[str]] = defaultdict(list)
    for cid, c in sorted(clusters.items()):
        key = c["fraud_reason"] or (sorted(c["edge_flags"])[0] if c["edge_flags"] else "clean")
        strata[key].append(cid)
    dev, held = [], []
    for i, (_k, cids) in enumerate(sorted(strata.items())):
        for j, cid in enumerate(cids):
            (dev if (i + j) % 2 == 0 else held).append(cid)
    unknown = sorted(m["doc_id"] for m in meta if m["category"] == "unknown")
    return {"dev_clusters": sorted(dev), "heldout_clusters": sorted(held),
            "dev_unknown": unknown[::2], "heldout_unknown": unknown[1::2]}


def pick_test20(meta: list[dict], labels: dict[str, dict]) -> list[str]:
    """Deterministic 20-document test set covering every category, decision and visible edge case."""
    want = [
        ("claim_forms", "APPROVE"), ("claim_forms", "APPROVE"), ("claim_forms", "REJECT:uncovered_procedure"),
        ("claim_forms", "REJECT:missing_fields"), ("claim_forms", "ESCALATE:fraud:proc_diag_mismatch"),
        ("claim_forms", "ESCALATE:fraud:duplicate_claim"),
        ("id_documents", "APPROVE"), ("id_documents", "REJECT:expired_id"),
        ("id_documents", "APPROVE:warning:expiring_soon_id"),
        ("discharge_summaries", "APPROVE"), ("discharge_summaries", "ESCALATE:fraud:readmission_30d"),
        ("prescriptions", "APPROVE"), ("prescriptions", "ESCALATE:fraud:date_conflict"),
        ("prescriptions", "REJECT:missing_fields"), ("prescriptions", "ESCALATE:low_confidence:blurred_scan"),
        ("policy_amendments", "APPROVE"), ("policy_amendments", "APPROVE"),
        ("unknown", "ESCALATE:unknown_document"), ("unknown", "ESCALATE:unknown_document"),
        ("unknown", "ESCALATE:unknown_document"),
    ]
    chosen: list[str] = []
    for cat, key in want:
        dec, _, reason = key.partition(":")
        for m in meta:
            lab = labels[m["doc_id"]]
            if (m["category"] == cat and m["doc_id"] not in chosen and lab["expected_decision"] == dec
                    and lab["visible"] and (not reason or reason in lab["reasons"])
                    and (reason or not lab["reasons"])):
                chosen.append(m["doc_id"])
                break
        else:
            raise RuntimeError(f"no document for {cat} {key}")
    return chosen


def build(root: Path) -> None:
    ds, gt_dir = root / "dataset", root / "ground_truth"
    meta = json.loads((ds / "metadata.json").read_text())
    render = json.loads((gt_dir / "render.json").read_text())
    cl = json.loads((gt_dir / "clusters.json").read_text())
    clusters = {c["cluster_id"]: c for c in cl["clusters"]}

    labels, fields = {}, {}
    for m in meta:
        c = clusters.get(m["case_cluster_id"])
        doc = render[m["doc_id"]]
        decision, reasons = decide(m)
        visible, why = _visible_signals(doc, m, c)
        labels[m["doc_id"]] = {
            "case_id": m["case_cluster_id"] or m["doc_id"], "category": m["category"],
            "expected_decision": decision, "reasons": reasons, "visible": visible, "visibility_note": why,
        }
        if m["category"] == "claim_forms":
            fields[m["doc_id"]] = claim_fields(c, doc, m)
        elif m["category"] == "id_documents":
            fields[m["doc_id"]] = id_fields(c, doc, cl["id_expiry"].get(c["cluster_id"]))
        elif m["category"] == "discharge_summaries":
            fields[m["doc_id"]] = discharge_fields(c, doc)
        elif m["category"] == "prescriptions":
            fields[m["doc_id"]] = rx_fields(c, doc)
        elif m["category"] == "policy_amendments":
            fields[m["doc_id"]] = amendment_fields(c, doc)

    cases: dict[str, list[str]] = defaultdict(list)
    for doc_id, lab in labels.items():
        cases[lab["case_id"]].append(lab["expected_decision"])
    rollup = {cid: ("ESCALATE" if "ESCALATE" in d else "REJECT" if "REJECT" in d else "APPROVE")
              for cid, d in sorted(cases.items())}

    out = {
        "rules": {
            "precedence": ["UNKNOWN->ESCALATE", "hard_fail->REJECT", "fraud|low_confidence->ESCALATE",
                           "else->APPROVE"],
            "hard_fail_flags": sorted(HARD_FAIL_FLAGS),
            "case_rollup": "any ESCALATE -> ESCALATE; else any REJECT -> REJECT; else APPROVE",
        },
        "documents": labels,
        "cases": rollup,
        "splits": make_splits(meta, clusters),
    }
    try:
        out["splits"]["test20"] = pick_test20(meta, labels)
    except RuntimeError as e:          # other seeds may lack a visible example of some edge case
        print(f"[truth] test20 not built for this dataset: {e}")
    (gt_dir / "labels.json").write_text(json.dumps(out, indent=2))
    (gt_dir / "fields.json").write_text(json.dumps(fields, indent=2))

    dec = Counter(lab["expected_decision"] for lab in labels.values())
    hidden = sorted(d for d, lab in labels.items() if not lab["visible"])
    print(f"documents: {len(labels)}  decisions: {dict(dec)}")
    print(f"cases: {dict(Counter(rollup.values()))}")
    print(f"labels NOT visible in pixels ({len(hidden)}): {hidden}")
    print(f"fields: {len(fields)} docs  -> {gt_dir}")


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "data/official"))
