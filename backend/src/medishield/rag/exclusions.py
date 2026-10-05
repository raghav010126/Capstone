"""Table 4.1 "Excluded CPT Code Ranges" as structured, exactly-matchable rules ("policy as data").

Neither policy PDF lists individual CPT codes; this table is the only machine-readable coverage rule, so
coverage of a code is decided by exact range containment, not by embedding similarity. The table also
contains rows that are *not* exclusions (finding F9): a prior-authorisation row and a copay row. Each row is
classified so a naive "row = excluded" reading cannot deny a covered service.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

RANGE_RE = re.compile(r"^\s*([0-9A-Z]{5})\s*-\s*([0-9A-Z]{5})\s*$")


@dataclass(frozen=True)
class CptRange:
    start: str
    end: str
    category: str
    basis: str
    kind: str          # exclusion | prior_auth | copay_rule
    plan: str
    page: int | None = None

    @property
    def label(self) -> str:
        return f"{self.start}-{self.end}"

    def contains(self, code: str) -> bool:
        code = code.strip().upper()
        if len(code) != 5 or not _same_shape(code, self.start):
            return False
        return _key(self.start) <= _key(code) <= _key(self.end)

    def to_dict(self) -> dict:
        return asdict(self)


def _shape(c: str) -> str:
    """Code family: numeric CPT (99213), Category III (0001T), HCPCS/ADA letter-prefixed (V2100, D0100)."""
    if c.isdigit():
        return "num"
    if c[:4].isdigit() and c[4].isalpha():
        return f"suffix-{c[4]}"
    if c[0].isalpha() and c[1:].isdigit():
        return f"prefix-{c[0]}"
    return "other"


def _same_shape(a: str, b: str) -> bool:
    return _shape(a) == _shape(b)


def _key(c: str) -> tuple:
    s = _shape(c)
    if s == "num":
        return (int(c),)
    if s.startswith("suffix"):
        return (int(c[:4]),)
    if s.startswith("prefix"):
        return (int(c[1:]),)
    return (c,)


def classify_row(category: str, basis: str) -> str:
    text = f"{category} {basis}".lower()
    if "prior auth" in text:
        return "prior_auth"
    if "copay" in text:
        return "copay_rule"
    return "exclusion"


def parse_rows(rows: list[list[str]], plan: str, page: int | None = None) -> list[CptRange]:
    out = []
    for r in rows:
        cells = [str(c).strip() for c in r]
        if len(cells) < 3:
            continue
        m = RANGE_RE.match(cells[0])
        if not m:
            continue
        out.append(CptRange(m.group(1), m.group(2), cells[1], cells[2], classify_row(cells[1], cells[2]),
                            plan, page))
    return out


def lookup(code: str, ranges: list[CptRange]) -> list[CptRange]:
    """All rows containing ``code`` (ranges overlap, e.g. 15000-15999 contains 15820-15829)."""
    return [r for r in ranges if r.contains(code)]
