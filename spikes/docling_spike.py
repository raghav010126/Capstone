"""Spike: Docling on the Gold/Silver policy PDFs - sections, tables, and the untagged table 4.1."""
import re, sys, time
from pathlib import Path
from docling.document_converter import DocumentConverter

RANGE = re.compile(r"^\s*([0-9A-Z]{5})\s*-\s*([0-9A-Z]{5})\s*$")
conv = DocumentConverter()
for plan in ("gold", "silver"):
    pdf = Path(f"data/official/dataset/policies/medishield_{plan}_plan.pdf")
    t0 = time.time(); doc = conv.convert(pdf).document; dt = time.time() - t0
    heads = [t.text for t in doc.texts if t.label in ("section_header", "title")]
    print(f"\n=== {plan.upper()}  {dt:.1f}s  pages={len(doc.pages)}  tables={len(doc.tables)}  headers={len(heads)}")
    print("  headers:", heads[:14], "...")
    for i, tb in enumerate(doc.tables):
        df = tb.export_to_dataframe(doc=doc)
        cols = [str(c) for c in df.columns]
        ranges = [r for r in df.astype(str).values.tolist() if r and RANGE.match(r[0])]
        page = tb.prov[0].page_no if tb.prov else "?"
        print(f"  table {i}: page {page} shape={df.shape} cols={cols[:3]} cpt_range_rows={len(ranges)}")
        if ranges:
            print("    first:", ranges[0], "| last:", ranges[-1])
    md = doc.export_to_markdown()
    Path(f"spikes/out/{plan}.md").write_text(md)
    print("  range lines anywhere in markdown:", len(re.findall(r"\|\s*[0-9A-Z]{5}\s*-\s*[0-9A-Z]{5}\s*\|", md)))
