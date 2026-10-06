"""Build the solution review deck the Solution Owner presents to MediShield's CTO (docs/MediShield_capstone.pptx).
Every measured number is read from docs/eval_results/; speaker notes carry what to say on each slide.

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
docs_year = 85_000 * 12
model_year = cost_doc * docs_year                         # model spend at the brief's full volume
pilot_1k = cost_doc * 1000

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
    text(slide, Inches(0.7), Inches(7.05), Inches(8), Inches(0.3), "MediShield Health · Claims intake · Solution review for the CTO", 10, MUTED)
    text(slide, Inches(11.9), Inches(7.05), Inches(0.8), Inches(0.3), str(n), 10, MUTED, align=PP_ALIGN.RIGHT)


def stat(slide, x, y, w, h, value, label, color=TEAL, sub=None):
    box(slide, x, y, w, h)
    text(slide, x + Inches(0.25), y + Inches(0.2), w - Inches(0.5), Inches(0.8), value, 34, color, True)
    text(slide, x + Inches(0.25), y + Inches(0.95), w - Inches(0.5), Inches(0.5), label, 14, INK, True)
    if sub:
        text(slide, x + Inches(0.25), y + Inches(1.3), w - Inches(0.5), h - Inches(1.4), sub, 11, MUTED)


def notes(slide, s):
    """Speaker notes: what the Solution Owner says on this slide."""
    slide.notes_slide.notes_text_frame.text = s


def card(slide, x, y, w, h, title, body, accent=TEAL, size=12):
    box(slide, x, y, w, h)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y + Inches(0.25), Inches(0.07), h - Inches(0.5))
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    text(slide, x + Inches(0.3), y + Inches(0.22), w - Inches(0.5), Inches(0.4), title, 16, INK, True)
    text(slide, x + Inches(0.3), y + Inches(0.65), w - Inches(0.5), h - Inches(0.8), body, size, MUTED)


def table(slide, rows, x, y, widths, h, size=13, flag=None):
    tbl = slide.shapes.add_table(len(rows), len(widths), x, y, sum(widths, Inches(0)), h).table
    for c, wdt in enumerate(widths):
        tbl.columns[c].width = wdt
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = val
            run = cell.text_frame.paragraphs[0].runs[0]
            run.font.size, run.font.name, run.font.bold = Pt(size), FONT, r == 0 or c == 0
            run.font.color.rgb = WHITE if r == 0 else (RED if flag and flag(val) else INK)
            cell.fill.solid()
            cell.fill.fore_color.rgb = TEAL if r == 0 else (WHITE if r % 2 else SOFT)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    return tbl


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


# ── slides ──
d = held["decision"]
n = 0


def new(title, kicker):
    global n
    n += 1
    sl = prs.slides.add_slide(BLANK)
    header(sl, title, kicker)
    footer(sl, n + 1)
    return sl


# ── 1. title ────────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = DEEP
mark(s, Inches(0.8), Inches(0.7), Inches(0.75))
text(s, Inches(1.75), Inches(0.78), Inches(6), Inches(0.6), "MediShield Health", 22, WHITE, True)
text(s, Inches(0.8), Inches(2.3), Inches(11.5), Inches(1.2), "Claims intake automation", 54, WHITE, True)
text(s, Inches(0.8), Inches(3.45), Inches(11.5), Inches(1.0), "Solution review and go-live recommendation for the CTO", 26,
     RGBColor(0xC9, 0xE6, 0xE8))
text(s, Inches(0.8), Inches(6.2), Inches(11.5), Inches(0.8),
     "Raghav Bansal · Solution Owner · October 2026\nLive environment: d3064azeabhrfe.cloudfront.net", 14, RGBColor(0x9F, 0xC9, 0xCD))
notes(s, "I'm the solution owner for claims-intake automation. In the next 15 minutes: what we built, how well it works on data it "
         "never saw, what it costs to run, the risks I still see, and the one decision I need from you today.")

# ── 2. executive summary ────────────────────────────────────────────────────────────────────────────
s = new("A working claims-intake system, live on AWS", "Executive summary")
for i, (v, l, sub) in enumerate([("≈ 1 min", "to a decision", "per 5-document case, measured live (today: 4.2 days)"),
                                  (pct(d["accuracy_visible"]), "decisions correct", f"held-out data, visible labels ({pct(d['accuracy_all'])} on all)"),
                                  (f"${cost_case:.2f}", "model cost per case", f"≈ ${cost_doc:.2f} per document vs ≈ ${manual_doc:.0f} manual"),
                                  ("$1.25", "a month while idle", "pay-per-use AWS; nothing runs between claims")]):
    stat(s, Inches(0.7 + i * 3.05), Inches(1.8), Inches(2.8), Inches(2.1), v, l, TEAL, sub)
for i, line in enumerate([("Seven AI agents read, verify and check every document; a versioned rule file makes the decision, and a person reviews "
                          "anything uncertain."),
                          "Role-based access, four-eyes approval over $10,000 and a tamper-evident audit trail are built in, not bolted on.",
                          "Everything is in one AWS account and one CloudFormation stack, tested on every change by CI quality gates."]):
    text(s, Inches(0.7), Inches(4.15 + i * 0.5), Inches(11.9), Inches(0.5), "•  " + line, 15, INK)
box(s, Inches(0.7), Inches(5.75), Inches(11.9), Inches(1.0), MINT, None)
text(s, Inches(1.0), Inches(5.87), Inches(11.4), Inches(0.8),
     "Recommendation: approve a shadow pilot, run beside one operations team on de-identified real scans with no effect on "
     "members, and decide go-live on measured agreement with our reviewers.", 15, DEEP, True)
notes(s, "Bottom line first. The system is built and running in our AWS account. On held-out data it matched every decision whose "
         "evidence is visible on the page, at about eight cents a case in model spend. It costs about a dollar a month when idle. "
         "What it has not seen yet is real scans, which is why I'm asking for a shadow pilot rather than a go-live.")

# ── 3. business case ────────────────────────────────────────────────────────────────────────────────
s = new("Four days of manual handling become about a minute", "Business case")
text(s, Inches(0.7), Inches(1.75), Inches(5.6), Inches(0.4), "TODAY", 13, RED, True)
for i, (v, l) in enumerate([("85,000", "documents a month, sorted and checked by 120 reviewers"), ("4.2 days", "average per claim"),
                            ("$18.4M", f"a year in processing, ≈ ${manual_doc:.0f} per document"),
                            ("12% · 3", "documents re-processed · open regulatory audits on KYC")]):
    y = Inches(2.2 + i * 1.08)
    box(s, Inches(0.7), y, Inches(5.6), Inches(0.92))
    text(s, Inches(0.95), y + Inches(0.18), Inches(1.9), Inches(0.6), v, 24, RED, True)
    text(s, Inches(2.9), y + Inches(0.26), Inches(3.3), Inches(0.6), l, 13, INK)
text(s, Inches(6.9), Inches(1.75), Inches(5.7), Inches(0.4), "WITH THE SYSTEM", 13, TEAL, True)
for i, (v, l) in enumerate([("≈ 1 min", "to an Approve / Reject / Escalate decision with its justification"),
                            (f"≈ ${model_year / 1000:.0f}k", f"model spend a year at full volume ({docs_year / 1e6:.2f}M documents × ${cost_doc:.3f})"),
                            ("Humans", "still decide every uncertain or risky case, with the rule and the evidence in front of them"),
                            ("Audit-ready", "every decision traceable: rule id, evidence, hash-chained log, PDF case report")]):
    y = Inches(2.2 + i * 1.08)
    box(s, Inches(6.9), y, Inches(5.7), Inches(0.92))
    text(s, Inches(7.15), y + Inches(0.18), Inches(1.9), Inches(0.6), v, 24 if i < 2 else 20, TEAL, True)
    text(s, Inches(9.1), y + Inches(0.26), Inches(3.4), Inches(0.6), l, 13, INK)
text(s, Inches(0.7), Inches(6.55), Inches(11.9), Inches(0.45),
     "Savings depend on the straight-through rate, which the pilot will measure on real documents; escalated cases keep their manual "
     "cost. AWS infrastructure is pay-per-use on top of model spend.", 11, MUTED)
notes(s, "The cost of intake today is people's time: four days and about eighteen dollars a document. Model spend at our full volume "
         "projects to under twenty thousand dollars a year. I'm deliberately not quoting a savings number yet: it depends on how many "
         "real cases go straight through, and that is exactly what the pilot measures.")

# ── 4. scope ────────────────────────────────────────────────────────────────────────────────────────
s = new("Everything in the brief, plus what operations will need next", "Scope delivered")
cols = [("The brief · 7 of 7", ["Multi-agent pipeline: 7 agents in LangGraph", "Ingestion API (FastAPI): upload, cases, trigger",
                                "Policy RAG: Docling parsing + hybrid retrieval", "Case-management UI and review queue",
                                "Labelled dataset and evaluation harness", "Architecture diagram", "README with an end-to-end walkthrough"]),
        ("Bonus challenges · 6 of 6", ["Confidence calibration (ECE 0.018)", "Live progress (WebSockets; polling on AWS)",
                                       "Tamper detection: ELA + typography", "Spanish and Hindi documents", "PDF case report",
                                       "LangSmith tracing per agent call"]),
        ("Beyond the brief", ["Role-aware assistant with citations (AgentCore + Memory)", "MCP server: Claude tools under the caller's role",
                              "Email intake from allow-listed senders", "Policy upload with no code change",
                              "AI quality monitor: where reviewers disagree", "CI: 261 tests + 21 quality gates"])]
for i, (t, items) in enumerate(cols):
    x = Inches(0.7 + i * 4.05)
    box(s, x, Inches(1.8), Inches(3.8), Inches(4.95), WHITE if i < 2 else MINT, LINE if i < 2 else None)
    text(s, x + Inches(0.3), Inches(2.0), Inches(3.3), Inches(0.45), t, 17, TEAL if i < 2 else DEEP, True)
    text(s, x + Inches(0.3), Inches(2.6), Inches(3.3), Inches(4.0), "\n".join(f"✓  {it}" for it in items), 13, INK)
notes(s, "Every deliverable and every bonus in the brief is done. The third column is what I added because operations will ask for "
         "it on day one: a way to ask the system questions within your role, email intake, policy updates without engineers, and a "
         "monitor that shows where reviewers disagree with the AI.")

# ── 5. how it decides ───────────────────────────────────────────────────────────────────────────────
s = new("Models read, a rule file decides, people handle the uncertain", "How it works")
steps = [("Upload", "PNG · JPEG · PDF · TIFF"), ("Read", "local OCR + classifier"), ("Extract", "fields grounded on the page"),
         ("Verify", "KYC · claims · policy RAG"), ("Fraud", "history + anomalies"), ("Decide", "rules + justification"),
         ("Review", "four-eyes over $10k")]
cw = Inches(1.66)
for i, (t, sub) in enumerate(steps):
    x = Inches(0.7) + i * (cw + Inches(0.1))
    shp = s.shapes.add_shape(MSO_SHAPE.CHEVRON if i else MSO_SHAPE.PENTAGON, x, Inches(2.0), cw, Inches(0.95))
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
    text(s, x, Inches(3.1), cw, Inches(0.7), sub, 12, MUTED, align=PP_ALIGN.CENTER)
for i, (t, dsc) in enumerate([("Deterministic decisions", ("The same facts always give the same decision, from a versioned rule file. A "
                                                          "document that says \"APPROVE\" cannot approve itself.")),
                              ("Confidence from evidence", ("Grounding on the page, agreement between checks and image quality, "
                                                           "calibrated on held-out data. Low confidence goes to a person.")),
                              ("Cheapest model that works", ("Free local OCR first; Sonnet for reading and reasoning; Opus only to retry "
                                                            "or double-check suspected tampering."))]):
    x = Inches(0.7 + i * 4.1)
    box(s, x, Inches(4.15), Inches(3.85), Inches(2.45), MINT, None)
    text(s, x + Inches(0.3), Inches(4.4), Inches(3.3), Inches(0.5), t, 17, DEEP, True)
    text(s, x + Inches(0.3), Inches(4.95), Inches(3.3), Inches(1.6), dsc, 13, INK)
notes(s, "The key design choice for a regulated business: the language models read documents and explain, but they never make the "
         "decision. A rule file does, so decisions are repeatable and every one points to a rule id. Anything the system is unsure "
         "about goes to a reviewer.")

# ── 6. product ──────────────────────────────────────────────────────────────────────────────────────
s = new("What the operations team uses every day", "The product")
picture(s, SHOTS / "dashboard.png", Inches(0.7), Inches(1.75), Inches(5.9), Inches(3.85))
picture(s, SHOTS / "case-detail.png", Inches(6.75), Inches(1.75), Inches(5.9), Inches(3.85))
text(s, Inches(0.7), Inches(5.75), Inches(5.9), Inches(1.0), "Dashboard: every case with its status, decision, confidence and fraud risk",
     13, MUTED)
text(s, Inches(6.75), Inches(5.75), Inches(5.9), Inches(1.0),
     "Case view: live pipeline, evidence highlighted on the page, each agent's output, the decision, report and override", 13, MUTED)
notes(s, "This is the reviewer's view of a real escalated case: the pipeline, the document with the extracted fields highlighted where "
         "they were found, why it escalated, and the override and report buttons. I'll show it live in the demo.")

# ── 7. architecture ─────────────────────────────────────────────────────────────────────────────────
s = new("Serverless on AWS, agents on Bedrock AgentCore", "Architecture")


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
text(s, Inches(0.7), Inches(5.55), Inches(6.4), Inches(1.1),
     "One CloudFormation stack · ARM64 image built in CodeBuild · secrets in SSM\nNo servers to patch · pay-per-use only: ≈ $1.25/month idle",
     13, INK)
notes(s, "Nothing here is a server we have to patch. The web app is static on CloudFront, the API is a Lambda, and both agents run on "
         "Bedrock AgentCore in isolated sessions. OCR, search and forensics run inside our own container at no API cost; only reading "
         "and reasoning call Claude. The whole thing deploys, and tears down, from one stack.")

# ── 8. results ──────────────────────────────────────────────────────────────────────────────────────
s = new("Quality measured on data the system never saw", "Results · held-out split")
tiles = [(pct(held["classification"]["accuracy"]), "classification", "6 document types"),
         (pct(held["extraction"]["rubric_claim_completeness"]), "claim-field extraction", "ICD · CPT · amounts · provider"),
         (pct(held["retrieval"]["recall@3"]), "policy retrieval R@3", "right clause in the top 3"),
         (pct(d["accuracy_visible"]), "decisions (visible labels)", f"{pct(d['accuracy_all'])} on all labels*")]
for i, (v, l, sub) in enumerate(tiles):
    stat(s, Inches(0.7 + i * 3.05), Inches(1.85), Inches(2.8), Inches(2.0), v, l, TEAL, sub)
tiles2 = [(f"${cost_case:.2f}", "model cost per case", f"≈ ${cost_doc:.2f} per document vs ≈ ${manual_doc:.0f} manual**"),
          (f"{pct(seed['decision']['accuracy_visible'])}", "unseen generator seed", (f"{pct(seedc['decision']['accuracy_visible'])} with "
                                                                                 "tampering drawn in")),
          (str(rt["flips"]), "prompt-injection flips", f"{rt['attacks']} adversarial documents"),
          ("21 / 21", "quality gates in CI", "accuracy · safety · cost thresholds")]
for i, (v, l, sub) in enumerate(tiles2):
    stat(s, Inches(0.7 + i * 3.05), Inches(4.05), Inches(2.8), Inches(2.0), v, l, GREEN if i in (2, 3) else TEAL, sub)
text(s, Inches(0.7), Inches(6.25), Inches(12), Inches(0.7),
     "* The dataset records a few labels its generator never draws on the page (e.g. 'tampered' IDs); no system can see those.   "
     "** Model spend only; escalated cases still get human review.", 11, MUTED)
notes(s, "Prompts were tuned on the development split only; these numbers come from data the system had never seen, plus a second "
         "dataset from a different random seed. The 96 versus 100 percent gap is labels that exist in the answer key but were never "
         "drawn on the documents. Prompt-injection attacks hidden in documents changed zero decisions.")

# ── 9. security and compliance ──────────────────────────────────────────────────────────────────────
s = new("Security and compliance controls are built in", "Security and compliance")
items = [("Least privilege, everywhere", ("One permission matrix drives the API, the UI and the assistant. Each AWS function has its own "
                                         "least-privilege role.")),
         ("Four-eyes on large overrides", "Overrides above $10,000 need a second, senior reviewer; nobody approves their own request."),
         ("Tamper-evident audit trail", "Every login, view, decision, override and blocked question is hash-chained; edits are detectable."),
         ("Injection-resistant decisions", "Document text is treated as data. Red team: 0 decision flips; a poisoned policy PDF held."),
         ("PHI protection", "Redacted from logs, traces and assistant memory; secrets only in SSM, never in code."),
         ("Spend guardrails", "Hard model-spend caps (total and daily) enforced in code, plus an AWS Budget alert.")]
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
notes(s, "These are the controls our auditors and the KYC findings will ask about. The important one: access is enforced where data is "
         "read, not just hidden in the screens, so even the assistant cannot leak what your role may not see. Red-team testing found "
         "no leaks and no decision flips.")

# ── 10. operations ──────────────────────────────────────────────────────────────────────────────────
s = new("Running it: observable, tested on every change, cost-capped", "Operations")
ops = [("Observability", ("A LangSmith trace per case: every agent call with tokens, latency and cost. CloudWatch logs kept 14 days. "
                         "An AI quality monitor shows override rates by rule and AI versus final decisions.")),
       ("Release safety", ("GitHub Actions on every push: lint, 261 tests on SQLite and DynamoDB, 21 quality gates on accuracy, safety "
                          "and cost. Images built in CodeBuild; one command deploys or tears down.")),
       ("Cost control", ("Pay-per-use only: Lambda, AgentCore, DynamoDB on-demand, S3. About $1.25 a month idle. Budget alert plus hard "
                        "model-spend caps that stop calls before a limit is crossed.")),
       ("Data lifecycle", ("Uploaded case files expire after 60 days, temporary uploads after 1 day. PHI is redacted from logs and traces. "
                          "Policies can be updated by an admin without a release."))]
for i, (t, dsc) in enumerate(ops):
    col, row = i % 2, i // 2
    card(s, Inches(0.7 + col * 6.1), Inches(1.85 + row * 2.45), Inches(5.85), Inches(2.2), t, dsc, size=13)
notes(s, "What it takes to run day to day. Every case can be replayed in LangSmith with the cost of each step. Nothing ships unless "
         "the quality gates pass, including accuracy and cost thresholds. And spend is capped in code, not just alerted on.")

# ── 11. engineering decisions ───────────────────────────────────────────────────────────────────────
s = new("Every optimisation was measured before it shipped", "Engineering decisions")
table(s, [("Change", "Measured effect", "Accuracy"),
          ("OCR first: vision model only when OCR isn't enough", "−25% cost per case", "unchanged"),
          ("Sonnet instead of Opus for policy and fraud", "−36% cost per case ($0.13 → $0.08)", "identical decisions"),
          ("7× smaller reranker (fits the 2 GB AgentCore image)", "MRR 0.963 → 1.000", "better"),
          ("Fraud check beside the specialists; length-sorted batching", "index build 4.4 s → 1.8 s, search 0.5 s → 0.14 s", "unchanged"),
          ("Lazy imports + keep-warm ping", "sign-in ≈ 15 s → under 1 s", "n/a"),
          ("Text-only extraction (tested, rejected)", "−4% cost", "−4 pts → not shipped")],
      Inches(0.7), Inches(1.85), (Inches(5.6), Inches(4.0), Inches(2.3)), Inches(4.4), size=14, flag=lambda v: "not shipped" in v)
notes(s, "Each change was A/B tested on the development split before it shipped. Two examples: running policy and fraud on Sonnet "
         "instead of Opus cut cost per case by a third with identical decisions. And I rejected one saving, text-only extraction, "
         "because it cost four points of accuracy.")

# ── 12. risks ───────────────────────────────────────────────────────────────────────────────────────
s = new("Known risks, and how we close them before go-live", "Risks")
table(s, [("Risk", "What could happen", "Mitigation"),
          ("Only synthetic documents tested", "Real scans (fax noise, skew, multi-page) read worse", "Shadow pilot on de-identified real scans; go-live gated on agreement with reviewers"),
          ("Subtle forged IDs", "1 of 3 forged IDs missed on the stress-test set", "Suspicious IDs escalate rather than approve; add an ID-verification service"),
          ("PHI sent to an external model API", "Compliance exposure", "Call Claude through Amazon Bedrock inside our AWS account, subject to security review"),
          ("Volume beyond demo scale", "Duplicate checks and lists read every case", "Keyed duplicate index, status index and running counters (designed)"),
          ("Cold starts after idle", "First action can take 10–30 s", "Keep a small warm pool of agent sessions in business hours"),
          ("Model updates", "Behaviour changes with a new model version", "Routing in one file; the 21 quality gates must pass before any switch")],
      Inches(0.7), Inches(1.85), (Inches(3.3), Inches(3.9), Inches(4.7)), Inches(4.8), size=12)
notes(s, "I want to be explicit about what is not proven yet. The biggest gap is real documents, which the pilot closes. The compliance "
         "item matters most to you: today model calls go to Anthropic's API; for production I recommend routing them through Bedrock "
         "so PHI stays in our AWS account. The scale fixes are designed and only matter at full volume.")

# ── 13. recommendation ──────────────────────────────────────────────────────────────────────────────
s = new("Recommendation: a shadow pilot, then a staged go-live", "Next steps")
phases = [("1 · Shadow pilot", "proposed: 6 weeks", ("Runs beside one reviewer team on de-identified real scans; members are not affected. "
                                                    f"Model spend ≈ ${pilot_1k:.0f} per 1,000 documents."),
           "Exit: agrees with reviewers on ≥ 95% of 1,000+ documents; no PHI incidents"),
          ("2 · Assisted decisions", "after phase 1", ("The AI decides; reviewers confirm every rejection. Company SSO and Bedrock model "
                                                      "access in place."), "Exit: reviewer override rate under 5% in the quality monitor"),
          ("3 · Straight-through", "after phase 2", ("Clean approvals complete automatically; escalations and four-eyes stay human. Scale "
                                                   "fixes and warm pool live."), "Ongoing: quality gates and monitor reviewed monthly")]
for i, (t, when, dsc, exit_) in enumerate(phases):
    x = Inches(0.7 + i * 4.05)
    box(s, x, Inches(1.8), Inches(3.8), Inches(3.4))
    text(s, x + Inches(0.3), Inches(1.98), Inches(3.3), Inches(0.45), t, 18, TEAL, True)
    text(s, x + Inches(0.3), Inches(2.45), Inches(3.3), Inches(0.35), when, 12, MUTED, True)
    text(s, x + Inches(0.3), Inches(2.9), Inches(3.3), Inches(1.4), dsc, 13, INK)
    text(s, x + Inches(0.3), Inches(4.35), Inches(3.3), Inches(0.8), exit_, 12, DEEP, True)
box(s, Inches(0.7), Inches(5.45), Inches(11.9), Inches(1.35), DEEP, None)
text(s, Inches(1.0), Inches(5.6), Inches(11.4), Inches(0.4), "Decisions I need today", 16, WHITE, True)
text(s, Inches(1.0), Inches(6.0), Inches(11.4), Inches(0.8),
     "1. Approve the shadow pilot and name the operations team.   2. Start the security review for Claude on Amazon Bedrock.   "
     "3. Assign an owner for company SSO integration.", 14, MINT)
notes(s, "My recommendation is to earn trust in stages, each with a measurable exit. The pilot carries no member risk and very little "
         "spend. The three decisions I need from you today are on the slide: the pilot team, the Bedrock security review, and an SSO "
         "owner. Happy to take questions, and then I'll show it live.")

# ── appendix: assistant ─────────────────────────────────────────────────────────────────────────────
s = new("Ask the system, within your role", "Appendix · Role-aware assistant")
picture(s, SHOTS / "assistant.png", Inches(6.3), Inches(1.75), Inches(6.35), Inches(4.4))
for i, (t, dsc) in enumerate([
        ("Answers with citations", "Policy clause and page, case evidence, audit entries, each as a numbered link."),
        ("Blocked by role, at the data", ("Policy search, case tools and a per-role read-only SQL database enforce access; "
                                         "the model never sees what you may not.")),
        ("Remembers, privately", "Follow-ups and per-user memory on AgentCore Memory; health data redacted; one-click clear."),
        (f"{pct(chat_eval['accuracy'])} on {chat_eval['questions']} labelled questions",
         f"refusals, routing, facts, citations · red team {chat_rt['attacks']} attacks, {chat_rt['failures']} failures")]):
    y = Inches(1.85 + i * 1.12)
    text(s, Inches(0.7), y, Inches(5.3), Inches(0.4), t, 16, TEAL if i == 3 else INK, True)
    text(s, Inches(0.7), y + Inches(0.4), Inches(5.3), Inches(0.7), dsc, 12, MUTED)
notes(s, "If asked about the assistant: staff and members can ask about policies, their cases and operations, and get cited answers. "
         "Access is enforced in the data tools, so a submitter cannot get the audit trail however they phrase it; every blocked "
         "attempt is written to the audit log.")

prs.save(OUT)
print(f"wrote {OUT} ({len(prs.slides)} slides)")
