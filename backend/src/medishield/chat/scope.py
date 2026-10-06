"""Questions asked from a case page ("Ask about this case"): the conversation is scoped to that case.

No extra model call. The router gets one context line saying which case the page shows. A few deterministic rules then make
that case the subject unless the question names another one. Access is still enforced by the case tool:
``sources.case_passages`` returns nothing for a case the user may not see, and the case's procedure codes and plan are used
only if it returned the case.
"""

from __future__ import annotations

import re

from medishield.chat import sources as src
from medishield.chat.router import _CASE_ID, RouteOut, keyword_route

# words that make a question about the case on screen when it names nothing else ("why?", "what would change it?")
_ABOUT = re.compile(r"\b(why|what|which|how|explain|summar\w*|tell me|decid\w*|decision|reject\w*|approv\w*|escalat\w*|"
                    r"chang\w*|reason\w*|clause|cover\w*|fraud|risk|flag\w*|status|this|it)\b", re.IGNORECASE)


def case_id_of(payload: dict) -> str | None:
    cid = str(payload.get("case_id") or "").strip().upper()
    return cid if _CASE_ID.fullmatch(cid) else None


def router_hint(case_id: str) -> dict:
    """A turn appended to the router's history: what "this case", "it" and bare follow-ups refer to."""
    return {"role": "page", "text": f"The user is asking from the page of case {case_id}. \"This case\", \"this claim\", \"it\" and "
                                    f"questions without another subject (\"why?\", \"what would change the decision?\") are about "
                                    f"{case_id}."}


def apply(r: RouteOut, case_id: str, question: str) -> RouteOut:
    """Make the page's case the subject of the routed question, unless the question names another topic."""
    if (r.route in ("help", "off_topic") and not (r.case_ids or r.cpt_codes or r.plans)
            and keyword_route(question).route != "help" and _ABOUT.search(question)):
        r.route = "case"
    if r.route == "case":
        r.case_ids = list(dict.fromkeys([case_id, *r.case_ids]))
    elif r.route == "audit" and not r.case_ids:
        r.case_ids = [case_id]
    if r.route != "analytics":           # whose case it is is decided by the case tool, as for any named case
        r.sources = [s for s in r.sources if s not in ("own_cases", "all_cases")]
    return r


def policy_terms(r: RouteOut, scoped: list[src.Passage]) -> tuple[list[str], list[str]]:
    """(plans, codes) for a policy search: those the question names, else the case's (present only if the user may see it)."""
    meta = next((p.meta for p in scoped if p.kind == "case"), {})
    return r.plans or meta.get("plans", []), r.cpt_codes or meta.get("cpt_codes", [])
