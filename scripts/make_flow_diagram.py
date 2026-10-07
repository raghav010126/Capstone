"""Write docs/diagrams/claim_flow.svg: the MediShield claim flow in the style of the brief's reference diagram.

Usage (from the repo root): python3 scripts/make_flow_diagram.py; the PNG is a 2x render of the SVG (any browser screenshot).
"""
from html import escape

W, H = 1920, 1080
BLUE, PURPLE, GREEN, ORANGE = ("#2563eb", "#60a5fa"), ("#7c3aed", "#a78bfa"), ("#2f855a", "#68d391"), ("#ea580c", "#fdba74")
OUT = {"Approved": ("#4d7c0f", "#a3e635"), "Rejected": ("#dc2626", "#fca5a5"), "Escalated": ("#d97706", "#fcd34d")}
F = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
el = []

def box(x, y, w, h, title, lines=(), col=BLUE, ts=26, ls=17):
    fill, stroke = col
    el.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="2.5" filter="url(#sh)"/>')
    n = len(lines)
    block = ts + n * (ls + 8)
    ty = y + (h - block) / 2 + ts * 0.85
    el.append(f'<text x="{x + w / 2}" y="{ty}" font-size="{ts}" font-weight="700" fill="#fff" text-anchor="middle">{escape(title)}</text>')
    for i, ln in enumerate(lines):
        el.append(f'<text x="{x + w / 2}" y="{ty + (i + 1) * (ls + 8) + 2}" font-size="{ls}" fill="#e0e7ff" text-anchor="middle">{escape(ln)}</text>')

def line(pts, arrow=False):
    d = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pts))
    el.append(f'<path d="{d}" fill="none" stroke="#cbd5e1" stroke-width="2.5"{" marker-end=&quot;url(#ar)&quot;" if arrow else ""}/>'.replace("&quot;", '"'))

def label(x, y, s, size=16, color="#c4b5fd", anchor="middle", weight="600", italic=False):
    el.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}"'
              f'{" font-style=&quot;italic&quot;" if italic else ""}>{escape(s)}</text>'.replace("&quot;", '"'))

CX = 700
label(95, 58, "MEDISHIELD · HOW A CLAIM FLOWS", 20, "#a5b4fc", "start", "800")
# 1 intake
box(360, 85, 680, 82, "Document intake", ["FastAPI · signed S3 uploads · email (.eml / SES)"], BLUE)
line([(CX, 167), (CX, 203)], True)
# 2 perceive
box(360, 205, 680, 82, "Perceive · every document in parallel", ["Local OCR (RapidOCR) · image quality · no API cost"], BLUE)
line([(CX, 287), (CX, 323)], True)
# 3 classifier
box(360, 325, 680, 82, "Classifier agent", ["Printed keywords first · Sonnet vision only when needed"], PURPLE)
# fan out to 4 boxes
xs = [95, 405, 715, 1025]; bw = 280; cxs = [x + bw / 2 for x in xs]
line([(CX, 407), (CX, 440)])
line([(cxs[0], 440), (cxs[3], 440)])
for c in cxs:
    line([(c, 440), (c, 470)], True)
label(cxs[0] + 14, 432, "per document, in parallel", 15, "#c4b5fd", "start", italic=True)
label(cxs[3] - 14, 432, "runs beside the specialists", 15, "#fdba74", "end", italic=True)
box(xs[0], 472, bw, 112, "KYC agent", ["Member record · ID expiry", "Tamper forensics · 2 models"], GREEN, 24, 15)
box(xs[1], 472, bw, 112, "Claims agent", ["ICD-10 · CPT · provider NPI", "Amounts add up"], GREEN, 24, 15)
box(xs[2], 472, bw, 112, "Policy agent", ["Docling + hybrid RAG", "Exclusion table decides"], GREEN, 24, 15)
box(xs[3], 472, bw, 112, "Fraud agent", ["Claim-history rules", "+ Sonnet narrative · risk"], ORANGE, 24, 15)
for c in cxs:
    line([(c, 584), (c, 612)])
line([(cxs[0], 612), (cxs[3], 612)])
line([(CX, 612), (CX, 638)], True)
# decision
box(330, 640, 740, 96, "Decision engine + orchestrator",
    ["A rule file decides: Approve · Reject · Escalate", "Calibrated confidence · justification written by Sonnet"], PURPLE, 25, 16)
line([(CX, 736), (CX, 760)])
ocx = [330, 700, 1070]
line([(ocx[0], 760), (ocx[2], 760)])
for c in ocx:
    line([(c, 760), (c, 786)], True)
for c, name in zip(ocx, OUT):
    box(c - 125, 788, 250, 62, name, (), OUT[name], 25)
# human review
line([(1070, 850), (1070, 880)], True)
box(880, 882, 380, 78, "Human review", ["Reviewer override · four-eyes over $10k → Finalized"], ("#7c2d12", "#fdba74"), 22, 14)

# legend + state machine
lx = 95
for col, name in ((BLUE, "Ingestion"), (PURPLE, "Orchestration"), (GREEN, "Specialist agents"), (ORANGE, "Fraud detection")):
    el.append(f'<rect x="{lx}" y="985" width="20" height="20" rx="4" fill="{col[0]}" stroke="{col[1]}" stroke-width="2"/>')
    label(lx + 30, 1001, name, 17, "#e2e8f0", "start", "500")
    lx += 30 + len(name) * 9 + 40
label(CX, 1048, "LangGraph: received → perceive → classified → [ specialists + fraud check, in parallel ] → decided → human review", 17,
      "#e2e8f0", "middle", "600")

# side panel
px, pw = 1365, 500
label(px, 58, "AROUND EVERY CASE", 20, "#a5b4fc", "start", "800")
cards = [("Case management UI", ["Next.js on CloudFront: dashboard, case view,", "review queue, audit log, insights"], BLUE),
         ("Role-aware assistant", ["AgentCore Runtime + Memory · cited answers", "blocked by role at the data"], PURPLE),
         ("Tamper-evident audit", ["Every view, decision and override", "hash-chained"], PURPLE),
         ("LangSmith tracing", ["Every agent call: tokens, latency, cost"], BLUE),
         ("Runs on AWS", ["Lambda API · Bedrock AgentCore · DynamoDB · S3", "one CloudFormation stack · ≈ $1.25/month idle"], GREEN)]
y = 85
for t, lines, col in cards:
    h = 140 if len(lines) > 1 else 120
    el.append(f'<rect x="{px}" y="{y}" width="{pw}" height="{h}" rx="14" fill="#1e1b4b" fill-opacity="0.75" stroke="{col[1]}" stroke-width="2"/>')
    el.append(f'<rect x="{px}" y="{y + 18}" width="6" height="{h - 36}" rx="3" fill="{col[1]}"/>')
    label(px + 30, y + 44, t, 23, "#ffffff", "start", "700")
    for i, ln in enumerate(lines):
        label(px + 30, y + 80 + i * 28, ln, 17, "#cbd5e1", "start", "400")
    y += h + 22

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{F}">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1e1b4b"/><stop offset="1" stop-color="#3b0764"/></linearGradient>
  <marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#cbd5e1"/></marker>
  <filter id="sh" x="-10%" y="-10%" width="120%" height="140%"><feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000" flood-opacity="0.35"/></filter>
</defs>
<rect width="{W}" height="{H}" fill="url(#bg)"/>
{chr(10).join(el)}
</svg>'''
open("docs/diagrams/claim_flow.svg", "w").write(svg)
print("svg written")
