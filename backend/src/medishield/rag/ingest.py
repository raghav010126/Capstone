"""Policy PDF ingestion with Docling: section-aware chunks + the structured exclusion table.

* Chunks follow the numbered section tree (``4.1 Excluded CPT Code Ranges``); un-numbered headers such as
  definition terms become sub-sections of the current numbered section.
* Tables are kept whole and serialised as Markdown. A table split across pages whose second fragment has no
  header row (finding F8) is stitched back together before chunking and before range parsing.
* Results are cached per PDF hash, so re-ingestion only happens when a policy changes; uploading a new PDF
  regenerates its exclusion rules automatically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from medishield.config import get_settings
from medishield.rag.exclusions import CptRange, parse_rows

log = logging.getLogger(__name__)
INGEST_VERSION = "1"
NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")
PRODUCT_RE = re.compile(r"Product Code:\s*([A-Z0-9-]+)")
MAX_CHARS = 1600


@dataclass
class Chunk:
    chunk_id: str
    plan: str
    section: str               # numbered section title, e.g. "4.1 Excluded CPT Code Ranges (Machine-Readable)"
    section_no: str            # "4.1"
    subsection: str | None
    pages: list[int]
    kind: str                  # text | table
    text: str

    @property
    def embed_text(self) -> str:
        head = f"{self.plan.title()} Plan > {self.section}" + (f" > {self.subsection}" if self.subsection else "")
        return f"{head}\n{self.text}"


@dataclass
class PolicyIndex:
    plan: str
    product_code: str | None
    source: str
    chunks: list[Chunk] = field(default_factory=list)
    ranges: list[CptRange] = field(default_factory=list)


def plan_from_filename(path: Path) -> str:
    name = path.stem.lower()
    for plan in ("gold", "silver", "bronze", "platinum"):
        if plan in name:
            return plan
    return name


def _table_rows(tb, doc) -> tuple[list[str], list[list[str]]]:
    df = tb.export_to_dataframe(doc=doc)
    cols = [str(c) for c in df.columns]
    return cols, [[str(v) for v in row] for row in df.values.tolist()]


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _convert(pdf: Path):
    return _converter().convert(pdf).document


@lru_cache
def _converter():
    from docling.document_converter import DocumentConverter

    return DocumentConverter()


def ingest_pdf(pdf: Path, plan: str | None = None) -> PolicyIndex:
    from docling_core.types.doc import DocItemLabel, TableItem

    plan = plan or plan_from_filename(pdf)
    doc = _convert(pdf)
    idx = PolicyIndex(plan=plan, product_code=None, source=pdf.name)
    section, section_no, sub = "Front matter", "0", None
    buf: list[str] = []
    buf_pages: set[int] = set()
    tables: list[dict] = []          # pending tables in the current section (for stitching)

    def flush_text() -> None:
        nonlocal buf, buf_pages
        text = "\n".join(buf).strip()
        if text:
            for part in _split(text):
                idx.chunks.append(Chunk("", plan, section, section_no, sub, sorted(buf_pages), "text", part))
        buf, buf_pages = [], set()

    def flush_tables() -> None:
        for t in tables:
            idx.chunks.append(Chunk("", plan, section, section_no, sub, t["pages"], "table",
                                    _md_table(t["header"], t["rows"])))
            idx.ranges.extend(parse_rows([t["header"]] + t["rows"], plan, t["pages"][0] if t["pages"] else None))
        tables.clear()

    for item, _lvl in doc.iterate_items():
        label = getattr(item, "label", None)
        page = item.prov[0].page_no if getattr(item, "prov", None) else None
        if isinstance(item, TableItem):
            header, rows = _table_rows(item, doc)
            numeric_header = all(re.fullmatch(r"\d+", h) for h in header)
            if tables and numeric_header and len(header) == len(tables[-1]["header"]):
                tables[-1]["rows"].extend(rows)                       # stitch headerless continuation
                tables[-1]["pages"] = sorted(set(tables[-1]["pages"]) | {page})
            else:
                if numeric_header:                                    # no header and nothing to stitch to
                    header = [f"col{i}" for i in range(len(header))]
                tables.append({"header": header, "rows": rows, "pages": [page] if page else []})
            continue
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        if idx.product_code is None and (m := PRODUCT_RE.search(text)):
            idx.product_code = m.group(1)
        if label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE):
            m = NUMBERED.match(text)
            if m:
                flush_text()
                flush_tables()
                section, section_no, sub = text, m.group(1), None
            else:
                flush_text()
                sub = text.rstrip(":")
                buf.append(f"{text}")
                if page:
                    buf_pages.add(page)
            continue
        if label in (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER):
            continue
        prefix = "* " if label == DocItemLabel.LIST_ITEM else ""
        buf.append(prefix + text)
        if page:
            buf_pages.add(page)
    flush_text()
    flush_tables()
    for i, c in enumerate(idx.chunks):
        c.chunk_id = f"{plan}-{i:03d}"
    return idx


def _split(text: str) -> list[str]:
    """Split long sections on line boundaries into ~MAX_CHARS pieces (sections here are short)."""
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) > MAX_CHARS:
            parts.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _cache_file(pdf: Path) -> Path:
    h = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]
    return get_settings().cache_dir / "policy_index" / f"{pdf.stem}-{h}-v{INGEST_VERSION}.json"


def is_cached(pdf: Path) -> bool:
    return _cache_file(pdf).exists()


def load_or_ingest(pdf: Path) -> PolicyIndex:
    cache = _cache_file(pdf)
    if cache.exists():
        d = json.loads(cache.read_text())
        return PolicyIndex(d["plan"], d["product_code"], d["source"], [Chunk(**c) for c in d["chunks"]],
                           [CptRange(**r) for r in d["ranges"]])
    log.info("ingesting %s with Docling", pdf.name)
    idx = ingest_pdf(pdf)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"plan": idx.plan, "product_code": idx.product_code, "source": idx.source,
                                 "chunks": [asdict(c) for c in idx.chunks],
                                 "ranges": [r.to_dict() for r in idx.ranges]}, indent=1))
    return idx


def policy_pdfs(root: Path | None = None) -> list[Path]:
    root = root or get_settings().data_root
    return sorted((root / "dataset" / "policies").glob("*.pdf"))
