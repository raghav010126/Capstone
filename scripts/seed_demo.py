"""Submit dataset cases through the API (as the demo `submitter`) and wait for each to finish.

    python scripts/seed_demo.py --api http://localhost:8100 C_002 C_012 C_019 unknown_bank_statement_001

Arguments are dataset cluster ids (a patient's bundle of documents) or standalone unknown-document ids.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1] / "data" / "official" / "dataset"


def bundle(ident: str) -> list[Path]:
    meta = json.loads((ROOT / "metadata.json").read_text())
    rows = [m for m in meta if m["case_cluster_id"] == ident or m["doc_id"] == ident]
    if not rows:
        sys.exit(f"unknown case {ident!r}")
    return [ROOT / m["file_path"] for m in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8100")
    ap.add_argument("--user", default="submitter")
    ap.add_argument("cases", nargs="+")
    a = ap.parse_args()
    with httpx.Client(base_url=a.api, timeout=120) as c:
        tok = c.post("/auth/login", json={"username": a.user, "password": f"{a.user}-demo"}).raise_for_status().json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        for ident in a.cases:
            files = [("files", (p.name, p.read_bytes(), "image/png")) for p in bundle(ident)]
            r = c.post("/cases", files=files, headers=h)
            r.raise_for_status()
            cid = r.json()["case_id"]
            t0 = time.time()
            while True:
                d = c.get(f"/cases/{cid}", headers=h).json()
                if d["status"] not in ("RECEIVED", "PROCESSING"):
                    break
                time.sleep(1)
            print(f"{ident:30s} -> {cid} {d['status']:10s} AI={d['ai_decision']} ${d['total_amount']:,.0f}  {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
