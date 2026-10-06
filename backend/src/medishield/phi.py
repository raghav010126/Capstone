"""PHI redaction shared by logs, traces and error messages (no web-framework imports)."""

from __future__ import annotations

import re

_PHI_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "[DATE]"),
    (re.compile(r"\bMED-[A-Z]{3}-\d{5,}\b"), "[POLICY]"),
    (re.compile(r"\bNPI-?\d{10}\b"), "[NPI]"),
    (re.compile(r"\b(?:RX-)?CLM-\d{4}-\d+\b"), "[CLAIM_NO]"),
    (re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+ [A-Z]\.(?!\w)"), "[NAME]"),
    (re.compile(r"\bDr\.? [A-Z][a-z]+(?: [A-Z][a-z]+)?,? ?(?:MD|DO|M\.D\.|D\.O\.)?"), "[PROVIDER]"),
    (re.compile(r"(?i)bearer\s+[\w.-]+"), "Bearer [TOKEN]"),
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "[JWT]"),               # any JWT, wherever it appears
    (re.compile(r"(?i)([?&]token=)[^&\s\"]+"), r"\1[TOKEN]"),            # WebSocket / SSE URLs carry the login token
]


def redact(text: str) -> str:
    for pat, repl in _PHI_PATTERNS:
        text = pat.sub(repl, text)
    return text
