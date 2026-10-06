"""What each role may ask about, derived from the API's permission matrix (the single source of truth).

Every boundary and every refusal message in the assistant comes from the maps below.
"""

from __future__ import annotations

from medishield.api.security import PERMISSIONS, Role

# source -> permission it needs
SOURCE_PERMISSION: dict[str, str] = {
    "policies": "policy:ask",        # coverage, exclusions, benefits (policy PDFs)
    "own_cases": "case:read",        # cases the user submitted
    "all_cases": "case:read_all",    # any case or member
    "review": "review:queue",        # the review queue and overrides
    "audit": "audit:read",           # the tamper-evident audit trail
    "ops": "ops:read",               # operational metrics: volumes, rates, cost, latency
}
SOURCES = tuple(SOURCE_PERMISSION)

SOURCE_LABELS = {
    "policies": "policy documents", "own_cases": "your own cases", "all_cases": "other people's cases and members",
    "review": "the review queue and overrides", "audit": "the audit trail", "ops": "operational metrics",
}

# analytics tables -> permission (row-level rule for cases/documents: without case:read_all only your own cases are present)
TABLE_PERMISSION: dict[str, str] = {
    "cases": "case:read",
    "documents": "case:read",
    "overrides": "review:queue",
    "audit_events": "audit:read",
    "agent_runs": "ops:read",
}
TABLES = tuple(TABLE_PERMISSION)

ROLE_LABELS = {Role.SUBMITTER: "submitter", Role.REVIEWER: "reviewer", Role.SENIOR_REVIEWER: "senior reviewer",
               Role.AUDITOR: "auditor", Role.ADMIN: "admin"}


def allowed(role: Role, permission: str) -> bool:
    return role in PERMISSIONS[permission]


def sources_for(role: Role) -> list[str]:
    return [s for s, p in SOURCE_PERMISSION.items() if allowed(role, p)]


def restricted_sources_for(role: Role) -> list[str]:
    return [s for s in SOURCES if s not in sources_for(role)]


def tables_for(role: Role) -> tuple[str, ...]:
    return tuple(t for t, p in TABLE_PERMISSION.items() if allowed(role, p))


def own_cases_only(role: Role) -> bool:
    return not allowed(role, "case:read_all")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _article(word: str) -> str:
    return "an" if word[0] in "aeiou" else "a"


def refusal(role: Role, blocked: list[str]) -> str:
    """Informative refusal for a question aimed at sources the role may not use (generated, never hard-coded)."""
    label = ROLE_LABELS[role]
    what = _join([SOURCE_LABELS[s] for s in blocked])
    can = _join([SOURCE_LABELS[s] for s in sources_for(role)])
    return f"As {_article(label)} {label}, you don't have access to {what}. I can answer questions about {can}."


def table_refusal(role: Role, blocked: list[str]) -> str:
    label = ROLE_LABELS[role]
    allowed_tables = tables_for(role)
    scope = " (only your own cases)" if own_cases_only(role) else ""
    return (f"As {_article(label)} {label}, you can't query {_join(blocked)}. Analytics for your role cover "
            f"{_join(list(allowed_tables))}{scope}.")
