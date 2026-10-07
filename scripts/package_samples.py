"""Build a deterministic, self-contained sample package of complete synthetic cases."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    data = ROOT / "data/official"
    labels = json.loads((data / "ground_truth/labels.json").read_text())
    fields = json.loads((data / "ground_truth/fields.json").read_text())
    meta = json.loads((data / "dataset/metadata.json").read_text())
    # Representative complete bundles: clean, review, uncovered and ID checks, plus
    # unknown documents. Preserve related dates and original case-level label context.
    cases = {"C_001", "C_002", "C_012", "C_023", "unknown_bank_statement_001", "unknown_utility_bill_001"}
    chosen = [m for m in meta if labels["documents"][m["doc_id"]]["case_id"] in cases]
    ids = {m["doc_id"] for m in chosen}
    files = {"dataset/" + m["file_path"]: (data / "dataset" / m["file_path"]).read_bytes() for m in chosen}
    for p in sorted((data / "dataset/policies").glob("*.pdf")):
        files["dataset/policies/" + p.name] = p.read_bytes()
    for p in sorted((data / "records").glob("*.json")):
        files["records/" + p.name] = p.read_bytes()
    def add_json(name, obj):
        files[name] = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
    add_json("dataset/metadata.json", chosen)
    add_json("ground_truth/fields.json", {d: fields[d] for d in sorted(ids) if d in fields})
    add_json("ground_truth/labels.json", {
        "documents": {d: labels["documents"][d] for d in sorted(ids)},
        "cases": {c: labels["cases"][c] for c in sorted(cases)},
        "splits": {},
    })
    files["README.txt"] = (f"MediShield synthetic samples: {len(chosen)} documents across {len(cases)} complete cases.\n"
                           "Includes complete representative bundles with at least 20 documents, both policies,\n"
                           "original labels, expected fields and synthetic member/history records. No real patient data.\n"
                           "Extract, then evaluate with: python eval/run_eval.py --dataset EXTRACTED_PATH --split all\n"
                           "See repository README for dependencies and model setup. Labels retain known generator limitations.\n").encode()
    assert len(chosen) >= 20 and len([n for n in files if n.startswith("dataset/policies/")]) == 2
    add_json("manifest.json", {n: hashlib.sha256(b).hexdigest() for n, b in sorted(files.items())})
    out = ROOT / "docs/samples/medishield-samples.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, "w") as z:
        for name, content in sorted(files.items()):
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, content)
    print(f"{out}: {len(chosen)} labelled documents, {len(cases)} complete cases, 2 policies")


if __name__ == "__main__":
    main()
