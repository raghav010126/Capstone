"""OCR-first routing decisions (pure functions)."""

from medishield.agents import lean
from medishield.schemas import DocType, OcrLine, QualityMetrics


def ln(text, x, y, score=0.99, h=20, w=120):
    return OcrLine(id=0, text=text, box=(x, y, x + w, y + h), score=score)


def quality(**kw):
    base = {"width": 1000, "height": 1400, "sharpness": 900, "blank": False, "blur_suspected": False, "ocr_mean_score": 0.99,
            "ocr_lines": 30, "quality_score": 0.95}
    return QualityMetrics(**{**base, **kw})


def test_good_ocr():
    ok, why = lean.ocr_is_good([ln("x", 0, i * 30) for i in range(12)], quality())
    assert ok and not why


def test_each_ocr_problem_is_reported():
    lines = [ln("x", 0, i * 30) for i in range(12)]
    assert "blurred page" in lean.ocr_is_good(lines, quality(blur_suspected=True))[1]
    assert "blank page" in lean.ocr_is_good(lines, quality(blank=True))[1]
    assert any("text lines" in w for w in lean.ocr_is_good(lines[:4], quality())[1])
    weak = [ln("x", 0, i * 30, score=0.6) for i in range(12)]
    assert not lean.ocr_is_good(weak, quality())[0]


def test_keyword_vote_must_be_clear():
    scores = {t: 0.0 for t in DocType if t != DocType.UNKNOWN}
    assert lean.keyword_decisive(scores) == (None, 0.0)                          # nothing recognised (e.g. a bank statement)
    scores[DocType.ID_DOCUMENT] = 4.5
    assert lean.keyword_decisive(scores)[0] == DocType.ID_DOCUMENT
    scores[DocType.CLAIM_FORM] = 4.0                                              # nearly tied: not decisive
    assert lean.keyword_decisive(scores)[0] is None
    assert lean.keyword_decisive({**scores, DocType.CLAIM_FORM: 0.0, DocType.ID_DOCUMENT: 3.0})[0] is None   # too little evidence


def test_missing_required_catches_the_unreadable_handwriting_case():
    """OCR reads the printed fields and skips the handwritten date of birth: a page it considers 'fine' is incomplete."""
    amend = {"policy_number": "MED-GLD-1", "policyholder": "Ann Lee", "dob": None, "amendment_type": "Cancellation",
             "effective_date": "2025-11-09"}
    assert lean.missing_required(DocType.POLICY_AMENDMENT, amend) == ["dob"]
    assert lean.missing_required(DocType.POLICY_AMENDMENT, {**amend, "dob": "02/28/1963"}) == []


def test_missing_markers_and_empty_lines_send_the_page_to_vision():
    claim = {"patient_name": "A", "patient_dob": "01/01/1980", "policy_number": "P", "claim_number": "C", "service_date": "2025-01-01",
             "icd_codes": ["E11.9"], "service_lines": [{"cpt": None, "charge": None}], "total_charge": 10.0, "provider_npi": "NPI-1",
             "billing_provider": "H", "missing_markers": []}
    assert "service_lines" in lean.missing_required(DocType.CLAIM_FORM, claim)
    claim["service_lines"] = [{"cpt": "99213", "charge": 10.0}]
    assert lean.missing_required(DocType.CLAIM_FORM, claim) == []
    assert lean.missing_required(DocType.CLAIM_FORM, {**claim, "missing_markers": ["npi"]}) == ["form prints a missing-field marker"]


def test_id_needs_an_expiry_or_a_stamp():
    assert lean.missing_required(DocType.ID_DOCUMENT, {"name_on_id": "A", "dob": "01/01/1980"}) == ["expiry_date"]
    assert lean.missing_required(DocType.ID_DOCUMENT, {"name_on_id": "A", "dob": "01/01/1980", "stamps": ["CARD EXPIRED"]}) == []


def test_layout_text_keeps_rows_and_columns():
    text = lean.layout_text([ln("Patient:", 60, 100), ln("Jessica Jackson Y.", 330, 102), ln("DOB:", 60, 160), ln("02/28/1963", 330, 158)])
    assert text.splitlines() == ['y=111: x=60 "Patient:" | x=330 "Jessica Jackson Y."', 'y=169: x=60 "DOB:" | x=330 "02/28/1963"']


# ── routing inside the agents (model calls stubbed) ───────────────────────────────────────────────────
import pytest
from medishield.agents import classifier, extractor, kyc


@pytest.fixture
def auto(monkeypatch):
    monkeypatch.setenv("MEDISHIELD_VISION", "auto")
    from medishield.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def claim_lines():
    texts = ["HEALTH INSURANCE CLAIM FORM", "CMS-1500", "Total charges", "CPT HCPCS", "Billing provider"] + [f"row {i}" for i in range(8)]
    return [ln(t, 10, 30 + i * 30) for i, t in enumerate(texts)]


def test_classifier_makes_no_model_call_when_keywords_decide(auto, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(classifier, "structured_with_retry", boom)
    c, run = classifier.classify("unused.png", claim_lines(), quality())
    assert c.doc_type == DocType.CLAIM_FORM and "ocr_only" in c.routing_tags and run.llm_calls == 0 and run.cost_usd == 0


def test_classifier_uses_vision_only_for_poor_ocr(auto, monkeypatch):
    seen = {}

    def fake(step, system, parts, out, **k):
        seen["parts"] = parts
        raise RuntimeError("stop")

    monkeypatch.setattr(classifier, "structured_with_retry", fake)
    monkeypatch.setattr(classifier, "image_part", lambda *a, **k: "IMAGE")
    with pytest.raises(RuntimeError):
        classifier.classify("p.png", claim_lines(), quality(blur_suspected=True))
    assert seen["parts"][0] == "IMAGE"                                           # poor page -> the model looks at the image
    with pytest.raises(RuntimeError):
        classifier.classify("p.png", [ln("a letter", 0, 30 * i) for i in range(12)], quality())
    assert "IMAGE" not in seen["parts"]                                          # good OCR, no keywords -> text only


class FakeRes:
    def __init__(self, parsed):
        from medishield.llm.client import Usage

        self.parsed, self.usage, self.cost_usd, self.cold_cost_usd, self.latency_ms = parsed, Usage(10, 5), 0.01, 0.01, 5.0
        self.cached, self.attempts, self.model, self.retried_with = False, ["m"], "m", None

    def run(self, agent):
        from medishield.schemas import AgentRun

        return AgentRun(agent=agent, model="m", input_tokens=10, output_tokens=5, cost_usd=0.01, cold_cost_usd=0.01, latency_ms=5.0,
                        llm_calls=1)


def id_model(**over):
    from medishield.schemas.llm_outputs import READ_MODELS

    vals = {"name_on_id": "Ann Lee", "dob": "01/02/1980", "expiry_date": "2030-01-01"}
    vals.update(over)
    return READ_MODELS[DocType.ID_DOCUMENT].model_construct(**{**{k: None for k in READ_MODELS[DocType.ID_DOCUMENT].model_fields}, **vals})


def test_extractor_text_only_when_nothing_is_missing(auto, monkeypatch):
    monkeypatch.setenv("MEDISHIELD_TEXT_EXTRACT", "1")
    from medishield.config import get_settings

    get_settings.cache_clear()
    lines = [ln(t, 10, 30 * i) for i, t in enumerate(["Ann Lee", "01/02/1980", "2030-01-01", *[f"x{i}" for i in range(9)]])]
    monkeypatch.setattr(extractor, "structured", lambda *a, **k: FakeRes(id_model()))
    monkeypatch.setattr(extractor, "structured_with_retry", lambda *a, **k: pytest.fail("vision path must not run"))
    ext, run = extractor.extract("p.png", DocType.ID_DOCUMENT, lines, quality(), None)
    assert ext.values["name_on_id"] == "Ann Lee" and run.llm_calls == 1


def test_extractor_falls_back_to_vision_when_a_required_field_is_missing(auto, monkeypatch):
    monkeypatch.setenv("MEDISHIELD_TEXT_EXTRACT", "1")
    from medishield.config import get_settings

    get_settings.cache_clear()
    lines = [ln(t, 10, 30 * i) for i, t in enumerate(["Ann Lee", "2030-01-01", *[f"x{i}" for i in range(10)]])]
    monkeypatch.setattr(extractor, "structured", lambda *a, **k: FakeRes(id_model(dob=None)))
    monkeypatch.setattr(extractor, "structured_with_retry", lambda *a, **k: FakeRes(id_model()))
    monkeypatch.setattr(extractor, "image_part", lambda *a, **k: "IMAGE")
    ext, run = extractor.extract("p.png", DocType.ID_DOCUMENT, lines, quality(), None)
    assert ext.values["dob"] == "01/02/1980"
    assert run.llm_calls == 2 and abs(run.cost_usd - 0.02) < 1e-9                  # the text attempt is still counted


def test_always_mode_never_skips_the_model(monkeypatch):
    monkeypatch.setenv("MEDISHIELD_VISION", "always")
    from medishield.config import get_settings

    get_settings.cache_clear()
    assert not lean.enabled()
    called = []
    monkeypatch.setattr(classifier, "structured_with_retry", lambda *a, **k: called.append(1) or (_ for _ in ()).throw(RuntimeError))
    monkeypatch.setattr(classifier, "image_part", lambda *a, **k: "IMAGE")
    with pytest.raises(RuntimeError):
        classifier.classify("p.png", claim_lines(), quality())
    assert called
    get_settings.cache_clear()


def test_kyc_import_is_wired():
    assert kyc.lean is lean


def test_extraction_sends_the_page_by_default_even_in_auto_mode(auto, monkeypatch):
    lines = [ln(t, 10, 30 * i) for i, t in enumerate(["Ann Lee", "01/02/1980", "2030-01-01", *[f"x{i}" for i in range(9)]])]
    monkeypatch.setattr(extractor, "structured", lambda *a, **k: pytest.fail("text-only extraction is off by default"))
    monkeypatch.setattr(extractor, "structured_with_retry", lambda *a, **k: FakeRes(id_model()))
    monkeypatch.setattr(extractor, "image_part", lambda *a, **k: "IMAGE")
    ext, _run = extractor.extract("p.png", DocType.ID_DOCUMENT, lines, quality(), None)
    assert ext.values["name_on_id"] == "Ann Lee"
