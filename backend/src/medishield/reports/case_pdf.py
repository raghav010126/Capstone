"""Downloadable case report (PDF): decision, per-document evidence, policy citations, fraud signals,
reviewer overrides and the audit hash chain with its verification status."""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from medishield.db.models import AuditEvent, Case, Override
from medishield.services.cases import display_status
from medishield.storage.base import get_storage

NAVY = colors.HexColor("#14213d")
GREY = colors.HexColor("#6b7280")
DECISION_COLOR = {"APPROVE": colors.HexColor("#15803d"), "REJECT": colors.HexColor("#b91c1c"),
                  "ESCALATE": colors.HexColor("#b45309")}


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _thumb(storage_key: str, width: float = 1.1 * inch):
    try:
        with Image.open(io.BytesIO(get_storage().get(storage_key))) as im:
            im = im.convert("RGB")
            im.thumbnail((360, 480))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=70)
        buf.seek(0)
        w, h = im.size
        return RLImage(buf, width=width, height=width * h / w)
    except Exception:                                       # noqa: BLE001 - a missing thumbnail must not break the report
        return ""


def build_case_pdf(case: Case, overrides: list[Override], audit_rows: list[AuditEvent], chain: dict) -> bytes:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=9.5, textColor=GREY)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=12, spaceBefore=10, spaceAfter=4)
    mono = ParagraphStyle("mono", parent=small, fontName="Courier", fontSize=6.5, leading=8)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.7 * inch, rightMargin=0.7 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch, title=f"MediShield case {case.id}",
                            author="MediShield Document Intake")
    dec = case.decision or {}
    final = case.final_decision or case.ai_decision or "-"
    story = [_p("MediShield - Case Report", h1),
             _p(f"Case {case.id}  |  status: {display_status(case)}  |  submitted by {case.submitted_by}  |  "
                f"{case.created_at:%Y-%m-%d %H:%M} UTC", small), Spacer(1, 8)]

    summary = Table([[_p("Final decision", small), _p("Automated decision", small), _p("Confidence", small),
                      _p("Claimed amount", small), _p("Fraud risk", small)],
                     [_p(final, ParagraphStyle("d", parent=h1, fontSize=15, textColor=DECISION_COLOR.get(final, NAVY))),
                      _p(case.ai_decision or "-", body), _p(f"{(case.ai_confidence or 0):.0%}", body),
                      _p(f"${case.total_amount:,.2f}", body),
                      _p(f"{(case.fraud or {}).get('risk_level', '-')}  ({case.risk_score:.2f})", body)]],
                    colWidths=[1.6 * inch] * 5)
    summary.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, GREY), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [summary, _p("Justification", h2), _p(dec.get("justification", "(not available)"), body)]

    story.append(_p("Documents", h2))
    for d in case.documents:
        det = d.decision_detail or {}
        reasons = "; ".join(det.get("reasons", [])) or "-"
        cls = d.classification or {}
        info = [Paragraph(f"<b>{escape(d.doc_id)}</b> - {escape(d.doc_type or 'unclassified')} "
                          f"(classifier confidence {cls.get('confidence', 0):.2f})", body),
                Paragraph(f"Decision: <b>{escape(d.decision or '-')}</b> via {escape(det.get('rule_id', '-'))}  |  "
                          f"confidence {det.get('confidence', 0):.2f}", body),
                _p(f"Evidence: {reasons}", small), _p(det.get("justification", ""), body)]
        sp = d.specialists or {}
        if sp.get("policy"):
            for pc in sp["policy"].get("per_code", []):
                info.append(_p(f"Policy {pc['code']}: {pc['status']}"
                               + (f", {pc['coverage_percentage']}% covered" if pc.get("coverage_percentage") is not None else "")
                               + f" - {pc.get('citation') or ''}", small))
        if sp.get("kyc"):
            info.append(_p("KYC: " + ("passed" if sp["kyc"]["kyc_passed"] else "FAILED") + ", flags: "
                           + (", ".join(sp["kyc"]["flags"] + sp["kyc"]["warnings"]) or "none"), small))
        if sp.get("claims") and sp["claims"]["validation_errors"]:
            info.append(_p("Claim standard: " + "; ".join(sp["claims"]["validation_errors"][:5]), small))
        row = Table([[_thumb(d.storage_key), info]], colWidths=[1.3 * inch, 5.7 * inch])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
        story.append(KeepTogether(row))

    fraud = case.fraud or {}
    story.append(_p("Fraud signals", h2))
    if fraud.get("anomalies"):
        t = Table([["Document", "Signal", "Weight", "Detail"]] + [
            [_p(a["doc_id"], small), _p(a["code"], small), f"{a['weight']:.2f}", _p(a["detail"], small)]
            for a in fraud["anomalies"]], colWidths=[1.4 * inch, 1.5 * inch, 0.5 * inch, 3.6 * inch])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                               ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(t)
    else:
        story.append(_p("No fraud signals.", body))
    if fraud.get("narrative"):
        story.append(_p(fraud["narrative"], small))

    story.append(_p("Reviewer actions", h2))
    if overrides:
        for o in overrides:
            story.append(_p(f"#{o.id} {o.requested_by}: {o.ai_decision} -> {o.decision} ({o.reason_code}), "
                            f"{o.status}{' by ' + o.resolved_by if o.resolved_by else ''}"
                            f"{', four-eyes' if o.requires_four_eyes else ''}. {o.note}", body))
    else:
        story.append(_p("None.", body))

    story.append(_p("Audit trail", h2))
    badge = "VERIFIED" if chain["ok"] else f"BROKEN at event {chain['broken_at']}: {chain['reason']}"
    story.append(_p(f"Hash-chain status ({chain['length']} events in the log): {badge}", body))
    for e in audit_rows:
        story.append(_p(f"{e.seq}  {e.ts[:19]}  {e.actor}  {e.action}  {e.hash[:16]}...", mono))
    doc.build(story)
    return buf.getvalue()
