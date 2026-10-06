"""Build MediShield's "system of record" for a generated dataset.

The official generator emits no member database or claim history, but the KYC agent must validate members
and the fraud agent must score against historical baselines. This script derives:

* ``members.json``        - the 30 dataset members (from the generator's own cluster data) plus synthetic
                            background members, all enrolled in the Gold plan for calendar 2025;
* ``claims_history.json`` - seeded historical claims (2023-2024, i.e. strictly before every 2025 date of
                            service, so history can never create a spurious duplicate or 30-day readmission).
                            Charges use the generator's own CPT price list with small noise, giving realistic
                            per-provider billing baselines.

Usage: python datagen/records.py data/official
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import OFFICIAL

HISTORY_SEED = 2024
N_BACKGROUND_MEMBERS = 270
N_HISTORY_CLAIMS = 2000
PLAN = {"plan": "GOLD", "product_code": "GLD-2025-US-IL", "coverage_start": "2025-01-01",
        "coverage_end": "2025-12-31"}


def official_pools() -> dict:
    """Load the generator's constant pools (names, doctors, codes) without running it."""
    src = (OFFICIAL / "generate_docs.py").read_text(encoding="utf-8")
    head = src.partition('\nif __name__ == "__main__":\n')[0]
    ns: dict = {"__name__": "__pools__"}
    exec(compile(head, "generate_docs.py", "exec"), ns)
    return ns


def build(root: Path) -> None:
    pools = official_pools()
    clusters = json.loads((root / "ground_truth" / "clusters.json").read_text())["clusters"]
    rng = random.Random(HISTORY_SEED)

    members = []
    for c in clusters:
        street, city, st = (p.strip() for p in c["address"].rsplit(",", 2))
        members.append({
            "member_id": c["patient_id"], "policy_number": c["policy"], "group_number": c["group_number"],
            "full_name": c["name"], "dob": _iso(c["dob"]), "gender": c["gender"],
            "address": {"street": street, "city": city, "state": st}, "status": "ACTIVE",
            "riders": [], "in_dataset": True, **PLAN,
        })
    used_policies = {m["policy_number"] for m in members}
    used_ids = {m["member_id"] for m in members}
    for _ in range(N_BACKGROUND_MEMBERS):
        gender = rng.choice("MF")
        name = rng.choice(pools["NAMES_M"] if gender == "M" else pools["NAMES_F"]) + f" {chr(rng.randint(65, 90))}."
        while (pid := f"PT_{rng.randint(10000, 99999)}") in used_ids:
            pass
        while (pol := f"MED-GLD-{rng.randint(1000000, 9999999)}") in used_policies:
            pass
        used_ids.add(pid)
        used_policies.add(pol)
        st = rng.choice(pools["STATE_POOL"])
        members.append({
            "member_id": pid, "policy_number": pol, "group_number": f"GRP-{rng.randint(10000, 99999)}",
            "full_name": name, "dob": date(rng.randint(1945, 2003), rng.randint(1, 12), rng.randint(1, 28)).isoformat(),
            "gender": gender,
            "address": {"street": rng.choice(pools["STREETS"]), "city": rng.choice(st["cities"]), "state": st["abbr"]},
            "status": "ACTIVE", "riders": [], "in_dataset": False, **PLAN,
        })

    history = []
    start, span = date(2023, 1, 1), (date(2024, 12, 31) - date(2023, 1, 1)).days
    for n in range(N_HISTORY_CLAIMS):
        m = rng.choice(members)
        doctor, npi = rng.choice(pools["DOCTORS"])
        lines = []
        for code, desc, price in rng.sample(pools["CPT_POOL"], k=rng.randint(1, 3)):
            lines.append({"cpt": code, "description": desc, "charge": round(price * rng.gauss(1.0, 0.05), 2)})
        icd = rng.choice(pools["ICD_POOL"])[0]
        history.append({
            "claim_id": f"HCLM-{n + 1:06d}", "member_id": m["member_id"], "policy_number": m["policy_number"],
            "service_date": (start + timedelta(days=rng.randint(0, span))).isoformat(),
            "provider_name": doctor, "provider_npi": npi, "facility": rng.choice(pools["HOSPITALS"]),
            "icd_codes": [icd], "lines": lines, "total_charge": round(sum(ln["charge"] for ln in lines), 2),
            "status": "PAID" if rng.random() < 0.92 else "DENIED",
        })
    history.sort(key=lambda h: h["service_date"])

    out = root / "records"
    out.mkdir(exist_ok=True)
    (out / "members.json").write_text(json.dumps(members, indent=1))
    (out / "claims_history.json").write_text(json.dumps(history, indent=1))
    print(f"members: {len(members)} ({len(clusters)} dataset + {N_BACKGROUND_MEMBERS} background) | "
          f"history claims: {len(history)} ({history[0]['service_date']} .. {history[-1]['service_date']}) -> {out}")


def _iso(mdy: str) -> str:
    m, d, y = mdy.split("/")
    return f"{y}-{m}-{d}"


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "data/official"))
