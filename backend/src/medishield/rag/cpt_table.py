"""CPT code -> service type, from the public structure of the CPT code set (AMA sections and subsections).

Used to phrase retrieval queries in the policy's vocabulary ("Diagnostic Lab & Imaging", "Emergency Room")
instead of the procedure's clinical wording. It is generic coding knowledge, not tuned to the dataset.
"""

from __future__ import annotations

# (first, last, service type, retrieval hint) - most specific first
_RANGES: list[tuple[int, int, str, str]] = [
    (36400, 36416, "laboratory", "diagnostic laboratory blood collection lab tests"),
    (59000, 59899, "maternity", "maternity care labor delivery obstetric prenatal postnatal rider"),
    (15000, 17999, "surgery-integumentary", "skin surgery cosmetic outpatient surgery"),
    (19000, 19499, "surgery-breast", "breast surgery cosmetic outpatient surgery"),
    (10000, 69999, "surgery", "surgical services outpatient surgery inpatient hospitalization operating room"),
    (70000, 79999, "radiology", "diagnostic imaging X-ray CT MRI ultrasound Diagnostic Lab & Imaging"),
    (80000, 89999, "laboratory", "diagnostic laboratory tests blood panels Diagnostic Lab & Imaging"),
    (90785, 90899, "mental-health", "mental health substance use outpatient psychotherapy"),
    (92920, 93799, "diagnostic-cardiology", "diagnostic services echocardiogram ECG Diagnostic Lab & Imaging"),
    (97010, 97799, "physical-medicine", "physical therapy rehabilitation physical medicine prior authorization"),
    (99202, 99215, "office-visit", "outpatient physician visit primary care specialist copay"),
    (99221, 99239, "inpatient-visit", "inpatient hospitalization attending physician"),
    (99241, 99255, "consultation", "specialist consultation copay"),
    (99281, 99288, "emergency", "emergency room services ER copay"),
    (99291, 99292, "critical-care", "intensive care unit ICU inpatient hospitalization"),
    (99381, 99429, "preventive", "preventive care ACA-mandated"),
    (90281, 99607, "medicine", "outpatient physician services"),
]


def service_type(code: str) -> tuple[str, str]:
    c = code.strip().upper()
    if c.endswith("T") and c[:4].isdigit():
        return "category-iii", "experimental emerging technology investigational"
    if c[:1] == "D" and c[1:].isdigit():
        return "dental", "dental procedures"
    if c[:1] == "V" and c[1:].isdigit():
        return "vision", "vision spectacles eyeglasses contact lenses"
    if not c.isdigit():
        return "unknown", ""
    n = int(c)
    for lo, hi, kind, hint in _RANGES:
        if lo <= n <= hi:
            return kind, hint
    return "unknown", ""
