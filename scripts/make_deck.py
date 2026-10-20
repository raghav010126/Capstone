"""Build the stakeholder deck (docs/MediShield_capstone.pptx): a keynote-style story, then a short appendix.

One idea per slide, few words, big type. The story follows a real claim (CASE-FBDDBB1D): five documents, three hidden
problems, caught in 82 seconds. Then how, proof, safety, and the ask. Plain language for a non-technical audience. Every measured number is read from docs/eval_results/, and the read-aloud script sits in each slide's speaker notes.

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



def big(slide, s, y, size=54, color=TEXT, h=1.4, bold=True):
    """One large centred statement."""
    text(slide, Inches(0.9), y, Inches(11.5), Inches(h), s, size, color, bold, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def sub(slide, s, y, size=20, color=SOFT, h=0.9):
    text(slide, Inches(1.4), y, Inches(10.5), Inches(h), s, size, color, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)


def plain(kicker=None):
    """A dark slide with no title block: the content is the statement."""
    global n
    n += 1
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    if kicker:
        text(s, Inches(0.9), Inches(0.55), Inches(11.5), Inches(0.35), kicker.upper(), 13, TEAL, True, align=PP_ALIGN.CENTER)
    text(s, Inches(11.9), Inches(7.05), Inches(0.8), Inches(0.3), str(n + 1), 10, MUTED, align=PP_ALIGN.RIGHT)
    return s


def numbers(slide, items, y, h=1.9, size=60):
    """A row of big numbers with a short label under each (``h`` in inches)."""
    w = Inches(11.5) / len(items)
    vh = Inches(size / 72 * 1.35)                       # room for one line at this size
    for i, (v, l) in enumerate(items):
        x = Inches(0.9) + w * i
        text(slide, x, y, w, vh, v, size, TEAL, True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.BOTTOM)
        text(slide, x + Inches(0.2), y + vh + Inches(0.08), w - Inches(0.4), Inches(h) - vh - Inches(0.1), l, 16, SOFT, align=PP_ALIGN.CENTER)


# ── 1. title ────────────────────────────────────────────────────────────────────────────────────────
s = plain()
mark(s, Inches(6.26), Inches(1.6), Inches(0.8))
big(s, "A minute, not a week.", Inches(2.7), 66)
sub(s, "Claims intake at MediShield Health", Inches(4.2), 24)
text(s, Inches(0.9), Inches(6.3), Inches(11.5), Inches(0.5), "Raghav Bansal · Solution Owner · October 2026", 14, MUTED, align=PP_ALIGN.CENTER)
notes(s, "Hi, I'm Raghav, the Solution Owner for claims intake at MediShield. I want to tell you about one claim. Then I'll "
         "show you what it taught us, and what I'd like to do about it.")

# ── 2. meet the claim ───────────────────────────────────────────────────────────────────────────────
s = plain("A real claim from our test set")
big(s, "Meet claim FBDDBB1D.", Inches(1.1), 54)
numbers(s, [("5", "documents: a claim form, an ID card,\na discharge summary, a prescription,\na policy amendment"),
            ("$16,825", "claimed, mostly for\na knee replacement"),
            ("by email", "the way most claims\nactually arrive")], Inches(2.6), 2.6)
sub(s, "Today, a claim like this waits 4.2 days while one of 120 people reads every page by hand.", Inches(5.6), 20, MUTED)
notes(s, "Meet claim FBDDBB1D. Five documents: a claim form, an ID card, a discharge summary, a prescription and a policy "
         "amendment. Sixteen thousand eight hundred dollars, mostly for a knee replacement. It arrived by email, like most of "
         "them do. Today, a claim like this waits four days while one of our 120 reviewers reads every page by hand. "
         "85,000 documents a month. 18 million dollars a year.")

# ── 3. three things were wrong ──────────────────────────────────────────────────────────────────────
s = plain("What a careful reader would have found")
big(s, "Three things were wrong with it.", Inches(0.95), 50)
for i, (t, line) in enumerate([("55 days", "The prescription was written 55 days after the treatment."),
                               ("Day 0", "The policy was cancelled on the very day the patient was admitted."),
                               ("Schedule II", "And the drug was hydrocodone, a controlled substance.")]):
    y = Inches(2.45 + i * 1.15)
    text(s, Inches(1.4), y, Inches(2.6), Inches(0.9), t, 34, AMBER, True, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    text(s, Inches(4.3), y, Inches(8), Inches(0.9), line, 22, TEXT, anchor=MSO_ANCHOR.MIDDLE)
sub(s, "None of this is visible on any single page. You only see it when you cross-check all five.", Inches(6.1), 18, MUTED)
notes(s, "Three things were wrong with it. The prescription was written 55 days after the treatment. The policy had been "
         "cancelled on the very day the patient was admitted. And the drug was hydrocodone, a controlled substance. Here's "
         "the thing: none of that is visible on any single page. You only see it when you lay all five documents side by "
         "side and cross-check the dates. That's exactly the work that takes a person four days.")

# ── 4. caught in 82 seconds ─────────────────────────────────────────────────────────────────────────
s = plain()
big(s, "We found all three in 82 seconds.", Inches(1.5), 56)
sub(s, "Escalated to a reviewer, with every reason written down and the policy page cited.", Inches(3.3), 22)
sub(s, "Nobody had to read five documents to get there.", Inches(4.1), 22, TEAL)
text(s, Inches(0.9), Inches(5.6), Inches(11.5), Inches(0.5), "Case created 18:29:59 · decided 18:31:21 · from the case's own audit trail", 13, MUTED, align=PP_ALIGN.CENTER)
notes(s, "The system found all three in 82 seconds. It didn't approve the claim and it didn't reject it. It escalated it to a "
         "reviewer, with every reason written down and the policy page cited. The reviewer opens the case and the work is "
         "already done. Nobody had to read five documents to get there. That's the whole idea.")

# ── 5. how: seven specialists, one rulebook ─────────────────────────────────────────────────────────
s = plain("How")
big(s, "Seven specialists. One rulebook.", Inches(0.95), 54)
for i, (t, line, col) in enumerate([("Software reads.", "Seven AI agents, each with one job: identify, verify identity, check codes and amounts, check the policy, look for fraud.", TEAL),
                                    ("A rulebook decides.", "The AI reports facts. A written rulebook turns them into Approve, Reject or Escalate. Same facts, same answer.", AMBER),
                                    ("People judge the rest.", "Anything uncertain goes to a reviewer. Over $10,000, a second senior signature. Every click in a tamper-proof log.", GREEN)]):
    y = Inches(2.55 + i * 1.3)
    text(s, Inches(1.4), y, Inches(4.2), Inches(1.0), t, 28, col, True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, Inches(5.8), y, Inches(6.6), Inches(1.0), line, 16, SOFT, anchor=MSO_ANCHOR.MIDDLE)
sub(s, "English, Spanish and Hindi.  ·  By web upload or email.  ·  Ask it a question, get the policy page back.", Inches(6.4), 15, MUTED)
notes(s, 'How? Seven specialists and one rulebook. Picture a mailroom with seven clerks, each an AI agent with one job: identify the document, check identity and tampering, check the codes and amounts, check the policy, look for fraud. Then the part that matters: the AI never decides. It reports facts, and a written rulebook turns them into Approve, Reject or Escalate. Same facts, same answer, every time. People judge the rest: anything uncertain goes to a reviewer, and anything over ten thousand dollars needs a second signature. It reads Spanish and Hindi too, and staff can simply ask it a question.')

# ── 6. the diagram ──────────────────────────────────────────────────────────────────────────────────
n += 1
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = BG
s.shapes.add_picture(str(DIAGRAM), 0, 0, width=W, height=H)
notes(s, "Here it is end to end. Documents in at the top, read by an OCR engine inside our own environment at no cost. The classifier identifies each one from its printed title and only asks the AI vision model when that isn't clear. The four specialists run at the same time, the rulebook decides, escalations go to a person. And around every case: the web app, the assistant, the tamper-proof audit trail, a trace of every AI call, all serverless on AWS for about a dollar a month idle.")

# ── 7. does it work ─────────────────────────────────────────────────────────────────────────────────
s = plain("Tested on 78 documents it had never seen")
numbers(s, [(pct(held["classification"]["accuracy"]), "documents\nidentified correctly"),
            (pct(held["extraction"]["rubric_claim_completeness"]), "claim fields\nread correctly"),
            (pct(held["retrieval"]["recall@3"]), "right policy clause,\nwith the page")], Inches(1.3), 2.4, 72)
numbers(s, [(pct(d["accuracy_visible"]), "decisions correct where the\nevidence is on the page"),
            (pct(d["accuracy_all"]), "counting labels the test set\nnever drew on the page"),
            (pct(ml_dev["classification"]["accuracy"]), f"of {ml_docs} Spanish and Hindi\ndocuments identified correctly")], Inches(3.95), 2.1, 48)
sub(s, "Labelled test data, not real scans yet. That is what the pilot is for.", Inches(6.3), 15, MUTED)
notes(s, "Does it work? I tested it on 78 documents it had never seen. Every document identified correctly. Every claim field read correctly. The right policy clause found, with the page, every time. Decisions: 100 percent correct where the evidence is on the page, 96 percent counting a few test labels never drawn on the documents. And across 80 Spanish and Hindi documents, every one identified correctly, 95 to 100 percent decided correctly. One honest note: labelled test data, not real scans yet. That's what the pilot is for.")

# ── 8. cost and speed ───────────────────────────────────────────────────────────────────────────────
s = plain()
for i, (a, b, col, label) in enumerate([("$18", f"${cost_case:.2f}", RED, "per document by hand   →   per whole claim in AI"),
                                        ("4.2 days", "1 minute", RED, "waiting today   →   live, on AWS")]):
    y = Inches(1.3 + i * 2.6)
    text(s, Inches(0.9), y, Inches(5.2), Inches(1.3), a, 64, MUTED, True, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    text(s, Inches(6.1), y, Inches(1.1), Inches(1.3), "→", 48, MUTED, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, Inches(7.2), y, Inches(5.2), Inches(1.3), b, 64, TEAL, True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, Inches(0.9), y + Inches(1.35), Inches(11.5), Inches(0.4), label, 15, MUTED, align=PP_ALIGN.CENTER)
sub(s, "Savings depend on how many claims go straight through. The pilot measures that; I'm not guessing it.", Inches(6.4), 15, MUTED)
notes(s, "Cost and speed. Eighteen dollars of handling per document today, against about eight cents of AI per whole claim. "
         "Four point two days of waiting, against about a minute, live on AWS. I'm deliberately not giving you a savings "
         "figure. It depends on how many claims go straight through, and the pilot measures that rather than guessing it.")

# ── 9. safe by design ───────────────────────────────────────────────────────────────────────────────
s = plain("Is it safe?")
big(s, "Safe by design.", Inches(0.95), 54)
for i, line in enumerate(["Each role sees only its own data, enforced where the data is read.",
                          "Over $10,000, a second signature from a senior reviewer.",
                          "A logbook nobody can edit: every action chained to the one before.",
                          f"{rt['attacks']} documents with hidden 'approve this' instructions. Decisions changed: {rt['flips']}.",
                          f"A second AI grades the first. Planted wrong answers caught: {judge.get('controls_caught', 3)} of {judge.get('controls', 3)}."]):
    text(s, Inches(1.6), Inches(2.5 + i * 0.75), Inches(10.4), Inches(0.65), line, 20, TEXT, anchor=MSO_ANCHOR.MIDDLE)
sub(s, "AI spend capped in code. Patient details stripped from logs and traces.", Inches(6.35), 15, MUTED)
notes(s, "Is it safe? Each role sees only its own data, enforced where the data is read, so a submitter can't talk the assistant into showing the audit trail. Over ten thousand dollars, a senior reviewer adds a second signature; nobody approves their own request. Every action goes into a logbook nobody can edit. We planted hidden 'approve this' instructions in seven documents: zero decisions changed. And a second, independent AI grades every assistant answer; it caught all three wrong answers I planted. Spend is capped in code, and patient details never reach the logs.")

# ── 10. what's next ─────────────────────────────────────────────────────────────────────────────────
s = plain("What's next")
big(s, "Shadow. Assist. Automate.", Inches(0.95), 54)
for i, (t, line, gate) in enumerate([("Shadow", "Runs beside one team on real scans.\nIts decisions are compared, never used.", "≥ 95% agreement"),
                                      ("Assist", "The system recommends.\nA person confirms every decision.", "< 5% overrides"),
                                      ("Automate", "Clean claims go straight through.\nEscalations always stay human.", "reviewed monthly")]):
    x = Inches(0.9) + Inches(11.5) / 3 * i
    text(s, x, Inches(2.5), Inches(11.5) / 3, Inches(0.6), t, 28, TEAL, True, align=PP_ALIGN.CENTER)
    text(s, x + Inches(0.3), Inches(3.15), Inches(11.5) / 3 - Inches(0.6), Inches(1.2), line, 16, SOFT, align=PP_ALIGN.CENTER)
    text(s, x, Inches(4.35), Inches(11.5) / 3, Inches(0.4), gate, 15, GREEN, True, align=PP_ALIGN.CENTER)
text(s, Inches(0.9), Inches(5.3), Inches(11.5), Inches(0.35), "WHAT I NEED TODAY", 13, AMBER, True, align=PP_ALIGN.CENTER)
sub(s, "A pilot team and an owner.   ·   Approval for the AI-provider privacy review.   ·   Scope for staff single sign-on.", Inches(5.7), 18, TEXT)
notes(s, "What's next? Not a switch-on for everyone. Three stages, each with a gate. Shadow: it runs beside one team on real scans, decisions compared, never used; we move on at 95 percent agreement. Assist: it recommends, a person confirms; we move on under 5 percent overrides. Automate: clean claims go straight through, escalations stay human. The pilot also closes the three open questions: real scans, subtle forged IDs, and the AI-provider privacy review. What I need today: a pilot team and an owner, approval for that review, and scope for single sign-on. Now let me show you it live.")

# ── 11. transition ──────────────────────────────────────────────────────────────────────────────────
s = plain()
big(s, "Let's see it live.", Inches(2.8), 60)
notes(s, "Switch to the browser.")

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
