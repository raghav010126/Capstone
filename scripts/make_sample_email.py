"""Build a demo .eml: one email from an allow-listed sender with a dataset case's documents attached.

Usage: python scripts/make_sample_email.py C_002 build/demo/claim-email-C_002.eml [--sender claims@clinic.example]
Upload it on New case -> "Submit an email" (or POST /api/intake/email). Through the API an .eml must stay under ~4 MB;
mail delivered by SES has no such limit.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cluster")
    ap.add_argument("out")
    ap.add_argument("--sender", default="claims@clinic.example")
    ap.add_argument("--dataset", default=str(REPO / "data" / "official" / "dataset"))
    a = ap.parse_args()
    root = Path(a.dataset)
    docs = [m for m in json.loads((root / "metadata.json").read_text()) if m["case_cluster_id"] == a.cluster]
    if not docs:
        raise SystemExit(f"no documents for {a.cluster}")
    msg = EmailMessage()
    msg["From"], msg["To"] = a.sender, "intake@medishield.example"
    msg["Subject"] = f"Claim submission - {len(docs)} documents"
    msg["Date"], msg["Message-ID"] = formatdate(localtime=True), make_msgid(domain="clinic.example")
    msg.set_content("Please find the claim documents attached.\n\nClinic billing office")
    for m in docs:
        path = root / m["file_path"]
        maintype, subtype = (mimetypes.guess_type(path.name)[0] or "application/octet-stream").split("/")
        msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(msg))
    print(f"{out} ({out.stat().st_size / 1e6:.2f} MB, {len(docs)} attachments, from {a.sender})")


if __name__ == "__main__":
    main()
