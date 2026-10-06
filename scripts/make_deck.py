"""Build the capstone presentation (docs/MediShield_capstone.pptx). Every number is read from docs/eval_results/.

Usage: uv run --with python-pptx --with pillow python scripts/make_deck.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "docs" / "eval_results"
SHOTS = REPO / "docs" / "screenshots"
OUT = REPO / "docs" / "MediShield_capstone.pptx"

TEAL = RGBColor(0x0F, 0x7F, 0x8A)
DEEP = RGBColor(0x12, 0x42, 0x4D)
INK = RGBColor(0x1F, 0x2D, 0x3D)
MUTED = RGBColor(0x5B, 0x6B, 0x7A)
SOFT = RGBColor(0xF3, 0xF8, 0xF9)
MINT = RGBColor(0xE1, 0xF2, 0xF3)
LINE = RGBColor(0xD8, 0xE4, 0xE7)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN, RED, AMBER = RGBColor(0x2E, 0x8B, 0x57), RGBColor(0xC0, 0x39, 0x2B), RGBColor(0xD6, 0x89, 0x10)
FONT = "Calibri"
W, H = Inches(13.333), Inches(7.5)


def load(name: str) -> dict:
    return json.loads((RES / f"{name}.json").read_text())


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".0%", "%")


held, seed, seedc = load("official-heldout"), load("seed7-all"), load("seed7_corrected-all")
rt, chat_rt, chat_eval = load("redteam"), load("chat_redteam"), load("chat_eval")
cost_case, cost_doc = held["ops"]["cold_cost_per_case_usd"], held["ops"]["cold_cost_per_doc_usd"]
manual_doc = 18.4e6 / (85_000 * 12)

prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────────
def text(slide, x, y, w, h, s, size=18, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, font=FONT):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, line in enumerate(s.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, font
    return tb


def box(slide, x, y, w, h, fill=WHITE, line=LINE, radius=True):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE, x, y, w, h)
    if radius:
        shp.adjustments[0] = 0.08
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp


def mark(slide, x, y, size, shield=WHITE, cross=DEEP):
    """MediShield mark: a shield with a medical cross."""
    s = slide.shapes.add_shape(MSO_SHAPE.PENTAGON, x, y, size, size)  # placeholder silhouette, rotated into a shield
    s.rotation = 90
    s.fill.solid()
    s.fill.fore_color.rgb = shield
    s.line.fill.background()
    arm, long = int(size * 0.18), int(size * 0.56)
    cx, cy = x + size // 2, y + int(size * 0.46)
    for (ww, hh) in ((arm, long), (long, arm)):
        c = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, cx - ww // 2, cy - hh // 2, ww, hh)
        c.fill.solid()
        c.fill.fore_color.rgb = cross
        c.line.fill.background()


def header(slide, title, kicker=None):
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = SOFT
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = TEAL
    bar.line.fill.background()
    if kicker:
        text(slide, Inches(0.7), Inches(0.45), Inches(10), Inches(0.35), kicker.upper(), 12, TEAL, True)
    text(slide, Inches(0.7), Inches(0.75), Inches(12), Inches(0.8), title, 32, INK, True)
    mark(slide, Inches(12.25), Inches(0.42), Inches(0.42), shield=TEAL, cross=WHITE)


def footer(slide, n):
    text(slide, Inches(0.7), Inches(7.05), Inches(8), Inches(0.3), "MediShield Health · Multi-agent claims intake", 10, MUTED)
    text(slide, Inches(11.9), Inches(7.05), Inches(0.8), Inches(0.3), str(n), 10, MUTED, align=PP_ALIGN.RIGHT)


def stat(slide, x, y, w, h, value, label, color=TEAL, sub=None):
    box(slide, x, y, w, h)
    text(slide, x + Inches(0.25), y + Inches(0.2), w - Inches(0.5), Inches(0.8), value, 34, color, True)
    text(slide, x + Inches(0.25), y + Inches(0.95), w - Inches(0.5), Inches(0.5), label, 14, INK, True)
    if sub:
        text(slide, x + Inches(0.25), y + Inches(1.3), w - Inches(0.5), h - Inches(1.4), sub, 11, MUTED)


def picture(slide, path, x, y, w, h_max):
    """Fit an image into a width, cropping its bottom if it is taller than h_max."""
    iw, ih = Image.open(path).size
    h = int(w * ih / iw)
    pic = slide.shapes.add_picture(str(path), x, y, width=w)
    if h > h_max:
        pic.crop_bottom = 1 - h_max / h
        pic.height = h_max
    pic.line.color.rgb = LINE
    return pic


# ── 1. title ────────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = DEEP
mark(s, Inches(0.8), Inches(0.7), Inches(0.75))
text(s, Inches(1.75), Inches(0.78), Inches(6), Inches(0.6), "MediShield Health", 22, WHITE, True)
text(s, Inches(0.8), Inches(2.4), Inches(11.5), Inches(1.2), "Multi-agent claims intake", 54, WHITE, True)
text(s, Inches(0.8), Inches(3.55), Inches(11.5), Inches(1.0),
     "Documents read, verified and decided in minutes, with a human in the loop for anything uncertain", 24,
     RGBColor(0xC9, 0xE6, 0xE8))
text(s, Inches(0.8), Inches(6.3), Inches(11.5), Inches(0.8),
     "AI Engineering Bootcamp capstone · Assignment 02\nLive: d3064azeabhrfe.cloudfront.net", 14, RGBColor(0x9F, 0xC9, 0xCD))

# ── 2. problem ──────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "Manual intake is slow, costly and error-prone", "The problem")
for i, (v, l, sub) in enumerate([("85,000", "documents a month", "claim forms, IDs, discharge summaries, prescriptions, amendments"),
                                  ("4.2 days", "per claim", "120 reviewers sort, check and route by hand"),
                                  ("$18.4M", "a year", f"about ${manual_doc:.0f} of processing per document"),
                                  ("12%", "re-processed", "plus 3 open regulatory audits on KYC")]):
    stat(s, Inches(0.7 + i * 3.05), Inches(2.0), Inches(2.8), Inches(2.4), v, l, RED if i == 3 else TEAL, sub)
text(s, Inches(0.7), Inches(5.0), Inches(12), Inches(1.2),
     "Goal: classify every document, extract and verify the data, check coverage and fraud, and return Approve / Reject / "
     "Escalate with a justification, within minutes, safely.", 18, INK)
footer(s, 2)

# ── 3. solution flow ────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "Seven agents, one decision engine, a human where it matters", "What it does")
steps = [("Upload", "PNG · JPEG · PDF · TIFF"), ("Read", "local OCR + classifier"), ("Extract", "fields grounded on the page"),
         ("Verify", "KYC · claims · policy RAG"), ("Fraud", "history + anomalies"), ("Decide", "rules + justification"),
         ("Review", "four-eyes over $10k")]
cw = Inches(1.66)
for i, (t, sub) in enumerate(steps):
    x = Inches(0.7) + i * (cw + Inches(0.1))
    shp = s.shapes.add_shape(MSO_SHAPE.CHEVRON if i else MSO_SHAPE.PENTAGON, x, Inches(2.1), cw, Inches(0.95))
    shp.fill.solid()
    shp.fill.fore_color.rgb = TEAL if i < 6 else AMBER
    shp.line.fill.background()
    tf = shp.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = 0
    tf.text = t
    tf.paragraphs[0].runs[0].font.size, tf.paragraphs[0].runs[0].font.bold = Pt(15), True
    tf.paragraphs[0].runs[0].font.color.rgb, tf.paragraphs[0].runs[0].font.name = WHITE, FONT
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    text(s, x, Inches(3.2), cw, Inches(0.7), sub, 12, MUTED, align=PP_ALIGN.CENTER)
for i, (t, d) in enumerate([("Models read, rules decide", "Claude reads documents and writes explanations; a versioned rule file "
                                                          "decides. An injected \"APPROVE\" can't decide a case."),
                            ("Evidence, not opinion", "Confidence comes from grounding, agent agreement and image quality, then "
                                                      "is calibrated. Uncertain → human."),
                            ("Every step auditable", "Hash-chained audit log, per-agent outputs in the UI, PDF case report.")]):
    x = Inches(0.7 + i * 4.1)
    box(s, x, Inches(4.35), Inches(3.85), Inches(2.25), MINT, None)
    text(s, x + Inches(0.3), Inches(4.6), Inches(3.3), Inches(0.5), t, 17, DEEP, True)
    text(s, x + Inches(0.3), Inches(5.15), Inches(3.3), Inches(1.4), d, 13, INK)
footer(s, 3)

# ── 4. product ──────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "A case-management product for the operations team", "The product")
picture(s, SHOTS / "dashboard.png", Inches(0.7), Inches(1.75), Inches(5.9), Inches(3.85))
picture(s, SHOTS / "case-detail.png", Inches(6.75), Inches(1.75), Inches(5.9), Inches(3.85))
text(s, Inches(0.7), Inches(5.75), Inches(5.9), Inches(1.0), "Dashboard: status, decision, confidence, fraud risk, live KPIs",
     13, MUTED)
text(s, Inches(6.75), Inches(5.75), Inches(5.9), Inches(1.0),
     "Case detail: live pipeline, evidence boxes on the page, per-agent panels, decision and override", 13, MUTED)
footer(s, 4)

# ── 5. architecture ─────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "Serverless on AWS, agents on Bedrock AgentCore", "Architecture")


def node(x, y, w, h, title, sub, fill=WHITE, tcolor=INK):
    box(s, x, y, w, h, fill)
    text(s, x + Inches(0.2), y + Inches(0.15), w - Inches(0.4), Inches(0.4), title, 15, tcolor, True)
    text(s, x + Inches(0.2), y + Inches(0.55), w - Inches(0.4), h - Inches(0.6), sub, 11, MUTED if tcolor == INK else MINT)


def arrow(x1, y1, x2, y2):
    c = s.shapes.add_connector(1, x1, y1, x2, y2)
    c.line.color.rgb, c.line.width = TEAL, Pt(2)
    c.line._get_or_add_ln().append(c.line._get_or_add_ln().makeelement(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd", {"type": "triangle"}))


node(Inches(0.7), Inches(2.0), Inches(2.6), Inches(1.3), "Next.js UI", "CloudFront + S3\n6 workspaces + assistant")
node(Inches(4.0), Inches(2.0), Inches(2.6), Inches(1.3), "FastAPI on Lambda", "JWT · 5 roles · uploads\nto S3 with signed forms")
node(Inches(7.4), Inches(1.75), Inches(5.2), Inches(1.75), "AgentCore Runtime: case pipeline", "LangGraph: perceive → classify → "
     "KYC · claims · policy RAG, with fraud in parallel → decide → human review", DEEP, WHITE)
node(Inches(7.4), Inches(3.75), Inches(5.2), Inches(1.45), "AgentCore Runtime: role-aware assistant",
     "router → access check → tools → answer with [n] citations · AgentCore Memory", DEEP, WHITE)
node(Inches(0.7), Inches(4.0), Inches(2.6), Inches(1.2), "DynamoDB · S3", "cases · audit chain · spend\nledger · documents")
node(Inches(4.0), Inches(4.0), Inches(2.6), Inches(1.2), "Claude", "Sonnet 5.5: read, reason, write\nOpus 5.5: retries, tamper check")
node(Inches(7.4), Inches(5.45), Inches(5.2), Inches(1.15), "Local models, no API cost",
     "RapidOCR (OCR) · bge-small + BM25 → RRF → jina reranker in Qdrant · ELA + typography forensics")
arrow(Inches(3.3), Inches(2.65), Inches(4.0), Inches(2.65))
arrow(Inches(6.6), Inches(2.5), Inches(7.4), Inches(2.5))
arrow(Inches(6.6), Inches(2.9), Inches(7.4), Inches(4.4))
text(s, Inches(0.7), Inches(5.55), Inches(6), Inches(1.1),
     "One CloudFormation stack · ARM64 image built by CodeBuild · secrets in SSM\nPay-per-use only: about $1/month idle",
     13, INK)
footer(s, 5)

# ── 6. results ──────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "Measured on data the system never saw", "Results · held-out split")
d = held["decision"]
tiles = [(pct(held["classification"]["accuracy"]), "classification", "6 document types"),
         (pct(held["extraction"]["rubric_claim_completeness"]), "claim-field extraction", "ICD · CPT · amounts · provider"),
         (pct(held["retrieval"]["recall@3"]), "policy retrieval R@3", "right clause in the top 3"),
         (pct(d["accuracy_visible"]), "decisions (visible labels)", f"{pct(d['accuracy_all'])} on all labels*")]
for i, (v, l, sub) in enumerate(tiles):
    stat(s, Inches(0.7 + i * 3.05), Inches(1.85), Inches(2.8), Inches(2.0), v, l, TEAL, sub)
tiles2 = [(f"${cost_case:.2f}", "model cost per case", f"≈ ${cost_doc:.2f} per document vs ≈ ${manual_doc:.0f} manual**"),
          (f"{pct(seed['decision']['accuracy_visible'])}", "unseen generator seed", f"{pct(seedc['decision']['accuracy_visible'])} with "
                                                                                 "tampering drawn in"),
          (str(rt["flips"]), "prompt-injection flips", f"{rt['attacks']} adversarial documents"),
          ("21 / 21", "quality gates in CI", "accuracy · safety · cost thresholds")]
for i, (v, l, sub) in enumerate(tiles2):
    stat(s, Inches(0.7 + i * 3.05), Inches(4.05), Inches(2.8), Inches(2.0), v, l, GREEN if i in (2, 3) else TEAL, sub)
text(s, Inches(0.7), Inches(6.25), Inches(12), Inches(0.7),
     "* The instructors' generator records a few labels it never draws (e.g. 'tampered' IDs); no system can see those.   "
     "** Model spend only; escalated cases still get human review.", 11, MUTED)
footer(s, 6)

# ── 7. trust ────────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "Built for a regulated business", "Safety and trust")
items = [("Roles and four-eyes", "One permission matrix for API, UI and assistant. Overrides over $10k need a second senior reviewer; "
                                 "nobody approves their own."),
         ("Tamper-evident audit", "Every view, override, report and blocked question is hash-chained; edits or deletions are located."),
         ("Injection-proof decisions", "Document text is data. Rules decide over grounded facts; red team: 0 flips, poisoned policy held."),
         ("Identity and tampering", "Expiry at the date of service, typography forensics, ELA heatmap, two-model visual agreement."),
         ("PHI protection", "Redacted from logs, traces and assistant memory; images never leave for tracing."),
         ("Cost guardrails", "Hard model-spend and daily caps across all agents, AWS budget alert, pay-per-use services only.")]
for i, (t, dsc) in enumerate(items):
    col, row = i % 2, i // 2
    x, y = Inches(0.7 + col * 6.1), Inches(1.85 + row * 1.6)
    box(s, x, y, Inches(5.85), Inches(1.4))
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, x + Inches(0.25), y + Inches(0.3), Inches(0.28), Inches(0.28))
    dot.fill.solid()
    dot.fill.fore_color.rgb = TEAL
    dot.line.fill.background()
    text(s, x + Inches(0.7), y + Inches(0.22), Inches(5), Inches(0.4), t, 16, INK, True)
    text(s, x + Inches(0.7), y + Inches(0.62), Inches(5), Inches(0.75), dsc, 12, MUTED)
footer(s, 7)

# ── 8. assistant ────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "Ask the system, within your role", "Role-aware assistant")
picture(s, SHOTS / "assistant.png", Inches(6.3), Inches(1.75), Inches(6.35), Inches(4.4))
for i, (t, dsc) in enumerate([
        ("Answers with citations", "Policy clause and page, case evidence, audit entries, each as a numbered link."),
        ("Blocked by role, at the data", "Policy search, case tools and a per-role read-only SQL database enforce access; "
                                         "the model never sees what you may not."),
        ("Remembers, privately", "Follow-ups and per-user memory on AgentCore Memory; health data redacted; one-click clear."),
        (f"{pct(chat_eval['accuracy'])} on {chat_eval['questions']} labelled questions",
         f"refusals, routing, facts, citations · red team {chat_rt['attacks']} attacks, {chat_rt['failures']} failures")]):
    y = Inches(1.85 + i * 1.12)
    text(s, Inches(0.7), y, Inches(5.3), Inches(0.4), t, 16, TEAL if i == 3 else INK, True)
    text(s, Inches(0.7), y + Inches(0.4), Inches(5.3), Inches(0.7), dsc, 12, MUTED)
footer(s, 8)

# ── 9. engineering choices ──────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "Every optimisation was measured before it shipped", "Engineering")
rows = [("Change", "Measured effect", "Accuracy"),
        ("OCR first: vision model only when OCR isn't enough", "−25% cost per case", "unchanged"),
        ("Sonnet instead of Opus for policy and fraud", "−36% cost per case ($0.13 → $0.08)", "identical decisions"),
        ("7× smaller reranker (fits the 2 GB AgentCore image)", "MRR 0.963 → 1.000", "better"),
        ("Fraud check beside the specialists; length-sorted batching", "index build 4.4 s → 1.8 s, search 0.5 s → 0.14 s",
         "unchanged"),
        ("Lazy imports + keep-warm ping", "sign-in ≈ 15 s → under 1 s", "n/a"),
        ("Text-only extraction (tested, rejected)", "−4% cost", "−4 pts → not shipped")]
tbl = s.shapes.add_table(len(rows), 3, Inches(0.7), Inches(1.85), Inches(11.9), Inches(4.4)).table
for c, wdt in enumerate((Inches(5.6), Inches(4.0), Inches(2.3))):
    tbl.columns[c].width = wdt
for r, row in enumerate(rows):
    for c, val in enumerate(row):
        cell = tbl.cell(r, c)
        cell.text = val
        p = cell.text_frame.paragraphs[0]
        p.runs[0].font.size, p.runs[0].font.name = Pt(14 if r else 13), FONT
        p.runs[0].font.bold = r == 0
        p.runs[0].font.color.rgb = WHITE if r == 0 else (RED if "not shipped" in val else INK)
        cell.fill.solid()
        cell.fill.fore_color.rgb = TEAL if r == 0 else (WHITE if r % 2 else SOFT)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
footer(s, 9)

# ── 10. demo ────────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
header(s, "What the demo shows", "Demo · about 7 minutes")
demo = [("1", "Submit a case", "Five documents uploaded; the pipeline lights up agent by agent."),
        ("2", "Read the decision", "Rejected: CPT 17000 excluded (cosmetic), cited to the policy page; evidence boxes on the claim."),
        ("3", "Human in the loop", "A $18,900 escalation: reviewer requests an override, senior approves, audit chain verifies."),
        ("4", "Ask the assistant", "Coverage with citations, a follow-up from memory, then a blocked request for the audit trail."),
        ("5", "Prove it", "Insights scorecard and calibration; red-team and quality-gate results; AWS cost ≈ $1/month idle.")]
for i, (n, t, dsc) in enumerate(demo):
    y = Inches(1.85 + i * 0.95)
    c = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(0.7), y, Inches(0.6), Inches(0.6))
    c.fill.solid()
    c.fill.fore_color.rgb = TEAL
    c.line.fill.background()
    c.text_frame.text = n
    rr = c.text_frame.paragraphs[0].runs[0]
    rr.font.size, rr.font.bold, rr.font.color.rgb, rr.font.name = Pt(18), True, WHITE, FONT
    c.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    text(s, Inches(1.55), y, Inches(3.3), Inches(0.6), t, 18, INK, True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, Inches(4.7), y, Inches(8), Inches(0.6), dsc, 14, MUTED, anchor=MSO_ANCHOR.MIDDLE)
box(s, Inches(0.7), Inches(6.55), Inches(11.9), Inches(0.42), MINT, None)
text(s, Inches(0.9), Inches(6.6), Inches(11.5), Inches(0.35),
     "Live: d3064azeabhrfe.cloudfront.net   ·   Code, evaluation report and design decisions: in the GitHub repository", 13, DEEP,
     True)
footer(s, 10)

prs.save(OUT)
print(f"wrote {OUT} ({len(prs.slides)} slides)")
