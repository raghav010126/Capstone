"""Tamper forensics and how KYC combines them with the visual review."""

import io
from pathlib import Path

from medishield.agents import kyc
from medishield.agents.context import CaseContext, DocView
from medishield.forensics import ela, typography
from medishield.records import Records
from medishield.schemas import AgentRun, DocType, ExtractionResult, OcrLine
from medishield.schemas.llm_outputs import KycVisualRead
from PIL import Image, ImageDraw, ImageFont

MEMBER = {"member_id": "PT_1", "policy_number": "MED-GLD-1234567", "full_name": "Ann Lee", "dob": "1980-01-02",
          "status": "ACTIVE", "plan": "GOLD"}
ARIAL = next((f for f in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
                          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",       # Linux (CI)
                          "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf") if Path(f).exists()), None)


def card(tmp_path, size_exp=18, name="card.png"):
    """A synthetic card with a date of birth and an expiry date; returns (path, OCR-like lines)."""
    img = Image.new("RGB", (640, 400), (240, 248, 255))
    d = ImageDraw.Draw(img)
    lines = []
    for y, text, size in ((120, "04/25/1954", 18), (200, "12/31/2029", size_exp)):
        f = ImageFont.truetype(ARIAL, size) if ARIAL else ImageFont.load_default(size)
        d.text((200, y), text, font=f, fill=(0, 0, 0))
        l, t, r, b = d.textbbox((200, y), text, font=f)
        lines.append(OcrLine(id=len(lines), text=text, box=(l, t, r, b), score=0.99))
    p = tmp_path / name
    img.save(p)
    return str(p), lines


def test_typography_passes_a_consistent_card(tmp_path):
    path, lines = card(tmp_path)
    assert not typography.analyse(path, lines).flagged


def test_typography_flags_a_retyped_date_in_another_size(tmp_path):
    path, lines = card(tmp_path, size_exp=22)
    res = typography.analyse(path, lines)
    assert res.flagged and {s["text"] for s in res.suspects} == {"04/25/1954", "12/31/2029"}


def test_typography_needs_two_dates(tmp_path):
    path, lines = card(tmp_path)
    assert "nothing to compare" in typography.analyse(path, lines[:1]).detail


def test_ela_not_applicable_to_png(tmp_path):
    path, _ = card(tmp_path)
    r = ela.analyse(Path(path).read_bytes())
    assert not r.applicable and not r.flagged and r.heatmap_png is None


def test_ela_returns_a_heatmap_for_jpeg(tmp_path):
    img = Image.new("RGB", (640, 400), "white")
    ImageDraw.Draw(img).text((50, 50), "hello world " * 10, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    r = ela.analyse(buf.getvalue())
    assert r.applicable and r.heatmap_png and r.heatmap_png.startswith(b"\x89PNG")


# ── how KYC combines the signals ─────────────────────────────────────────────────────────────────────
def verdict(level: str, suspect: bool):
    return KycVisualRead(tamper_indicators=["x"] if suspect else [], layout_or_quality_issues=[], tamper_likelihood=level,
                         expired_marking=False, photo_present=True, assessment="")


def run_kyc(tmp_path, monkeypatch, size_exp, vision):
    path, lines = card(tmp_path, size_exp)
    monkeypatch.setattr(kyc, "_visual", lambda p, t: (verdict(*vision), [], AgentRun(agent="kyc_visual"), vision[1]))
    ext = ExtractionResult(doc_type=DocType.ID_DOCUMENT, fields=[], raw_text="", bounding_boxes=lines, grounding_rate=1,
                           support_rate=1, confidence=0.95,
                           values={"name_on_id": "ANN LEE", "dob": "04/25/1954", "expiry_date": "2029-12-31",
                                   "policy_number": None, "stamps": []})
    ctx = CaseContext("C", [DocView("claim", DocType.CLAIM_FORM, {"service_date": "2025-11-09", "patient_name": "Ann Lee",
                                                                     "patient_dob": "01/02/1980", "policy_number": "MED-GLD-1234567"}, 0.95)])
    res, _ = kyc.verify_id("id", path, ext, ctx, Records([{**MEMBER, "dob": "1954-04-25"}], []))
    return res


def test_consistent_card_and_clean_vision_passes(tmp_path, monkeypatch):
    res = run_kyc(tmp_path, monkeypatch, 18, ("none", False))
    assert res.kyc_passed and "typography_inconsistent" not in res.warnings


def test_typography_alone_escalates_but_does_not_deny(tmp_path, monkeypatch):
    res = run_kyc(tmp_path, monkeypatch, 22, ("none", False))
    assert res.kyc_passed and "typography_inconsistent" in res.warnings and res.confidence <= 0.5


def test_typography_plus_visual_suspicion_is_a_hard_tamper_flag(tmp_path, monkeypatch):
    res = run_kyc(tmp_path, monkeypatch, 22, ("medium", True))
    assert not res.kyc_passed and "tamper_suspected" in res.flags
    assert res.forensics["typography"]["flagged"]


def test_visual_suspicion_alone_does_not_deny(tmp_path, monkeypatch):
    res = run_kyc(tmp_path, monkeypatch, 18, ("medium", True))
    assert res.kyc_passed and "tamper_suspected" not in res.flags
