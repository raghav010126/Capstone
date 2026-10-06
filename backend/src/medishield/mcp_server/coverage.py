"""Deterministic coverage answers for the MCP ``check_coverage`` tool: no model call, no search models.

Coverage of a CPT code is decided the same way the policy agent decides it: exact containment in the plan's parsed table 4.1
(``rag.exclusions.lookup``). Cost sharing comes from the plan's Schedule of Benefits (``agents.policy.benefit_rows``). Which
benefit row applies is a hint from the code's CPT section; on a real claim the policy agent picks the row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from medishield.rag.cpt_table import service_type
from medishield.rag.exclusions import lookup
from medishield.rag.ingest import PolicyIndex

CODE_RE = re.compile(r"^[0-9A-Z]{5}$")
# CPT section (rag.cpt_table.service_type) -> words that name its Schedule of Benefits row(s)
BENEFIT_HINTS: dict[str, tuple[str, ...]] = {
    "office-visit": ("primary care", "specialist"),
    "consultation": ("specialist",),
    "emergency": ("emergency room",),
    "inpatient-visit": ("inpatient hospitalization",),
    "critical-care": ("inpatient hospitalization",),
    "surgery": ("outpatient surgery", "inpatient hospitalization"),
    "surgery-integumentary": ("outpatient surgery",),
    "surgery-breast": ("outpatient surgery",),
    "radiology": ("diagnostic lab",),
    "laboratory": ("diagnostic lab",),
    "diagnostic-cardiology": ("diagnostic lab",),
    "preventive": ("preventive care",),
    "mental-health": ("mental health",),
}


class CoverageInputError(ValueError):
    """The code or plan is not one we can look up (the message is safe to show the caller)."""


@dataclass
class PolicyIndexes:
    """What a coverage check needs from the policy store (``PolicyStore.indexes`` / ``.ranges``) without its search models."""

    indexes: dict[str, PolicyIndex]

    def ranges(self, plan: str) -> list:
        return self.indexes[plan].ranges if plan in self.indexes else []


def policy_store() -> PolicyIndexes:
    """The parsed policies the search store is built from (``rag.retrieve``): bundled PDFs, then READY uploads, which replace
    their plan. Only cached ingestion results are read, so the API Lambda never loads the embedding models for this."""
    from medishield.rag.ingest import load_or_ingest, policy_pdfs
    from medishield.services.policies import uploaded_policy_paths

    indexes = {i.plan: i for i in (load_or_ingest(p) for p in policy_pdfs())}
    for p in uploaded_policy_paths():
        idx = load_or_ingest(p)
        plan = p.stem.split("-")[0]
        idx.plan = plan
        indexes[plan] = idx
    return PolicyIndexes(indexes)


def _section(store, plan: str, section_no: str, kind: str) -> tuple[str | None, int | None]:
    """(title, first page) of a plan's section chunk, for citations."""
    for c in store.indexes[plan].chunks:
        if c.section_no == section_no and c.kind == kind:
            return c.section, (c.pages[0] if c.pages else None)
    return None, None


def check(store, cpt_code: str, plan: str) -> dict:
    # imported here, not at module load: agents.policy pulls in the model SDK and the vector store client
    from medishield.agents.policy import benefit_rows

    code = (cpt_code or "").strip().upper()
    plan = re.sub(r"\s*plan$", "", (plan or "").strip().lower())
    if not CODE_RE.match(code):
        raise CoverageInputError(f"'{cpt_code}' is not a 5-character procedure code (e.g. 17000, 0042T, D0120)")
    if plan not in store.indexes:
        raise CoverageInputError(f"unknown plan '{plan}'; plans on file: {', '.join(sorted(store.indexes))}")
    rows = lookup(code, store.ranges(plan))
    excl = [r for r in rows if r.kind == "exclusion"]
    prior = [r for r in rows if r.kind == "prior_auth"]
    table_title, table_page = _section(store, plan, "4.1", "table")
    table_title = table_title or "4.1 Excluded CPT Code Ranges"
    name = f"{plan.title()} plan"

    def cite_row(r) -> dict:
        return {"source": f"{name}, {table_title}", "clause": f"{r.label} {r.category} ({r.basis})",
                "page": r.page or table_page}

    if excl:
        r = excl[0]
        status = "NOT_COVERED"
        answer = (f"CPT {code} is NOT covered on the {name}: table 4.1 excludes {r.label} {r.category} ({r.basis}). "
                  "Codes in this table are denied automatically unless a qualifying rider is active.")
    elif prior:
        r = prior[0]
        status = "CONDITIONAL"
        answer = (f"CPT {code} is covered on the {name} only with prior authorisation: table 4.1 lists {r.label} {r.category} "
                  f"({r.basis}).")
    elif rows:
        r = rows[0]
        status = "COVERED"
        answer = (f"CPT {code} is not excluded on the {name}; table 4.1 sets a cost-sharing rule for {r.label} {r.category}: "
                  f"{r.basis}.")
    else:
        status = "NOT_LISTED"
        answer = (f"CPT {code} is not listed in table 4.1 of the {name} (no exclusion or prior-authorisation range), so it "
                  "is not automatically excluded; like any unlisted code it is subject to medical-necessity review.")
    citations = [cite_row(r) for r in rows] or [{"source": f"{name}, {table_title}", "clause": "code not in any listed range",
                                                 "page": table_page}]
    benefits = []
    if status != "NOT_COVERED":
        kind, _hint = service_type(code)
        words = BENEFIT_HINTS.get(kind, ())
        benefits = [{"category": cat, "in_network": cost} for cat, cost in benefit_rows(store, plan).items()
                    if any(w in cat.lower() for w in words)]
        if benefits:
            sob_title, sob_page = _section(store, plan, "1", "table")
            citations.append({"source": f"{name}, {sob_title or 'Schedule of Benefits'}",
                              "clause": "; ".join(f"{b['category']}: {b['in_network']} in-network" for b in benefits),
                              "page": sob_page})
            answer += " In-network cost sharing for this kind of service: " + "; ".join(
                f"{b['category']} {b['in_network']}" for b in benefits).rstrip(".") + "."
    return {"cpt_code": code, "plan": plan, "status": status, "answer": answer,
            "table_4_1_rows": [{"range": r.label, "category": r.category, "basis": r.basis, "kind": r.kind, "page": r.page}
                               for r in rows],
            "benefit_rows": benefits, "citations": citations, "deterministic": True}
