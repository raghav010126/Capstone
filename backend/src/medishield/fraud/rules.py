"""Deterministic fraud signals. Each signal is attributed to the document that carries it.

Weights and thresholds live in ``decision_policy.yaml`` (``fraud:`` section). ICD/CPT clinical plausibility
is deliberately *not* scored (finding F10: pairs are random in the dataset; a generic medical-necessity
check would flag almost every claim) - only hard coding edits such as obstetric CPT without a pregnancy
diagnosis are enforced.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from PIL import Image

from medishield.agents.context import CaseContext
from medishield.records import ProcessedClaim, Records, name_score, parse_date
from medishield.schemas import DocType, FraudAnomaly

PREGNANCY_DX = re.compile(r"^(O\d|Z3[2-9]|Z3A)", re.IGNORECASE)
OBSTETRIC_CPT = range(59000, 59900)


def dhash(path: str | Path, size: int = 8) -> str:
    """Perceptual difference hash (64 bits): robust to re-scans, so re-submitted images collide."""
    with Image.open(path) as im:
        g = im.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(g.tobytes())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | int(px[r * (size + 1) + c] > px[r * (size + 1) + c + 1])
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def norm_claim_no(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"CLM[-\s]?\d{4}[-\s]?\d+", s.upper())
    return re.sub(r"[^A-Z0-9]", "", m.group(0)) if m else re.sub(r"[^A-Z0-9]", "", s.upper())


def _a(code: str, doc_id: str, cfg: dict, detail: str) -> FraudAnomaly:
    return FraudAnomaly(code=code, doc_id=doc_id, weight=cfg["weights"][code], detail=detail, source="rule")


def run_rules(ctx: CaseContext, records: Records, cfg: dict) -> tuple[list[FraudAnomaly], list[ProcessedClaim]]:
    """Return anomalies and the claim records to register once the case completes."""
    out: list[FraudAnomaly] = []
    claims = ctx.of_type(DocType.CLAIM_FORM)
    prior = records.prior_claims()
    new: list[ProcessedClaim] = []

    # ── duplicates: earlier claims in this case (submission order) or any previously processed case ────
    for d in claims:
        v = d.values
        member, _ = records.find_member(policy=v.get("policy_number"), name=v.get("patient_name"),
                                        dob=v.get("patient_dob"))
        pc = ProcessedClaim(d.doc_id, ctx.case_id, norm_claim_no(v.get("claim_number")),
                            member["member_id"] if member else None, v.get("service_date"),
                            v.get("total_charge"), d.image_hash or None)
        for p in prior + new:
            same_no = pc.claim_number and pc.claim_number == p.claim_number and pc.member_id == p.member_id
            same_bill = (pc.member_id and pc.member_id == p.member_id and pc.service_date == p.service_date
                         and pc.total_charge is not None and pc.total_charge == p.total_charge)
            # forms share one layout, so a coarse image hash only counts for the same member
            same_img = (pc.member_id and pc.member_id == p.member_id and pc.image_hash and p.image_hash
                        and hamming(pc.image_hash, p.image_hash) <= 4)
            if same_no or same_bill or same_img:
                why = ", ".join(w for w, ok in (("same claim number", same_no), ("same member/DOS/amount", same_bill),
                                                ("near-identical image", same_img)) if ok)
                out.append(_a("duplicate_claim", d.doc_id, cfg, f"duplicate of {p.doc_id} ({why})"))
                break
        new.append(pc)

    service_dates = [(d.doc_id, parse_date(d.values.get("service_date"))) for d in claims]
    service_dates = [(i, s) for i, s in service_dates if s]

    # ── readmission: a discharge that ended <= N days before this case's date of service ──────────────
    for d in ctx.of_type(DocType.DISCHARGE_SUMMARY):
        dis = parse_date(d.values.get("discharge_date"))
        for cid, dos in service_dates:
            if dis and 0 < (dos - dis).days <= cfg["readmission_days"]:
                out.append(_a("readmission_30d", d.doc_id, cfg,
                              f"discharged {dis}, readmitted for service on {dos} ({(dos - dis).days} days; {cid})"))
                break

    # ── prescription dated well after the date of service ─────────────────────────────────────────────
    for d in ctx.of_type(DocType.PRESCRIPTION):
        rx = parse_date(d.values.get("rx_date"))
        refs = [s for _, s in service_dates] or [parse_date(x.values.get("discharge_date"))
                                                for x in ctx.of_type(DocType.DISCHARGE_SUMMARY)]
        refs = [r for r in refs if r]
        stamp = any("EXCEED" in s.upper() for s in d.values.get("stamps") or [])
        late = [r for r in refs if rx and rx > r + timedelta(days=cfg["rx_after_service_days"])]
        if late or stamp:
            detail = (f"Rx dated {rx}, {(rx - late[0]).days} days after service {late[0]}" if late
                      else "form stamped 'EXCEEDS CLAIM DATE'")
            out.append(_a("rx_date_after_service", d.doc_id, cfg, detail))

    # ── claim-level coding / billing signals ──────────────────────────────────────────────────────────
    lo, hi = cfg["structuring_band"]
    for d in claims:
        v = d.values
        lines = v.get("service_lines") or []
        cpts = [ln["cpt"].strip().upper() for ln in lines if ln.get("cpt")]
        icds = [i.strip().upper() for i in v.get("icd_codes") or []]
        ob = [c for c in cpts if c.isdigit() and int(c) in OBSTETRIC_CPT]
        if ob and not any(PREGNANCY_DX.match(i) for i in icds):
            out.append(_a("obstetric_code_without_pregnancy_dx", d.doc_id, cfg,
                          f"obstetric CPT {', '.join(ob)} with non-pregnancy diagnoses {', '.join(icds) or 'none'}"))
        total = v.get("total_charge")
        charges = [ln["charge"] for ln in lines if ln.get("charge") is not None]
        mismatch = total is not None and charges and abs(sum(charges) - total) > 0.01
        unlisted = "99999" in cpts
        if total is not None and lo <= total < hi and (unlisted or mismatch):
            out.append(_a("structuring_below_10k", d.doc_id, cfg,
                          f"total ${total:,.2f} just under $10,000 with "
                          + ("combined code 99999" if unlisted else "line items not summing to the total")))
        else:
            if unlisted:
                out.append(_a("unlisted_combined_code", d.doc_id, cfg, "unlisted/combined service code 99999"))
            if mismatch:
                out.append(_a("total_mismatch", d.doc_id, cfg, f"lines sum ${sum(charges):,.2f} vs total ${total:,.2f}"))
        for ln in lines:
            base = records.cpt_baseline.get((ln.get("cpt") or "").strip().upper())
            if base and ln.get("charge") is not None:
                mean, sd, n = base
                z = (ln["charge"] - mean) / sd
                if z > cfg["billing_z"]:
                    out.append(_a("provider_billing_outlier", d.doc_id, cfg,
                                  f"CPT {ln['cpt']} billed ${ln['charge']:,.2f}, z={z:.1f} vs {n} historical claims"))
                    break
        member, _ = records.find_member(policy=v.get("policy_number"))
        dos = parse_date(v.get("service_date"))
        if member and dos:
            recent = [h for h in records.history_by_member.get(member["member_id"], [])
                      if 0 <= (dos - parse_date(h["service_date"])).days <= cfg["frequency_window_days"]]
            if len(recent) >= cfg["frequency_min_claims"]:
                out.append(_a("claim_frequency", d.doc_id, cfg,
                              f"{len(recent)} claims in the {cfg['frequency_window_days']} days before {dos}"))

    # ── identity consistency across documents ─────────────────────────────────────────────────────────
    c_name, c_dob, _ = ctx.patient_identity()
    for d in ctx.of_type(DocType.ID_DOCUMENT):
        n = d.values.get("name_on_id")
        if c_name and n and name_score(n, c_name) < 88:
            out.append(_a("identity_name_mismatch", d.doc_id, cfg, f"ID name '{n}' vs claim patient '{c_name}'"))
        if c_dob and d.values.get("dob") and parse_date(c_dob) != parse_date(d.values["dob"]):
            out.append(_a("identity_dob_mismatch", d.doc_id, cfg, f"ID DOB {d.values['dob']} vs claim {c_dob}"))
    return out, new


def image_hash(path: str) -> str:
    try:
        return dhash(path)
    except (OSError, ValueError):
        return ""
