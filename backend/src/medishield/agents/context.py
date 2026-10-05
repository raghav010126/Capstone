"""Case context shared with the specialist agents after the perception fan-out (ADR: two-stage fan-out).

Specialists need facts from *other* documents in the case: KYC judges ID expiry against the claim's date of
service (finding F11), Policy needs the claim's CPT codes, Fraud compares dates across documents. Running
perception for every document first, then the specialists with this context, resolves the brief's
"Policy needs Claims output but runs in parallel" tension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from medishield.records import parse_date
from medishield.schemas import DocType


@dataclass
class DocView:
    doc_id: str
    doc_type: DocType
    values: dict
    confidence: float
    image_hash: str = ""


@dataclass
class CaseContext:
    case_id: str
    docs: list[DocView] = field(default_factory=list)       # submission order

    def of_type(self, t: DocType) -> list[DocView]:
        return [d for d in self.docs if d.doc_type == t]

    def reference_date(self) -> tuple[date | None, str]:
        """Date of service used to judge ID validity: claim DOS > discharge admission > Rx date > amendment."""
        for t, key in ((DocType.CLAIM_FORM, "service_date"), (DocType.DISCHARGE_SUMMARY, "admit_date"),
                       (DocType.PRESCRIPTION, "rx_date"), (DocType.POLICY_AMENDMENT, "effective_date")):
            for d in self.of_type(t):
                v = parse_date(d.values.get(key))
                if v:
                    return v, f"{d.doc_id}.{key}"
        return None, "none"

    def patient_identity(self) -> tuple[str | None, str | None, str | None]:
        """(name, dob, policy) as printed on the case's clinical/claim documents (not the ID itself)."""
        for t in (DocType.CLAIM_FORM, DocType.DISCHARGE_SUMMARY, DocType.PRESCRIPTION, DocType.POLICY_AMENDMENT):
            for d in self.of_type(t):
                v = d.values
                name = v.get("patient_name") or v.get("policyholder")
                if name:
                    return name, v.get("patient_dob") or v.get("dob"), v.get("policy_number")
        return None, None, None
