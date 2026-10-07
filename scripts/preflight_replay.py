"""Verify local OCR, policy chunks, embeddings and reranker before an offline replay.

Run once with --download to populate missing public model assets, then run without it.
Does not open the case database, call an LLM, or alter the spend ledger.
"""
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if not args.download:
        os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["MEDISHIELD_TRACING"] = "0"
    from medishield.ocr.engine import _engine
    from medishield.rag.ingest import load_or_ingest, policy_pdfs
    from medishield.rag.retrieve import PolicyStore
    try:
        _engine()
        store = PolicyStore([load_or_ingest(p) for p in policy_pdfs()])
        for plan in store.indexes:
            if not store.search("CPT 99213 office visit benefits", plan, k=3):
                raise RuntimeError(f"no retrieval hits for {plan}")
    except Exception as exc:
        raise SystemExit(f"Replay assets unavailable: {exc}\nRun scripts/preflight_replay.py --download with network access, "
                         "then repeat offline. Generate data/official first (make dataset).") from exc
    print("Replay assets ready: OCR, policy chunks, dense + BM25 + reranker.")
    print("LLM response-cache coverage is separate; replay integration tests verify case outcomes.")


if __name__ == "__main__":
    main()
