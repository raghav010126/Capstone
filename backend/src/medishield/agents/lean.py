"""OCR-first routing: use the (free, local) OCR text, and call a *vision* model only when the OCR is not good enough.

Three questions decide whether the page image has to be sent to a model:

1. Is the OCR itself trustworthy?  (sharp page, enough text, high recognition confidence)       -> ``ocr_is_good``
2. Is the document type already clear from its printed words?  (deterministic keyword vote)      -> ``keyword_decisive``
3. After reading the OCR text, are all the fields a document of that type must have present?    -> ``missing_required``

Question 3 matters because confident OCR can still be *incomplete*: OCR reads printed text well and silently skips
handwriting, stamps and anything it cannot see, so a high recognition score does not mean the field is there. A required
field that is absent from the text-only reading sends the page to vision.
"""

from __future__ import annotations

import statistics
from typing import Any

from medishield.config import get_settings
from medishield.schemas import AgentRun, DocType, OcrLine, QualityMetrics

MIN_LINES = 8
MIN_MEAN_SCORE = 0.93
MAX_WEAK_SHARE = 0.15            # share of lines the recogniser itself was unsure about (< 0.8)
KEYWORD_MIN_SCORE = 4.0          # decisive: at least this much weighted keyword evidence ...
KEYWORD_MIN_MARGIN = 0.25        # ... and clearly ahead of the runner-up type

# Fields a document of each type must carry for an automated decision. Absence means "look at the page".
REQUIRED: dict[DocType, list[str]] = {
    DocType.CLAIM_FORM: ["patient_name", "patient_dob", "policy_number", "claim_number", "service_date", "icd_codes",
                         "service_lines", "total_charge", "provider_npi", "billing_provider"],
    DocType.ID_DOCUMENT: ["name_on_id", "dob"],
    DocType.DISCHARGE_SUMMARY: ["patient_name", "admit_date", "discharge_date", "primary_icd"],
    DocType.PRESCRIPTION: ["patient_name", "rx_date", "prescriber", "prescriber_npi", "dea_number", "drugs"],
    DocType.POLICY_AMENDMENT: ["policy_number", "policyholder", "dob", "amendment_type", "effective_date"],
}


def enabled() -> bool:
    """OCR-first routing is on (MEDISHIELD_VISION=auto); otherwise every page image goes to the model."""
    return get_settings().vision_mode == "auto"


def text_extraction() -> bool:
    """Also read the page from OCR text alone before looking at it. Off by default: on the dev split it saved 4% of the cost and
    cost four points of decision accuracy (it copies OCR noise and cannot see coloured stamps or handwriting)."""
    return enabled() and get_settings().text_extract


def absorb(run: AgentRun, res: Any) -> AgentRun:
    """Add the cost of an earlier model call (``res`` is an LLMResult) to the telemetry of the call that replaced it."""
    run.input_tokens += res.usage.input_tokens
    run.output_tokens += res.usage.output_tokens
    run.cost_usd += res.cost_usd
    run.cold_cost_usd += res.cold_cost_usd
    run.latency_ms += res.latency_ms
    run.llm_calls += len(res.attempts)
    run.cache_hits += int(res.cached)
    return run


def ocr_is_good(lines: list[OcrLine], q: QualityMetrics) -> tuple[bool, list[str]]:
    """(good, reasons it is not). Cheap, deterministic, and conservative."""
    why = []
    if q.blank:
        why.append("blank page")
    if q.blur_suspected:
        why.append("blurred page")
    if len(lines) < MIN_LINES:
        why.append(f"only {len(lines)} text lines")
    if lines:
        mean = statistics.fmean(ln.score for ln in lines)
        weak = sum(ln.score < 0.8 for ln in lines) / len(lines)
        if mean < MIN_MEAN_SCORE:
            why.append(f"mean recognition confidence {mean:.2f}")
        if weak > MAX_WEAK_SHARE:
            why.append(f"{weak:.0%} of lines uncertain")
    return not why, why


def keyword_decisive(scores: dict[DocType, float]) -> tuple[DocType | None, float]:
    """The document type if the printed words settle it, else (None, 0). Returns the type and its margin over the runner-up."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top, a), (_, b) = ranked[0], ranked[1]
    margin = (a - b) / a if a else 0.0
    return (top, round(margin, 3)) if a >= KEYWORD_MIN_SCORE and margin >= KEYWORD_MIN_MARGIN else (None, 0.0)


def _present(v: Any) -> bool:
    if v is None or v == "" or v == [] or v == {}:
        return False
    return not (isinstance(v, list) and all(isinstance(x, dict) and not any(x.values()) for x in v))


def missing_required(doc_type: DocType, values: dict[str, Any]) -> list[str]:
    """Required fields that a text-only reading did not find (the page itself should then be looked at)."""
    missing = [f for f in REQUIRED.get(doc_type, []) if not _present(values.get(f))]
    if doc_type == DocType.ID_DOCUMENT and "dob" not in missing and not (values.get("expiry_date") or values.get("stamps")):
        missing.append("expiry_date")                          # some cards print none, but then a stamp or the page must say so
    if doc_type == DocType.CLAIM_FORM and _present(values.get("service_lines")) \
            and not any(ln.get("cpt") for ln in values["service_lines"]):
        missing.append("service_lines.cpt")
    if values.get("missing_markers"):
        missing.append("form prints a missing-field marker")  # let the vision reading confirm what exactly is missing
    return missing


def layout_text(lines: list[OcrLine]) -> str:
    """OCR lines as rows, left to right, with x positions - enough for a model to reassemble forms and tables without the image.

    Lines whose vertical centres are within about 60% of the median text height share a row."""
    if not lines:
        return ""
    heights = [max(1, ln.box[3] - ln.box[1]) for ln in lines]
    tol = max(6.0, 0.6 * statistics.median(heights))
    rows: list[list[OcrLine]] = []
    for ln in sorted(lines, key=lambda x: ((x.box[1] + x.box[3]) / 2, x.box[0])):
        cy = (ln.box[1] + ln.box[3]) / 2
        if rows and abs(cy - statistics.fmean((r.box[1] + r.box[3]) / 2 for r in rows[-1])) <= tol:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    out = []
    for row in rows:
        row.sort(key=lambda x: x.box[0])
        y = int(statistics.fmean((r.box[1] + r.box[3]) / 2 for r in row))
        out.append(f"y={y}: " + " | ".join(f'x={r.box[0]} "{r.text}"' for r in row))
    return "\n".join(out)
