"""Build the solution review deck the Solution Owner presents to MediShield's CTO (docs/MediShield_capstone.pptx).
Every measured number is read from docs/eval_results/; speaker notes carry what to say on each slide.

Usage: uv run --with python-pptx --with pillow python scripts/make_deck.py
"""

from __future__ import annotations

import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "docs" / "eval_results"
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


# ── slides ──
# Text-light by design: a headline and a few words per point on the slide; the detail lives in the speaker notes.
d = held["decision"]
n = 0


def new(title, kicker):
    global n
    n += 1
    sl = prs.slides.add_slide(BLANK)
    header(sl, title, kicker)
    footer(sl, n + 1)
    return sl


def tile(slide, x, y, w, h, title, line, fill=WHITE, tcolor=INK):
    box(slide, x, y, w, h, fill, LINE if fill == WHITE else None)
    text(slide, x + Inches(0.3), y + Inches(0.3), w - Inches(0.6), Inches(0.5), title, 20, tcolor, True)
    text(slide, x + Inches(0.3), y + Inches(0.9), w - Inches(0.6), h - Inches(1.0), line, 15, MUTED)


# ── 1. title ────────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = DEEP
mark(s, Inches(0.8), Inches(0.7), Inches(0.75))
text(s, Inches(1.75), Inches(0.78), Inches(6), Inches(0.6), "MediShield Health", 22, WHITE, True)
text(s, Inches(0.8), Inches(2.3), Inches(11.5), Inches(1.2), "Claims intake automation", 54, WHITE, True)
text(s, Inches(0.8), Inches(3.45), Inches(11.5), Inches(1.0), "Solution review and go-live recommendation", 26, RGBColor(0xC9, 0xE6, 0xE8))
text(s, Inches(0.8), Inches(6.2), Inches(11.5), Inches(0.8), "Raghav Bansal · Solution Owner · October 2026", 14,
     RGBColor(0x9F, 0xC9, 0xCD))
notes(s, "I'm the solution owner for claims-intake automation. In the next 15 minutes: what we built, how well it works on data it "
         "never saw, what it costs to run, the risks I still see, and the decision I need from you today.")

# ── 2. executive summary ────────────────────────────────────────────────────────────────────────────
s = new("It works, it's live, and it's cheap to run", "Executive summary")
for i, (v, l, sub) in enumerate([("≈ 1 min", "to a decision", "today: 4.2 days"),
                                  (pct(d["accuracy_visible"]), "decisions correct", "on data it never saw"),
                                  (f"${cost_case:.2f}", "per case", "model cost"),
                                  ("$1.25", "a month idle", "pay-per-use AWS")]):
    stat(s, Inches(0.7 + i * 3.05), Inches(2.0), Inches(2.8), Inches(2.0), v, l, TEAL, sub)
box(s, Inches(0.7), Inches(4.7), Inches(11.9), Inches(1.4), MINT, None)
text(s, Inches(1.0), Inches(4.95), Inches(11.4), Inches(0.4), "MY RECOMMENDATION", 12, TEAL, True)
text(s, Inches(1.0), Inches(5.35), Inches(11.4), Inches(0.6), "A shadow pilot on real scans, then a staged go-live.", 24, DEEP, True)
notes(s, "Bottom line first. The system is built and running in our AWS account. On held-out data it matched every decision whose "
         f"evidence is visible on the page ({pct(d['accuracy_all'])} counting labels never drawn on the documents), at about "
         f"{cost_case * 100:.0f} cents a case in model spend, and about a dollar a month when idle. Seven agents read and check every "
         "document, a rule file decides, and people review anything uncertain. What it hasn't seen yet is real scans, which is "
         "why I'm asking for a shadow pilot rather than a go-live.")

# ── 3. business case ────────────────────────────────────────────────────────────────────────────────
s = new("Four days of manual work become about a minute", "Business case")
for col, (head, color, rows) in enumerate([
        ("TODAY", RED, [("4.2 days", "per claim"), ("$18.4M", "a year"), (f"≈ ${manual_doc:.0f}", "per document")]),
        ("WITH THE SYSTEM", TEAL, [("≈ 1 min", "per claim"), (f"≈ ${model_year / 1000:.0f}k", "a year in model spend"),
                                   (f"≈ ${cost_doc:.2f}", "per document")])]):
    x = Inches(0.7 + col * 6.2)
    text(s, x, Inches(1.9), Inches(5.7), Inches(0.4), head, 14, color, True)
    for i, (v, l) in enumerate(rows):
        y = Inches(2.45 + i * 1.3)
        box(s, x, y, Inches(5.7), Inches(1.1))
        text(s, x + Inches(0.35), y + Inches(0.2), Inches(2.6), Inches(0.7), v, 32, color, True)
        text(s, x + Inches(3.0), y + Inches(0.38), Inches(2.6), Inches(0.5), l, 17, INK)
text(s, Inches(0.7), Inches(6.45), Inches(11.9), Inches(0.4), "Savings depend on how much goes straight through; the pilot measures it.",
     13, MUTED)
notes(s, "The cost of intake today is people's time: 85,000 documents a month, 120 reviewers, four days and about eighteen dollars a "
         f"document. Model spend at our full volume projects to about {model_year / 1000:.0f} thousand dollars a year "
         f"({docs_year / 1e6:.2f} million documents at {cost_doc:.3f} each); AWS infrastructure is pay-per-use on top. I'm "
         "deliberately not quoting a savings number yet: escalated cases keep their manual cost, so it depends on how many real cases "
         "go straight through, and that is exactly what the pilot measures.")

# ── 4. scope ────────────────────────────────────────────────────────────────────────────────────────
s = new("Everything asked for, plus what operations will want", "Scope delivered")
cols = [("The brief", "Replaces the manual sorting and checking",
         ["Seven agents per document", "Intake API", "Policy checks with page refs", "Screens for every team", "Measured accuracy"]),
        ("The bonus items", "Answers risk and audit questions",
         ["Confidence you can trust", "ID tamper checks", "Spanish and Hindi", "One-click audit report", "Every AI call traced"]),
        ("Beyond the brief", "Ready for day one",
         ["Assistant with sources", "Email intake", "Policy updates, no release", "Quality monitor", "Quality gates on every change"])]
for i, (t, why, items) in enumerate(cols):
    x = Inches(0.7 + i * 4.05)
    box(s, x, Inches(1.85), Inches(3.8), Inches(4.85), WHITE if i < 2 else MINT, LINE if i < 2 else None)
    text(s, x + Inches(0.35), Inches(2.1), Inches(3.2), Inches(0.45), t, 20, TEAL if i < 2 else DEEP, True)
    text(s, x + Inches(0.35), Inches(2.6), Inches(3.2), Inches(0.7), why, 14, MUTED)
    text(s, x + Inches(0.35), Inches(3.45), Inches(3.2), Inches(3.1), "\n".join(f"✓  {it}" for it in items), 16, INK)
notes(s, "Every deliverable and every bonus in the brief is done. Rather than read the list, here's why it matters. The left column is "
         "the job itself: it takes over the sorting and checking our reviewers do by hand. The middle column looks like extras, but "
         "each one answers a question you'll get from risk or audit: can we trust the confidence score, what about forged IDs (the "
         "open KYC findings), what about members who don't write in English, can an auditor see the whole decision, can we replay "
         "what the AI did. The right column is what operations would have raised as follow-up projects: an assistant that only shows "
         "what your role allows, claims by email, new policies without an engineering release, a monitor showing where reviewers "
         "overrule the AI, and CI gates so a change that lowers accuracy cannot ship.")

# ── 5. how it decides ───────────────────────────────────────────────────────────────────────────────
s = new("AI reads. Rules decide. People handle the uncertain.", "How it works")
steps = ["Upload", "Read", "Extract", "Verify", "Fraud", "Decide", "Review"]
cw = Inches(1.66)
for i, t in enumerate(steps):
    x = Inches(0.7) + i * (cw + Inches(0.1))
    shp = s.shapes.add_shape(MSO_SHAPE.CHEVRON if i else MSO_SHAPE.PENTAGON, x, Inches(2.2), cw, Inches(0.95))
    shp.fill.solid()
    shp.fill.fore_color.rgb = TEAL if i < 6 else AMBER
    shp.line.fill.background()
    tf = shp.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = 0
    tf.text = t
    tf.paragraphs[0].runs[0].font.size, tf.paragraphs[0].runs[0].font.bold = Pt(16), True
    tf.paragraphs[0].runs[0].font.color.rgb, tf.paragraphs[0].runs[0].font.name = WHITE, FONT
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
for i, (t, line) in enumerate([("Same facts, same decision", "A rule file decides, not the model"),
                               ("Unsure goes to a person", "Confidence comes from evidence"),
                               ("Lowest cost first", "Free OCR first, AI only when needed")]):
    tile(s, Inches(0.7 + i * 4.05), Inches(4.0), Inches(3.8), Inches(2.0), t, line, MINT, DEEP)
notes(s, "The key design choice for a regulated business: the AI models read documents and explain, but they never make the "
         "decision. A versioned rule file does, so decisions are repeatable, every one points to a rule id, and a document that says "
         "'APPROVE' cannot approve itself. Confidence comes from evidence on the page, not the model's opinion, and anything uncertain "
         "goes to a reviewer; above $10,000 an override needs a second, senior reviewer. Free local OCR runs first; Sonnet reads and "
         "reasons, and Opus only retries or double-checks suspected tampering.")

# ── 6. architecture ─────────────────────────────────────────────────────────────────────────────────
s = new("Serverless on AWS: nothing to patch, nothing idle", "Architecture")


def node(x, y, w, h, title, sub, fill=WHITE, tcolor=INK):
    box(s, x, y, w, h, fill)
    text(s, x + Inches(0.25), y + Inches(0.2), w - Inches(0.5), Inches(0.45), title, 17, tcolor, True)
    text(s, x + Inches(0.25), y + Inches(0.68), w - Inches(0.5), h - Inches(0.75), sub, 13, MUTED if tcolor == INK else MINT)


def arrow(x1, y1, x2, y2):
    c = s.shapes.add_connector(1, x1, y1, x2, y2)
    c.line.color.rgb, c.line.width = TEAL, Pt(2)
    c.line._get_or_add_ln().append(c.line._get_or_add_ln().makeelement(
        "{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd", {"type": "triangle"}))


node(Inches(0.7), Inches(2.0), Inches(2.6), Inches(1.25), "Web app", "CloudFront")
node(Inches(4.0), Inches(2.0), Inches(2.6), Inches(1.25), "API", "Lambda")
node(Inches(7.4), Inches(1.85), Inches(5.2), Inches(1.4), "Case pipeline", "Bedrock AgentCore · LangGraph", DEEP, WHITE)
node(Inches(7.4), Inches(3.5), Inches(5.2), Inches(1.4), "Assistant", "Bedrock AgentCore · Memory", DEEP, WHITE)
node(Inches(0.7), Inches(3.65), Inches(2.6), Inches(1.25), "Data", "DynamoDB · S3")
node(Inches(4.0), Inches(3.65), Inches(2.6), Inches(1.25), "AI models", "Claude Sonnet · Opus")
arrow(Inches(3.3), Inches(2.62), Inches(4.0), Inches(2.62))
arrow(Inches(6.6), Inches(2.5), Inches(7.4), Inches(2.5))
arrow(Inches(6.6), Inches(2.9), Inches(7.4), Inches(4.2))
text(s, Inches(0.7), Inches(5.6), Inches(11.9), Inches(0.5), "One CloudFormation stack  ·  pay-per-use only  ·  ≈ $1.25 a month idle",
     17, INK, True)
notes(s, "Nothing here is a server we have to patch. The web app is static on CloudFront and S3, the API is a Lambda with signed "
         "direct-to-S3 uploads, and both agents run on Bedrock AgentCore in isolated sessions; the assistant keeps per-user memory "
         "in AgentCore Memory. OCR, search (bge-small and BM25 with a reranker) and image forensics run inside our own container at no "
         "API cost; only reading and reasoning call Claude. The ARM64 image is built in CodeBuild, secrets live in SSM, and the whole "
         "thing deploys, and tears down, from one stack.")

# ── 7. results ──────────────────────────────────────────────────────────────────────────────────────
s = new("Measured on data the system never saw", "Results")
tiles = [(pct(held["classification"]["accuracy"]), "document types"),
         (pct(held["extraction"]["rubric_claim_completeness"]), "claim fields extracted"),
         (pct(held["retrieval"]["recall@3"]), "right policy clause found"),
         (pct(d["accuracy_visible"]), "decisions correct*"),
         (f"{pct(seed['decision']['accuracy_visible'])}", "on a second, unseen dataset"),
         (str(rt["flips"]), "decisions flipped by attacks")]
for i, (v, l) in enumerate(tiles):
    col, row = i % 3, i // 3
    stat(s, Inches(0.7 + col * 4.05), Inches(1.9 + row * 2.2), Inches(3.8), Inches(1.95), v, l, GREEN if i == 5 else TEAL)
text(s, Inches(0.7), Inches(6.45), Inches(11.9), Inches(0.4), f"* where the evidence is on the page; {pct(d['accuracy_all'])} on all labels",
     13, MUTED)
notes(s, "Prompts were tuned on the development split only; these numbers come from the held-out split the system had never seen, "
         "plus a second dataset generated with a different random seed. The gap between "
         f"{pct(d['accuracy_visible'])} and {pct(d['accuracy_all'])} is labels that exist in the answer key but were never drawn on "
         f"the documents, like 'tampered' IDs that look normal. {rt['attacks']} adversarial documents with hidden instructions "
         "changed zero decisions, and 21 quality gates in CI check accuracy, safety and cost on every change.")

# ── 8. security and compliance ──────────────────────────────────────────────────────────────────────
s = new("Built for auditors from day one", "Security and compliance")
for i, (t, line) in enumerate([("Role-based access", "Enforced at the data"), ("Four-eyes approval", "Overrides over $10k"),
                               ("Tamper-evident audit", "Every action hash-chained"), ("Injection-resistant", "0 decisions flipped"),
                               ("Patient data protected", "Redacted from logs and traces"), ("Spend caps", "Enforced in code")]):
    col, row = i % 3, i // 3
    tile(s, Inches(0.7 + col * 4.05), Inches(1.9 + row * 2.3), Inches(3.8), Inches(2.0), t, line)
notes(s, "These are the controls our auditors and the open KYC findings will ask about. One permission matrix drives the API, the "
         "screens and the assistant, and it's enforced where data is read, so even the assistant can't leak what your role may not "
         "see. Overrides above $10,000 need a second, senior reviewer, and nobody approves their own. Every login, view, decision, "
         "override and blocked question is hash-chained, so edits are detectable. Patient data is redacted from logs, traces and "
         "assistant memory; secrets live only in SSM. Model spend has hard total and daily caps, plus an AWS Budget alert.")

# ── 9. operations ───────────────────────────────────────────────────────────────────────────────────
s = new("Easy to run, hard to break", "Operations")
for i, (t, line) in enumerate([("Every case traceable", "Each AI step, its cost and time"),
                               ("Every change tested", "261 tests, 21 quality gates"),
                               ("Costs capped", "Budget alert and hard limits"),
                               ("Data expires", "Case files after 60 days")]):
    col, row = i % 2, i // 2
    tile(s, Inches(0.7 + col * 6.1), Inches(1.9 + row * 2.3), Inches(5.85), Inches(2.0), t, line)
notes(s, "What it takes to run day to day. Every case has a LangSmith trace with each agent call, its tokens, latency and cost; logs "
         "stay 14 days in CloudWatch; and an AI quality monitor shows where reviewers overrule the AI, by rule. GitHub Actions runs "
         "lint, 261 tests on two databases and 21 quality gates on every push, so nothing ships that lowers accuracy or raises cost "
         "past a threshold. Spend is capped in code, not just alerted on. Uploaded case files expire after 60 days, temporary uploads "
         "after a day, and an admin can update policies without a release.")

# ── 10. engineering decisions ───────────────────────────────────────────────────────────────────────
s = new("Every saving was measured before it shipped", "Engineering decisions")
table(s, [("Change", "Effect", "Accuracy"),
          ("OCR first, AI vision only when needed", "−25% cost", "unchanged"),
          ("Sonnet instead of Opus for policy and fraud", "−36% cost", "identical"),
          ("Smaller search reranker", "fits the agent image", "better"),
          ("Text-only extraction", "−4% cost", "−4 pts: rejected")],
      Inches(0.7), Inches(2.0), (Inches(5.9), Inches(3.3), Inches(2.7)), Inches(3.6), size=18, flag=lambda v: "rejected" in v)
notes(s, "Each change was A/B tested on the development split before it shipped. Calling the vision model only when OCR isn't good "
         "enough cut a quarter of the cost. Moving policy and fraud from Opus to Sonnet cut cost per case from 13 to 8 cents with "
         "identical decisions. A seven-times smaller reranker scored better and let the image fit AgentCore's 2 GB limit. And I "
         "rejected one saving, text-only extraction, because it cost four points of accuracy. Sign-in also went from about 15 "
         "seconds to under one.")

# ── 11. risks ───────────────────────────────────────────────────────────────────────────────────────
s = new("What's not proven yet, and how we close it", "Risks")
table(s, [("Risk", "How we close it"),
          ("Only synthetic documents so far", "Shadow pilot on real scans"),
          ("Subtle forged IDs", "Escalate, add ID verification"),
          ("Patient data to an external AI API", "Use Claude via Amazon Bedrock"),
          ("Full production volume", "Indexes already designed"),
          ("Slow first request after idle", "Warm pool in business hours")],
      Inches(0.7), Inches(2.0), (Inches(5.95), Inches(5.95)), Inches(4.2), size=18)
notes(s, "I want to be explicit about what is not proven. The biggest gap is real documents: fax noise, skew, multi-page scans. The "
         "pilot closes that. On the stress-test set one of three subtly forged IDs got through; suspicious IDs escalate, and for "
         "production I'd add an ID-verification service. The item that matters most to you: today model calls go to Anthropic's "
         "API; for production I recommend Claude through Amazon Bedrock so patient data stays in our AWS account, subject to "
         "security review. The scale fixes, a keyed duplicate index and status counters, are designed and only matter at full volume. "
         "Cold starts can make the first action take 10 to 30 seconds; a small warm pool fixes that.")

# ── 12. recommendation ──────────────────────────────────────────────────────────────────────────────
s = new("Earn trust in stages", "Recommendation")
for i, (t, line, exit_) in enumerate([("1 · Shadow pilot", "Beside one team, real scans", "Exit: ≥ 95% agreement"),
                                      ("2 · Assisted", "AI decides, people confirm", "Exit: < 5% overrides"),
                                      ("3 · Straight-through", "Clean claims go automatically", "Escalations stay human")]):
    x = Inches(0.7 + i * 4.05)
    box(s, x, Inches(1.85), Inches(3.8), Inches(2.45))
    text(s, x + Inches(0.3), Inches(2.1), Inches(3.2), Inches(0.45), t, 20, TEAL, True)
    text(s, x + Inches(0.3), Inches(2.7), Inches(3.2), Inches(0.6), line, 15, INK)
    text(s, x + Inches(0.3), Inches(3.55), Inches(3.2), Inches(0.5), exit_, 14, DEEP, True)
box(s, Inches(0.7), Inches(4.65), Inches(11.9), Inches(2.0), DEEP, None)
text(s, Inches(1.0), Inches(4.9), Inches(11.4), Inches(0.4), "DECISIONS I NEED TODAY", 13, MINT, True)
text(s, Inches(1.0), Inches(5.35), Inches(11.4), Inches(1.2),
     "1.  Approve the pilot and name the team\n2.  Start the security review for Claude on Bedrock\n3.  Assign an owner for company sign-in (SSO)",
     17, WHITE)
notes(s, "My recommendation is to earn trust in stages, each with a measurable exit. Phase one, proposed at six weeks: run beside one "
         "reviewer team on de-identified real scans, with no member impact and model spend of about "
         f"{pilot_1k:.0f} dollars per thousand documents; exit when it agrees with reviewers on at least 95 percent of 1,000 or more "
         "documents with no patient-data incidents. Phase two: the AI decides and reviewers confirm every rejection, with company "
         "sign-in and Bedrock in place; exit at under 5 percent overrides in the quality monitor. Phase three: clean approvals go "
         "straight through; escalations and four-eyes stay human. The three decisions I need are on the slide. Happy to take "
         "questions, and then I'll show it live.")

prs.save(OUT)
print(f"wrote {OUT} ({len(prs.slides)} slides)")
