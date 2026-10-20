"""Build the stakeholder deck (docs/MediShield_capstone.pptx): a seven-slide story, then a short appendix.

Problem -> idea -> how it works (diagram) -> does it work -> is it safe -> what's next. Plain language for a non-technical
audience. Every measured number is read from docs/eval_results/, and the read-aloud script sits in each slide's speaker notes.

Usage: uv run --with python-pptx python scripts/make_deck.py
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
DIAGRAM = REPO / "docs" / "diagrams" / "claim_flow.png"

# dark theme
BG = RGBColor(0x0B, 0x12, 0x20)
CARD = RGBColor(0x11, 0x1A, 0x2E)
CARD2 = RGBColor(0x16, 0x22, 0x3A)
LINE = RGBColor(0x23, 0x30, 0x47)
TEXT = RGBColor(0xF8, 0xFA, 0xFC)
SOFT = RGBColor(0xCB, 0xD5, 0xE1)
MUTED = RGBColor(0x94, 0xA3, 0xB8)
TEAL = RGBColor(0x2D, 0xD4, 0xBF)
TEAL_DARK = RGBColor(0x0F, 0x76, 0x6E)
GREEN = RGBColor(0x4A, 0xDE, 0x80)
RED = RGBColor(0xF8, 0x71, 0x71)
AMBER = RGBColor(0xFB, 0xBF, 0x24)
FONT = "Calibri"
W, H = Inches(13.333), Inches(7.5)


def load(name: str) -> dict:
    return json.loads((RES / f"{name}.json").read_text())


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".0%", "%")


held, ml_dev, ml_held = load("official-heldout"), load("multilingual-dev"), load("multilingual-heldout")
rt, chat = load("redteam"), load("chat_eval")
d = held["decision"]
cost_case, cost_doc = held["ops"]["cold_cost_per_case_usd"], held["ops"]["cold_cost_per_doc_usd"]
manual_doc = 18.4e6 / (85_000 * 12)
ml_docs = ml_dev["classification"]["n"] + ml_held["classification"]["n"]
ml_lo, ml_hi = sorted([ml_dev["decision"]["accuracy_all"], ml_held["decision"]["accuracy_all"]])
judge = chat.get("judge", {})

prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]
n = 0


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────────
def text(slide, x, y, w, h, s, size=18, color=TEXT, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
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
        r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(size), bold, color, FONT
    return tb


def box(slide, x, y, w, h, fill=CARD, line=LINE):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
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


def mark(slide, x, y, size):
    s = slide.shapes.add_shape(MSO_SHAPE.PENTAGON, x, y, size, size)
    s.rotation = 90
    s.fill.solid()
    s.fill.fore_color.rgb = TEAL
    s.line.fill.background()
    arm, long = int(size * 0.18), int(size * 0.56)
    cx, cy = x + size // 2, y + int(size * 0.46)
    for ww, hh in ((arm, long), (long, arm)):
        c = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, cx - ww // 2, cy - hh // 2, ww, hh)
        c.fill.solid()
        c.fill.fore_color.rgb = BG
        c.line.fill.background()


def notes(slide, s):
    slide.notes_slide.notes_text_frame.text = s


def new(title, kicker):
    """A dark slide with a kicker, a title, the mark and a footer with the slide number."""
    global n
    n += 1
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, Inches(0.1))
    bar.fill.solid()
    bar.fill.fore_color.rgb = TEAL
    bar.line.fill.background()
    text(s, Inches(0.7), Inches(0.45), Inches(10), Inches(0.35), kicker.upper(), 12, TEAL, True)
    text(s, Inches(0.7), Inches(0.75), Inches(11.2), Inches(0.8), title, 32, TEXT, True)
    mark(s, Inches(12.25), Inches(0.42), Inches(0.42))
    text(s, Inches(0.7), Inches(7.05), Inches(8), Inches(0.3), "MediShield Health · Claims intake automation", 10, MUTED)
    text(s, Inches(11.9), Inches(7.05), Inches(0.8), Inches(0.3), str(n + 1), 10, MUTED, align=PP_ALIGN.RIGHT)
    return s


def stat(slide, x, y, w, h, value, label, color=TEAL, sub=None):
    box(slide, x, y, w, h)
    text(slide, x + Inches(0.25), y + Inches(0.2), w - Inches(0.5), Inches(0.8), value, 34, color, True)
    text(slide, x + Inches(0.25), y + Inches(0.95), w - Inches(0.5), Inches(0.5), label, 14, TEXT, True)
    if sub:
        text(slide, x + Inches(0.25), y + Inches(1.3), w - Inches(0.5), h - Inches(1.4), sub, 11, MUTED)


def tile(slide, x, y, w, h, title, line, accent=TEAL):
    box(slide, x, y, w, h)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y + Inches(0.25), Inches(0.06), h - Inches(0.5))
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    text(slide, x + Inches(0.3), y + Inches(0.25), w - Inches(0.5), Inches(0.5), title, 16, TEXT, True)
    text(slide, x + Inches(0.3), y + Inches(0.8), w - Inches(0.5), h - Inches(0.9), line, 14, SOFT)


def table(slide, rows, x, y, widths, h, size=14):
    tbl = slide.shapes.add_table(len(rows), len(widths), x, y, sum(widths, Inches(0)), h).table
    for c, wdt in enumerate(widths):
        tbl.columns[c].width = wdt
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = val
            run = cell.text_frame.paragraphs[0].runs[0]
            run.font.size, run.font.name, run.font.bold = Pt(size), FONT, r == 0 or c == 0
            run.font.color.rgb = BG if r == 0 else TEXT
            cell.fill.solid()
            cell.fill.fore_color.rgb = TEAL if r == 0 else (CARD if r % 2 else CARD2)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    return tbl


# ── 1. title ────────────────────────────────────────────────────────────────────────────────────────
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = BG
mark(s, Inches(0.8), Inches(0.7), Inches(0.75))
text(s, Inches(1.75), Inches(0.78), Inches(6), Inches(0.6), "MediShield Health", 22, TEXT, True)
text(s, Inches(0.8), Inches(2.3), Inches(11.8), Inches(1.2), "Claims decisions in a minute, not days", 50, TEXT, True)
text(s, Inches(0.8), Inches(3.5), Inches(11.5), Inches(1.0),
     "How we automated claims intake, what it costs, how well it works, and what I'm asking for", 24, SOFT)
text(s, Inches(0.8), Inches(6.2), Inches(11.5), Inches(0.8), "Raghav Bansal · Solution Owner · October 2026", 14, MUTED)
notes(s, "Hi, I'm Raghav Bansal, the Solution Owner for MediShield's claims-intake automation. In the next ten minutes I'll "
         "show you the problem we have today, the idea behind the fix, proof that it works, and the one decision I need "
         "from you. Then you'll see it running live.")

# ── 2. the problem ──────────────────────────────────────────────────────────────────────────────────
s = new("Every claim waits for a person to read five documents", "The problem today")
for i, (v, l, sub) in enumerate([("85,000", "documents a month", "claim forms, ID cards, discharge summaries, prescriptions, amendments"),
                                  ("120", "people reading them", "sorting, checking and routing by hand"),
                                  ("4.2 days", "per claim", "a member waits almost a week for an answer"),
                                  ("$18.4M", "a year", f"about ${manual_doc:.0f} of handling for every document")]):
    stat(s, Inches(0.7 + i * 3.05), Inches(1.95), Inches(2.8), Inches(2.3), v, l, RED if i == 3 else TEAL, sub)
box(s, Inches(0.7), Inches(4.7), Inches(11.9), Inches(1.55), CARD2, None)
text(s, Inches(1.0), Inches(4.9), Inches(11.4), Inches(0.4), "WHAT GOES WRONG", 12, TEAL, True)
text(s, Inches(1.0), Inches(5.3), Inches(11.4), Inches(0.9),
     "Slow answers for members. 12% of documents handled twice. Three open regulatory audits on identity checks. "
     "And when a decision is questioned, nobody can show exactly why it was made.", 17, TEXT)
notes(s, "Here's the problem. Every month 85,000 documents arrive, and 120 people read every one by hand. A claim waits 4.2 days, and the handling costs 18.4 million dollars a year, about 18 dollars a document. It's not just slow. One in eight documents is handled twice, we have three open audits on identity checks, and when someone asks why a claim was rejected, nobody can show exactly how the decision was made.")

# ── 3. the idea ─────────────────────────────────────────────────────────────────────────────────────
s = new("Software reads. A rulebook decides. People judge.", "The idea")
cols = [("1 · Software reads", ("Seven specialist 'clerks', each an AI agent: one identifies the document, one checks identity, "
                               "one checks medical codes and amounts, one checks the policy, one looks for fraud."), TEAL),
        ("2 · A rulebook decides", ("The AI never decides. It reports facts. A written rulebook turns those facts into Approve, "
                                    "Reject or Escalate, so the same facts always give the same answer."), AMBER),
        ("3 · People handle doubt", ("Anything uncertain goes to a reviewer. A big override needs a second signature from a "
                                     "senior reviewer. Every click is written to a tamper-proof logbook."), GREEN)]
for i, (t, body, col) in enumerate(cols):
    x = Inches(0.7 + i * 4.05)
    box(s, x, Inches(1.95), Inches(3.8), Inches(3.4))
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, Inches(2.25), Inches(0.06), Inches(2.8))
    bar.fill.solid()
    bar.fill.fore_color.rgb = col
    bar.line.fill.background()
    text(s, x + Inches(0.35), Inches(2.2), Inches(3.2), Inches(0.5), t, 20, col, True)
    text(s, x + Inches(0.35), Inches(2.85), Inches(3.2), Inches(2.4), body, 15, SOFT)
box(s, Inches(0.7), Inches(5.65), Inches(11.9), Inches(1.0), CARD2, None)
text(s, Inches(1.0), Inches(5.78), Inches(11.4), Inches(0.8),
     "Works on documents in English, Spanish and Hindi.  ·  Accepts claims by web upload or by email.  ·  "
     "Answers staff questions in plain English, with the policy page cited.", 15, TEXT)
notes(s, 'The idea, in one sentence: software does the reading, people keep the judgement. Picture a mailroom with seven specialist clerks, each one an AI agent. One identifies the document, one checks identity and tampering, one checks medical codes and amounts, one checks the policy, one looks for fraud. The important part: the AI never decides. It reports facts, and a written rulebook turns them into Approve, Reject or Escalate. Same facts, same answer, every time. Anything uncertain goes to a person, and a big override needs a second signature. It reads Spanish and Hindi as well as English, takes claims by email, and staff can ask it questions and get the policy page cited back.')

# ── 4. how it works (diagram) ───────────────────────────────────────────────────────────────────────
n += 1
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = BG
s.shapes.add_picture(str(DIAGRAM), 0, 0, width=W, height=H)
notes(s, "This is how a claim flows. Documents come in at the top and are read by an OCR engine inside our own environment, at no cost. The classifier identifies each document from its printed title, and only asks the AI vision model when that isn't clear. Then the four specialists run at the same time: identity, claims, policy and fraud. Everything lands in the decision engine, where the rulebook decides. Escalations go to a reviewer; large overrides need a second signature. On the right is what wraps every case: the web app, the assistant, the tamper-proof audit trail, tracing of every AI call with its cost, and the platform: serverless on AWS, one stack, about a dollar a month idle.")

# ── 5. does it work ─────────────────────────────────────────────────────────────────────────────────
s = new("Tested on documents it had never seen", "Does it work?")
tiles = [(pct(held["classification"]["accuracy"]), "documents identified correctly", "78 documents, 6 types"),
         (pct(held["extraction"]["rubric_claim_completeness"]), "claim fields read correctly", "codes, amounts, provider"),
         (pct(held["retrieval"]["recall@3"]), "right policy clause found", "with the page number"),
         (pct(d["accuracy_visible"]), "decisions correct", f"{pct(d['accuracy_all'])} counting labels not drawn on the page*"),
         (f"${cost_case:.2f}", "per claim in AI cost", f"vs ≈ ${manual_doc:.0f} per document by hand"),
         ("≈ 1 min", "per claim, live on AWS", "today: 4.2 days")]
for i, (v, l, sub) in enumerate(tiles):
    col, row = i % 3, i // 3
    stat(s, Inches(0.7 + col * 4.05), Inches(1.9 + row * 2.0), Inches(3.8), Inches(1.8), v, l, TEAL, sub)
box(s, Inches(0.7), Inches(5.95), Inches(11.9), Inches(0.72), CARD2, None)
text(s, Inches(1.0), Inches(6.08), Inches(11.4), Inches(0.5),
     f"Spanish and Hindi: {ml_docs} documents, {pct(ml_dev['classification']['accuracy'])} identified correctly, "
     f"{pct(ml_lo)}–{pct(ml_hi)} decided correctly.   Whole claims (all five documents): {pct(held['cases']['accuracy'])} correct.", 15, TEXT)
text(s, Inches(0.7), Inches(6.72), Inches(11.9), Inches(0.3),
     "* Measured on a labelled test set the system never saw during development. The pilot confirms this on real scans.", 11, MUTED)
notes(s, 'Does it work? I tested it on 78 documents it had never seen. It identified every document correctly, read every required claim field correctly, and found the right policy clause with the page number every time. Decisions were 100 percent correct where the evidence is on the page, 96 percent counting a few test labels that were never drawn on the documents. Each claim costs about 8 cents in AI, against 18 dollars by hand, and takes about a minute. Spanish and Hindi: 80 documents, all identified correctly, 95 to 100 percent decided correctly. Whole claims, all five documents together: 88 percent. One honest note: this is a labelled test set. Real scans come in the pilot.')

# ── 6. is it safe ───────────────────────────────────────────────────────────────────────────────────
s = new("Safety was built in, not bolted on", "Is it safe?")
items = [("Each role sees only its data", "Enforced where data is read, not just hidden on screen. The assistant too."),
         ("Two signatures over $10,000", "Over $10,000 a senior reviewer must approve. Nobody approves their own request."),
         ("A tamper-proof logbook", "Every login, view, decision and override is chained; an edit or deletion shows."),
         ("Hidden instructions fail", f"{rt['attacks']} attack documents hid 'approve this' instructions. Decisions changed: {rt['flips']}."),
         ("A second AI checks the first", (f"A second model grades every assistant answer; it caught {judge.get('controls_caught', 3)} of "
                                            f"{judge.get('controls', 3)} planted wrong answers.")),
         ("Capped spend, private data", "AI spending is capped in code. Patient details are removed from logs and traces.")]
for i, (t, line) in enumerate(items):
    col, row = i % 3, i // 3
    tile(s, Inches(0.7 + col * 4.05), Inches(1.95 + row * 2.3), Inches(3.8), Inches(2.05), t, line)
notes(s, "Is it safe? Each role sees only its own data, enforced where the data is read, so a submitter can't talk the assistant into showing the audit trail. Overrides over ten thousand dollars need a senior's second signature, and nobody approves their own request. Every action goes into a tamper-proof logbook: each entry is chained to the one before, so edits show. Documents with hidden 'approve this' instructions: seven attacks, zero decisions changed. A second, independent AI grades every assistant answer, and it caught all three wrong answers I planted. Spending is capped in code, and patient details are stripped from logs.")

# ── 7. what's next ──────────────────────────────────────────────────────────────────────────────────
s = new("Earn trust in three stages", "What's next")
for i, (t, line, exit_) in enumerate([("1 · Shadow pilot", "Runs beside one team on real scans. Its decisions are compared, never used.",
                                        "Move on at ≥ 95% agreement with reviewers"),
                                       ("2 · Assisted", "The system recommends; a person confirms every decision.",
                                        "Move on when overrides fall below 5%"),
                                       ("3 · Straight-through", "Clean claims are approved automatically. Escalations always stay human.",
                                        "Reviewed monthly against the quality monitor")]):
    x = Inches(0.7 + i * 4.05)
    box(s, x, Inches(1.95), Inches(3.8), Inches(2.5))
    text(s, x + Inches(0.3), Inches(2.15), Inches(3.2), Inches(0.45), t, 20, TEAL, True)
    text(s, x + Inches(0.3), Inches(2.7), Inches(3.2), Inches(1.0), line, 15, SOFT)
    text(s, x + Inches(0.3), Inches(3.75), Inches(3.2), Inches(0.6), exit_, 13, GREEN, True)
box(s, Inches(0.7), Inches(4.7), Inches(5.85), Inches(1.95), CARD2, None)
text(s, Inches(1.0), Inches(4.88), Inches(5.3), Inches(0.35), "STILL TO PROVE, IN THE PILOT", 12, AMBER, True)
text(s, Inches(1.0), Inches(5.25), Inches(5.3), Inches(1.3),
     "Real scans (fax noise, skew, new policies)\nVery subtle forged ID cards\nPrivacy review of the AI provider before real patient data", 14, SOFT)
box(s, Inches(6.75), Inches(4.7), Inches(5.85), Inches(1.95), TEAL_DARK, None)
text(s, Inches(7.05), Inches(4.88), Inches(5.3), Inches(0.35), "WHAT I NEED TODAY", 12, TEXT, True)
text(s, Inches(7.05), Inches(5.25), Inches(5.3), Inches(1.3),
     "1.  Name a pilot team and an owner for disagreements\n2.  Approve the AI-provider and data-privacy review\n3.  Scope staff single sign-on",
     14, TEXT)
notes(s, "What's next? I'm not asking to switch this on for everyone. Stage one is a shadow pilot: it runs beside one reviewer team on real scans, and its decisions are compared, never used. We move on at 95 percent agreement. Stage two is assisted: the system recommends, a person confirms. We move on when overrides drop below 5 percent. Stage three, clean claims go straight through; escalations always stay human. Three things are still to prove, and the pilot proves them: real scans, subtle forged IDs, and a privacy review of the AI provider. What I need today: a pilot team and an owner, approval for the privacy review, and scoping of single sign-on. Now let me show you it working.")

# ── appendix ────────────────────────────────────────────────────────────────────────────────────────
s = new("Everything in the brief, plus what operations will want", "Appendix A · Scope delivered")
cols = [("The brief", ["Seven agents, routed by document type", "Intake API and case workflow", "Policy checks with page references",
                       "Screens for every team", "Labelled evaluation set"]),
        ("The bonus items", ["Confidence calibration", "ID tamper detection (ELA + typography)", "Spanish and Hindi documents",
                             "PDF case report", "LangSmith tracing of every AI call"]),
        ("Beyond the brief", ["Assistant with citations and memory", "Email intake", "Policy updates without a release",
                              "Review-quality monitor", "LLM judge + RAGAS; 312 tests, 28 gates in CI"])]
for i, (t, items) in enumerate(cols):
    x = Inches(0.7 + i * 4.05)
    box(s, x, Inches(1.95), Inches(3.8), Inches(4.6))
    text(s, x + Inches(0.35), Inches(2.2), Inches(3.2), Inches(0.45), t, 20, TEAL, True)
    text(s, x + Inches(0.35), Inches(2.85), Inches(3.2), Inches(3.6), "\n".join(f"✓  {it}" for it in items), 15, SOFT)
notes(s, "Appendix: every deliverable and every bonus item in the brief is done, plus the extras operations will ask for.")

s = new("Every saving was measured before it shipped", "Appendix B · Engineering decisions")
table(s, [("Change", "Measured effect", "Accuracy"),
          ("Read the text first; AI vision only when needed", "−25% cost per claim", "unchanged"),
          ("Sonnet instead of Opus for policy and fraud", "−36% cost per claim", "identical decisions"),
          ("Smaller search re-ranker", "fits the 2 GB agent image", "better"),
          ("Text-only extraction", "−4% cost", "−4 points: rejected")],
      Inches(0.7), Inches(2.0), (Inches(5.9), Inches(3.3), Inches(2.7)), Inches(3.4), size=16)
notes(s, "Appendix: each optimisation was A/B tested on the development split; the one that cost accuracy was rejected.")

s = new("Serverless on AWS, tested on every change", "Appendix C · Platform and operations")
for i, (t, line) in enumerate([("One CloudFormation stack", "CloudFront web app · Lambda API · two Bedrock AgentCore runtimes · DynamoDB · S3"),
                               ("Pay-per-use only", "≈ $1.25 a month idle; AI spend capped at $10 total and $5 a day"),
                               ("Every case traceable", "LangSmith: each agent call with tokens, latency and cost"),
                               ("Nothing ships untested", "312 tests on two databases and 28 quality gates run on every push")]):
    col, row = i % 2, i // 2
    tile(s, Inches(0.7 + col * 6.1), Inches(1.95 + row * 2.3), Inches(5.85), Inches(2.05), t, line)
notes(s, "Appendix: how it runs and how it's kept safe to change.")

prs.save(OUT)
print(f"wrote {OUT} ({len(prs.slides)} slides)")
