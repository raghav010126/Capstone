# Implementation and validation — 6 October 2026

This revision closes unsafe approval paths and corrects the presentation of the evidence. It was verified, published with OCR-first evaluation numbers and deployed to AWS on 7 October; existing live cases were not re-decided or migrated.

## Behavior changes

- Policy analysis now requires evidence for every billed code. Missing model output, omitted codes, unknown/unavailable plans, empty or wrong-plan retrieval and unresolved benefit mapping produce conditional coverage and review. Authoritative exclusions and prior authorization retain precedence.
- Each claim checks its policy number, name, DOB and active status against the member record. A matching active record is enough for claim-only intake. Unknown or conflicting identity requires review; confirmed inactive membership remains a hard failure. Existing ID expiry and tamper checks remain in place.
- Missing required agent results no longer imply success. Non-applicable specialists remain optional for other document types.
- Charges must be finite and nonnegative; a claim total must be positive. A zero-charge line is allowed inside a positive claim. Reconciliation mismatches retain their existing warning/fraud treatment. Invalid totals do not enter the case's monetary aggregate.
- Extraction and retrieval scoring retain failed/missing outputs in their ground-truth denominator. Wrong-plan retrieval fails. Missing gold annotations stop the evaluation instead of shrinking the denominator.
- Runs record timing scope and cache/prefetch provenance. Publishing is explicit and archives prior results. Calibration is fitted on official dev only.
- Offline BM25 loading uses its verified cached English stopword snapshot, avoiding Fastembed's nonexistent dummy weight-file check. `make replay-preflight` verifies the assets; `--download` sets up public model assets when needed.

## Checks completed

| Check | Result |
|---|---|
| SQLite deterministic suite | 312 passed, 2 integration tests deselected (also with an invalid API key) |
| DynamoDB/moto suite | 311 passed, 1 backend-specific skip, 2 integration tests deselected |
| Real pipeline offline replay | 2 passed: upload, OCR/RAG/graph, review/resume, duplicate detection, audit and PDF |
| Saved evaluation artifact gates | 28/28 passed (21 + 7 for the LLM judge and RAGAS, added 10 October); these do not run fresh LLM evaluations |
| Python lint | Passed |
| Frontend ESLint, TypeScript, production build and static export | Passed |
| Isolated browser workflow | Approve/reject/escalate visible; high-value override pending until a different senior reviewer approved; audit chain verified; auditor has no override/reclassification controls |
| Presentation | 12 editable dark slides (figures updated to OCR-first on 7 Oct): 8 main + 4 appendix, ~8-minute script including a 90-second demo; package/layout/font checks passed and all slides inspected after LibreOffice rendering |
| Sample package | 22 original labelled documents, 6 complete cases, 2 policies, fields, records and SHA-256 manifest; `make samples` reproduces it |

The tests use temporary databases, uploads and ledgers, and run with no model access (CI has no API key).

**Live check after the AWS deploy (7 October):** two fresh cases were submitted through the website. C_007 was rejected (excluded procedure code, prescription with missing fields) and C_006 escalated (blurred prescription). Both claim forms showed the new member checks (member found, name, date of birth, active). The Insights page shows the OCR-first numbers, and the assistant answered a coverage question with a citation.

## Current evaluation and limitations

The official dev and held-out splits were replayed on 7 October in **OCR-first** mode (`MEDISHIELD_VISION=auto`), which is what
the live AWS deployment runs, with no prefetch and the response cache enabled. Most model calls were served from the cache
(dev 111/129, held-out 114/133); cache misses were live calls, $0.22 in total for both splits. These are graph replays on the
synthetic dataset, not a blind production evaluation.

| Metric | Dev | Held-out |
|---|---:|---:|
| Documents / cases | 77 / 17 | 78 / 17 |
| Document decisions, all labels | 96.1% | 96.15% |
| Document decisions, visible labels | 100% | 100% |
| Case decisions | 82.4% (14/17) | 88.2% (15/17) |
| Classification | 100% | 100% |
| Required claim fields | 100% | 100% |
| Retrieval Recall@3 | 100% | 100% |
| Model cost per case (uncached equivalent) | $0.079 | $0.082 |
| Calibration ECE, raw → calibrated | 0.077 → 0.021 (fitted here) | 0.098 → 0.018 |

**Decisions are identical to the pre-fix OCR-first baseline on both splits**: the same three documents per split are wrong, all
of them labels the generator never draws on the page. The safety fixes therefore did not escalate any clean case in this data.
An earlier always-vision replay (archived under `docs/eval_results/history/` and `eval/runs/`) differed only on dev `C_023`,
where the vision-mode KYC review raised a two-model tamper warning; that is a perception-mode difference, not a rule change.

Held-out graph latency in this replay is 5.5 s median / 7.0 s p95, cache-assisted and excluding setup. It is not a cold-latency
measurement; a live 5-document case on AWS takes about a minute. Other seed-7, corrected, multilingual, red-team and assistant
results are historical and were not rerun here.

No labels were changed to raise the score. The dataset is synthetic; real scans, independent policies, cold latency, subtle
forged IDs and production review effort remain unproven. Durable AWS graph checkpoints and SSO remain future work.

## Reproduction

```bash
make test-fast
make test-dynamo
make replay-preflight
HF_HUB_OFFLINE=1 MEDISHIELD_LLM_OFFLINE=1 uv run pytest -q -m integration
# Use separate temporary state and ledger paths for evaluation:
MEDISHIELD_VISION=auto MEDISHIELD_STATE_DIR=/tmp/medishield-eval-state MEDISHIELD_LEDGER_PATH=/tmp/medishield-eval-spend.jsonl \
  uv run python eval/run_eval.py --split dev --no-prefetch --publish
# Then repeat for --split heldout, applying the dev calibrator unchanged.
make gates
make report
make samples
```

LLM replay needs a previously populated response cache. On a new machine, generate the dataset and download model assets first; a live evaluation requires configured model access and budget. Integration tests do not silently replace missing cached outputs with approvals.

`docs/MediShield_capstone.pptx` is a finished, editable file: edit it in PowerPoint. `scripts/make_deck.mjs` records how the dark version was produced, but it needs the Artifact Tool runtime, which is not part of this repository, so it is kept for reference only. Its evaluation figures were updated to the OCR-first results by direct text replacement.
