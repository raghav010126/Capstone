# MediShield Multi-Agent Document Intake — "Top-5" Capstone Plan

## Context
Capstone for the AI Engineering Bootcamp. The deadline is **21 Oct 2026, 23:59 IST**, about 17 days away. The user chose
Assignment 02 (multi-agent claims intake). Only the top 5 submissions win, so the bar is not "complete the brief". It is
"clearly the most production-grade, measurable and well-presented submission".

**How graders score** (from Capstone_Submission_Instruction.pdf):
- 40% Implementation, Architecture & Engineering
- 30% Presentation & Demo
- 10% Docs & **Deployment**
- 20% participation

They also judge four qualities explicitly: **Correctness, Safety (guardrails + permissions), System thinking ("real product,
not demo"), and Clarity (explaining decisions and trade-offs)**.

**Required submission:**
- A public GitHub repo with no secrets.
- A README containing the demo-video link, setup instructions and the approach.
- A 5–10 minute demo video.

**Assignment rubric:**

| Criterion | Weight |
|---|---|
| Classification | 20% |
| Extraction | 20% |
| Policy retrieval | 15% |
| **Decision correctness** | **25%** |
| UI | 10% |
| Code quality | 10% |

### Key discovery: the official dataset generator (`Assignment2_datagen_scripts/`)
The instructors provided scripts that generate 151 labelled PNGs plus 4 out-of-distribution "unknown" docs, Gold and
Silver policy PDFs, and `metadata.json`. Graders will very likely evaluate against this data. Analysis found **flaws
that most students will miss**. Turning them into explicit, well-documented engineering decisions is our biggest
"Clarity/Correctness" advantage.

1. **`expected_decision` exists only for the 4 unknown docs**, despite the overview claiming otherwise. The other 151 docs
   only have `fraud_label`, `fraud_reason` and `edge_flags`. **We must derive ground truth ourselves**, using an
   explicit, auditable labeler.
2. **Some labels are present in metadata but never drawn on the image:**
   - The name-mismatch fraud (`id_PT_39451`).
   - All 3 tampered IDs (`generate_id_document` at line 796 never passes `tampered`).
   - The structuring fraud (C_004 is a UB-04 form, and only the CMS-1500 generator injects structuring).
   - Only 1 of the 3 "blurry" prescriptions is actually blurred.
3. **Every member is on the Gold plan** (`MED-GLD-…`). The Silver PDF acts as a retrieval distractor.
4. **No individual CPT code appears in either PDF.** The only codes are the 18 range rows of table "4.1 Excluded CPT
   Code Ranges", which has no bookmark. All 5 "uncovered" codes fall inside these ranges. The table also contains
   overlapping ranges, 2 rows that are not exclusions (a prior-auth row and a copay row), and broken section references.
5. **ICD/CPT pairs are random.** A general medical-plausibility check would flag almost every claim. Only obstetric
   59400 on a non-pregnancy diagnosis is an intended mismatch.
6. **The ID-expiry reference date is the date of service, not today.** Checking against Oct 2026 would mark all 5
   "expiring-soon" IDs as expired.
7. **No member database or claim history is emitted.** We must build the "system of record" ourselves.
8. **Fonts are Windows-only.** On macOS, all text silently falls back to a tiny bitmap font. All images are PNG, so
   Error Level Analysis (ELA) has nothing to find. The Gold PDF is written to `./policy/` instead of
   `dataset/policies/`.

## User decisions (2026-10-04)
- **Frontend: Next.js**, as the brief specifies. Install Node Active LTS into `~/.local/node` from the official
  nodejs.org tarball (no brew or admin needed) and add it to PATH in `~/.zshrc`.
- **Live public deploy** with a demo mode: rate limit plus a daily LLM budget cap.
- **Model routing by complexity:**
  - `claude-sonnet-5-5` for perception and summarization.
  - `claude-opus-5-5` for reasoning-heavy steps, and as the retry model when a Sonnet result fails a check (table below).
- **All 6 bonus challenges.**

## Environment (verified)
- **Machine:** macOS, M4 Pro, 48 GB RAM.
- **Installed:** uv 0.12, CPython 3.12/3.13/3.14 (managed by uv), gh CLI.
- **Not installed:** Node, Docker, brew, Tesseract, Redis.
- **Fonts available for the font shim:** Arial and Courier New (`/System/Library/Fonts/Supplemental`), Brush Script and
  Apple Chancery (for signatures), Devanagari Sangam MN and Kohinoor (for Hindi).
- **API key:** `ANTHROPIC_API_KEY` exists in `~/Downloads/medibot/.env`. Copy it into the new `.env` and never commit it.
- **New standalone project: `~/Desktop/medishield-capstone`**, using Python 3.12 for Docling compatibility. It holds
  only the capstone; nothing comes from the MediBot assignment. The step-0 bootstrap below sets it up.
- **Reuse from MediBot** (`~/Downloads/medibot/src/medibot`):
  - `llm.py`: Anthropic wrapper with structured output, refusal fallbacks and the `stop_reason` check. Generalize it
    to per-agent model and effort.
  - `ingestion/parse.py` and `chunk.py`: Docling parsing and heading-aware chunking.
  - `retrieval/store.py`, `embeddings.py`, `rerank.py`: Qdrant (Cloud or embedded path), fastembed, bge reranker.
  - `auth.py`: JWT.
  - `scripts/redteam.py`: harness pattern.

---

## Winning strategy: 6 differentiators (each maps to a grading signal)

1. **Eval-driven, measured results on the *official* data** (Correctness, Clarity).
   - `eval/run_eval.py` scores all 155 official docs on the exact rubric metrics: classification accuracy, field-level
     extraction completeness, policy retrieval Recall@k/MRR, and decision accuracy.
   - It also reports per-fraud-scenario detection, per-edge-case recall, latency p50/p95, cost per case, and
     calibration (ECE and Brier score).
   - **Generalization check:** regenerate the dataset with an unseen seed (e.g. 7) that we never inspect during
     development, and report on it too.
   - Prompt iteration uses a dev split of clusters only. Reported numbers come from the held-out split, the full set
     and seed 7.
2. **The LLM perceives; deterministic code decides** (Safety, System thinking).
   - The orchestrator's decision is a pure, unit-tested decision table configured in `decision_policy.yaml`.
   - LLMs only extract and reason. They cannot flip a decision, so prompt injection cannot approve a claim.
   - Sonnet writes the justification, constrained to cite agent outputs.
3. **Evidence-grounded extraction.**
   - RapidOCR returns raw text and bounding boxes. Claude returns structured fields.
   - Each field is fuzzy-matched back to an OCR box, which gives a `grounded` flag and a box.
   - Ungrounded fields lower confidence, which catches hallucinations.
   - In the UI, clicking a field highlights it on the document image.
4. **"Dataset Findings" and Architecture Decision Records (ADRs)** (Clarity).
   - `docs/dataset_findings.md` documents every generator flaw above with line numbers.
   - The labeler encodes our interpretation explicitly.
   - Metrics are reported two ways: overall, and on the subset whose label is actually visible in the pixels.
   - **Corrected dataset:** we also ship a patched generator that actually renders tampering (a re-saved JPEG with a
     pasted region, so ELA can see it), the name mismatch, structuring, and real blur. Results are reported on it
     separately.
5. **Production safety and governance:**
   - RBAC with five roles. Overrides need a reason code, and high-value overrides need a second approver ("four-eyes").
   - A hash-chained, tamper-evident audit log.
   - Prompt-injection red-team suite.
   - PHI redaction in logs and traces.
   - Upload hardening: file-type checks by magic bytes, size and page limits, decompression-bomb guard.
   - Idempotent ingestion (SHA-256 plus perceptual hash), rate limiting and an LLM budget guard.
6. **Live deploy plus an ops/business dashboard.**
   - Shows straight-through-processing rate, time-to-decision versus the 4.2-day baseline, cost per case, and projected
     annual savings against the $18.4M baseline.
   - The pipeline graph lights up live over WebSocket.

---

## Architecture

```
Next.js (Vercel) ──REST/WS──> FastAPI (HF Spaces Docker) ──> Huey queue (Redis if REDIS_URL, else SQLite)
                                   │                               │
                       Postgres (Supabase) / SQLite          Worker: LangGraph pipeline
                       S3 storage (Supabase/R2/MinIO) / FS   ├─ Qdrant (Cloud / embedded)
                       hash-chained audit log                └─ Claude Sonnet 5.5 / Opus 5.5, RapidOCR, Docling
```

### LangGraph case graph
A case is a bundle of 1 to N documents. The graph produces a verdict per document and a roll-up per case.

`RECEIVED → PREPROCESS (quality metrics + OCR) → CLASSIFIED → [Send API fan-out per doc type: KYC ‖ CLAIMS ‖ POLICY] → FRAUD_CHECK (case-level + history) → AGGREGATED → DECIDED → (interrupt: HUMAN_REVIEW) → FINALIZED`

- **Policy can run in parallel with Claims.** The brief has Policy needing the CPT codes from Claims while drawing
  them as parallel. We resolve this by having the pre-processor extract CPT codes before the fan-out. This is
  documented as an ADR.
- **Conditional routing by document type:**

  | Document type | Routed to |
  |---|---|
  | `CLAIM_FORM` | Claims, then Policy |
  | `ID_DOCUMENT` | KYC |
  | `DISCHARGE_SUMMARY` | Claims-lite (dates, ICD, CPT) |
  | `PRESCRIPTION` | Claims-lite (prescriber, NPI, DEA, drug, date) |
  | `POLICY_AMENDMENT` | KYC-lite, plus checks on attached supporting documents |
  | `UNKNOWN`, or confidence < 0.6 | Human review queue |

- **Human-in-the-loop:** LangGraph `interrupt()` pauses the graph for review. A human override or reclassification
  resumes it from the checkpoint (Postgres or SQLite checkpointer).

### Model routing (per-agent, env-overridable)

| Step | Model / effort | Retry on Opus 5.5 when… | Deterministic parts |
|---|---|---|---|
| Classifier | Sonnet 5.5, low | confidence < 0.75 | blur and blank detection (Laplacian variance, entropy) |
| Field extraction (OCR) | Sonnet 5.5, medium | schema invalid, grounding < 0.8, or blurry | RapidOCR text and boxes; field grounding |
| KYC | Sonnet 5.5, medium (visual inspection) | anomaly suspected | member-DB match (fuzzy name, DOB, policy); expiry vs **date of service**; ELA; typography check |
| Claims | uses extraction output | n/a | ICD-10/CPT regex and known-code tables, required fields, totals equal sum of lines, NPI format (**not Luhn**: dataset NPIs fail the checksum) |
| Policy (RAG) | **Opus 5.5, high** | n/a | parsed exclusion-range index (exact containment); plan filter by policy prefix |
| Fraud | **Opus 5.5, high** (cross-document narrative and signals, capped weight) | n/a | duplicate check (perceptual hash plus claim number, DOS, amount); readmission ≤30 days; Rx date beyond DOS; obstetric CPT without pregnancy ICD; structuring (total in $9k–$10k, sum mismatch, code 99999); name mismatch; provider billing z-score; frequency baselines |
| Orchestrator | decision table; justification by Sonnet 5.5, low | n/a | precedence rules and confidence aggregation |

**SDK idioms:**
- Use `anthropic` with `client.messages.parse()` and Pydantic models for structured output.
- Set `output_config.effort` explicitly. Thinking cannot be disabled on Sonnet 5.5 or Opus 5.5, and Opus 5.5's
  default effort is medium.
- Enable refusal fallbacks (`fallbacks="default"` with the `server-side-fallback-2026-07-01` beta).
- Use prompt caching on stable system prompts and policy context.
- Cache LLM responses on disk, keyed by model, prompt hash and image hash. Eval re-runs are then free and
  deterministic, and CI replays a committed subset.

### Decision engine precedence (default `decision_policy.yaml`, matches the brief's rule)
Evaluated top to bottom; the first matching rule wins:

1. `UNKNOWN` document, or classifier confidence < 0.6 → **ESCALATE**
2. Hard failure (KYC failed, procedure not covered, or schema invalid) → **REJECT**
   - This takes precedence over fraud. For example, C_012's uncovered $9,950 claim also looks like structuring.
3. Fraud score ≥ 0.3, or any agent confidence < 0.6 → **ESCALATE**
4. Otherwise → **APPROVE**

Rules apply only where an agent ran: N/A checks are skipped for non-claim docs. Tamper suspicion maps to REJECT by
default, as the brief specifies. An alternative "tamper → ESCALATE" policy is documented and configurable.

### Policy RAG (Docling) — "policy as data"
- **Ingestion:** Docling (no OCR needed; the PDF text layer is clean) produces a section tree from headings and
  bookmarks.
  - Tables are kept whole. When a table is split across pages, its header is re-attached to the second fragment.
  - Each chunk carries metadata: plan, section, page and product code.
- **Exclusion table:** table 4.1 is parsed into structured `CptRange` rows. These handle alphanumeric ranges
  (`0001T`, `V2100`, `D0100`) and overlaps, and classify each row as an exclusion, a prior-auth rule or a copay rule.
  The rows are stored in the database. Uploading a new policy PDF regenerates these rules automatically, which is the
  "real-time upload" requirement.
- **Retrieval:**
  1. Map CPT to its description, using a code table plus the description printed on the form.
  2. Run hybrid search (BM25 + dense fastembed in Qdrant), filtered to the member's plan.
  3. Rerank with bge.
  4. Opus 5.5 returns `{covered, coverage_percentage, policy_clause, exclusions}` with page citations.
     `coverage_percentage` = 100 − member coinsurance for the matched benefit category.
- **Retrieval gold set:** CPT → expected section/clause for every code in the generator's pools. Reports Recall@k and
  MRR, which turns "manual spot-check" into a number.

### Data layer
- **Member database and claim history.** `datagen/export_records.py` runs the generator in instrumented mode and
  exports:
  - `members` (name, DOB, policy, group, address, plan).
  - A seeded synthetic history of about 2k past claims across members and providers, used for frequency and
    provider-billing baselines.
  - Every processed claim is appended to the history, so cross-submission duplicates are detectable.
- **Database tables:** cases, documents, agent_runs (model, tokens, cost, latency), decisions, overrides,
  audit_events (`hash = sha256(prev_hash + event)`), users, policies, cpt_ranges.
- **Storage interface:** LocalFS for dev; an S3 adapter (boto3) that works with Supabase Storage, R2, MinIO or AWS,
  tested with moto.

### UI (Next.js App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query + React Flow)
Types are generated from FastAPI's OpenAPI schema with `openapi-typescript`, so types are checked end to end.

| Page | Contents |
|---|---|
| Login | demo accounts per role |
| Dashboard | cases, status badges, filters, KPI tiles |
| New case | drag-and-drop multi-file upload; live **pipeline graph** over WebSocket |
| Case detail | document viewer with zoom; bounding-box overlay linked to fields; ELA heatmap toggle; collapsible panels per agent (model used, retry on Opus or not, tokens, latency); decision panel with confidence, justification and cited clause with page link |
| Review queue | escalations sorted by risk and SLA; override or reclassify with reason codes; four-eyes approval above $10k |
| Audit log | timeline with a "chain verified" badge; **Download Case Report (PDF)** |
| Policies (admin) | upload a PDF and watch live ingestion; preview sections and the parsed exclusion table |
| Insights | eval scorecard, confusion matrices, calibration curve, cost and latency, business-impact panel |

### Bonus challenges
| Bonus | Approach |
|---|---|
| Calibration | reliability diagram, ECE and Brier score; isotonic calibration fitted on the dev split and applied to held-out; use the `dataviz` skill for charts |
| WebSockets | graph node events go to a broadcaster (Redis pub/sub or in-process), then to `/ws/cases/{id}` |
| Tamper detection | ELA on JPEG uploads, with a heatmap; a typography-consistency check (OCR glyph height, offset and colour outliers) for PNG; the corrected set provides real tampered JPEGs |
| Multi-language | Spanish and Hindi variants generated with system fonts; RapidOCR Latin and Devanagari models, with Claude vision as fallback; fields normalized to English with `source_language` |
| Audit PDF export | ReportLab: thumbnails, agent outputs, decision, overrides, audit hash chain |
| LangSmith | `wrap_anthropic` plus LangGraph tracing per case (tokens, latency, cost); PHI anonymizer on traces |

### Deployment (every external service is optional, with a local fallback)
| Component | Service |
|---|---|
| Frontend | Vercel |
| API and worker | one Docker container on Hugging Face Spaces (free CPU tier, 16 GB) |
| Database and storage | Supabase (Postgres + S3-compatible storage) |
| Vectors | Qdrant Cloud |
| Queue | Upstash Redis |
| Tracing | LangSmith |

- **Docker without Docker locally:** the Dockerfile is verified by GitHub Actions (`docker build`) and by HF's remote
  build.
- **Demo mode:**
  - Pre-processed showcase cases are seeded at startup.
  - Live uploads are rate-limited.
  - A daily $ budget is enforced from token accounting.
- **Keep-warm:** a GitHub Actions cron pings the Space so graders aren't hit by a sleeping Space.
- **CI** (`.github/workflows/ci.yml`): ruff, mypy, pytest (unit plus replayed-LLM integration), gitleaks, frontend
  typecheck/build, Docker build.

---

## Working agreement: checkpoints (I stop and report at each)
Work runs in 7 checkpoints. At the end of each one I stop, show what was built and measured, and wait for the user's
go-ahead before starting the next.

| # | Checkpoint | What gets built | What the user sees at the stop | Spend / installs |
|---|---|---|---|---|
| **1** | **Foundation (now)** | uv project (venv in `~/.cache/medishield`); official dataset generated with the font fix and seeded pixels; harness that captures ground truth (every drawn string and field); `eval/labels.py`; member records and claim-history export; spikes for RapidOCR and for Docling's table-4.1 parse; draft `docs/dataset_findings.md` | sample images opened, label counts (APPROVE/REJECT/ESCALATE), spike results (OCR text vs truth, parsed exclusion ranges), any surprises | No Claude calls ($0). Python packages only, inside the venv. |
| 2 | Pipeline core + first scorecard | schemas, LLM layer, OCR grounding, all 7 agents, decision engine, LangGraph graph, eval harness | first EVAL_REPORT on the dev split (all 4 rubric metrics) | ~$5–15 of Claude API |
| 3 | Backend product | FastAPI, uploads, storage, queue, database, auth/RBAC, review and override, audit chain, WebSocket, PDF report | API demo (curl/Swagger), test results | none |
| 4 | Next.js UI | all pages | screenshots, local click-through | **installs Node into `~/.local` and edits `~/.zshrc`** |
| 5 | Bonuses + red-team | ELA and corrected set, multilingual, LangSmith, calibration, red-team suite, final eval runs | final scorecard, red-team report | ~$15–30 API |
| 6 | Deploy | HF Space, Vercel, managed services, CI | live URL | **needs the user's accounts and keys** |
| 7 | Docs + demo prep | README, diagrams, ADRs, demo script, LinkedIn draft | full repo review | **GitHub public push only on explicit OK** |

**Always stop and ask, mid-checkpoint if necessary, before:**
- spending more than the stated budget;
- installing anything outside the project venv, or editing shell config;
- creating accounts or deploying;
- pushing to GitHub;
- deleting anything not created in this session.

## Step 0: bootstrap the project — DONE (2026-10-04)
1. Create `~/Desktop/medishield-capstone/` and run `git init` on branch `main`.
2. Copy this plan to `docs/PLAN.md`.
3. Copy the capstone inputs into `docs/brief/`:
   - `assignment_02_multimodal_ai.md`
   - `Capstone_Submission_Instruction.pdf`
4. Copy the official generator scripts, unmodified, into `datagen/official/`:
   - `generate_docs.py`, `generate_gold_policy.py`, `generate_silver_policy.py`, `generate_unknown.py`
   - `scripts_overview.txt`

   Source for steps 3–4: `~/Downloads/capstone_project_cohort3/`, including `Assignment2_datagen_scripts.zip`.
5. Leave `~/Downloads/Medibot_Assignment_Resources 3` and `~/Downloads/medibot` untouched. MediBot modules are
   *copied and adapted* into the new repo, never imported from it.

## Repo layout (`~/Desktop/medishield-capstone`)
```
backend/src/medishield/
  config.py
  schemas/                    # typed agent I/O contracts matching the brief's shapes
  llm/                        # client, routing, cache, cost
  ocr/                        # rapidocr, grounding
  forensics/                  # ela, typography, quality
  agents/                     # classifier, extractor, kyc, claims, policy, fraud, orchestrator
  rag/                        # docling_ingest, chunking, exclusion_table, store, retrieve
  fraud/                      # rules, baselines
  decision/                   # engine.py + decision_policy.yaml
  graph/                      # state, build, events
  db/                         # models, repo, audit_chain
  storage/
  queue/
  api/                        # main, routes/*, security, ws
  reports/                    # case_pdf
backend/tests/
frontend/                     # Next.js
datagen/
  official/                   # vendored scripts, unmodified, with attribution
  fontshim.py                 # maps Windows fonts to macOS/Linux; seeds global RNGs so pixels are deterministic
  instrumented_run.py         # writes ground_truth.json (fields per doc) + members/history
  augment.py                  # corrected tamper/name/structuring/blur, JPEG variants, ES/HI, prompt-injection docs
eval/
  labels.py                   # explicit expected_decision derivation
  run_eval.py
  metrics.py
  calibration.py
  retrieval_gold.json
  sets/{dev,heldout,test20}.json
  redteam/
docs/
  architecture.md             # Mermaid + PNG with real model names
  adr/
  dataset_findings.md
  EVAL_REPORT.md
  redteam.md
  demo_script.md
  linkedin_post.md
deploy/                       # Dockerfile, HF Space config, vercel.json, docker-compose.yml
.github/workflows/
Makefile                      # make setup / dataset / ingest / dev / eval / redteam / test
README.md
```

**Dataset in git:** the full image set (~hundreds of MB) is published as a GitHub Release asset. `make dataset`
reproduces it pixel-for-pixel, thanks to the seeded font shim. The repo commits only `metadata.json`, the ground truth
and the 20-case test images.

---

## Schedule (17 days, ~2 days buffer)
| Dates | Milestone |
|---|---|
| Oct 4–5 | Scaffold repo (uv, Python 3.12) and install Node. Font shim plus seeded generation of the official set, seed 7 and the corrected set. Instrumented ground truth, labeler, member and history export. **Spikes:** RapidOCR on arm64; Docling on both PDFs (table 4.1 parse). Draft `dataset_findings.md`. |
| Oct 6–9 | Schemas, LLM layer, OCR plus grounding, classifier, extractor, claims, KYC (plus forensics), policy RAG, fraud, decision engine, LangGraph graph. **Eval harness running from day 6**, iterating on the dev split. |
| Oct 10–12 | FastAPI: upload validation, storage, Huey queue, cases, review and override, JWT RBAC, audit chain, WebSocket, reports. Database and migrations (Alembic). |
| Oct 12–15 | Next.js UI: all pages above, with generated types. |
| Oct 15–17 | Bonuses: ELA and corrected set, multilingual, PDF export, LangSmith, calibration. Red-team suite. Final held-out and seed-7 eval runs. |
| Oct 17–19 | Deploy (HF Spaces, Vercel, Supabase, Qdrant Cloud, Upstash), demo mode, CI, keep-warm. |
| Oct 19–21 | README, architecture diagram, ADRs, EVAL_REPORT, demo script. User records the video. LinkedIn post draft. **Public GitHub push only after the user explicitly confirms.** |

**Approximate cost:**
- A full 155-doc eval run with Sonnet plus Opus routing costs about $6–10 before caching. Cached re-runs are free.
- Budget about 6–8 full runs.

---

## Labeling rules (`eval/labels.py`, documented in `dataset_findings.md`)
- **Labels are per document**, matching how the generator attaches flags.
- **A non-claim doc with no issues → APPROVE**, meaning "accepted as valid". This applies to discharge summaries,
  amendments and expiring-soon IDs. Expiring-soon IDs get an informational warning flag only.
- **Case roll-up:** any ESCALATE makes the case ESCALATE; otherwise any REJECT makes it REJECT; otherwise APPROVE.
- **Resolving ambiguous labels:**
  - `rx_PT_45400` (missing drug name + blur flag) → REJECT. Hard failure takes precedence.
  - `rx_PT_39451` (actually blurred) → ESCALATE.
  - `rx_PT_88139` (blur flag, not blurred) → ESCALATE, but marked *not visible in pixels*.
  - The 3 tampered IDs, `id_PT_39451` (name mismatch) and `claim_PT_69470` (structuring) → also marked *not visible
    in pixels*.
- **Decision accuracy is reported two ways:** on all docs, and on the visible-label subset.

## Top risks → mitigation (spike on day 1)
| Risk | Mitigation |
|---|---|
| RapidOCR or onnxruntime fails on arm64 / Python 3.12 | Fall back to `ocrmac` (Apple Vision) locally and Claude-vision OCR in the container; grounding then uses text matching only |
| Docling misses the untagged ruled-grid table 4.1 | Regex-parse the Docling text for range rows (`^[0-9A-Z]{5}-[0-9A-Z]{5}`), with pdfplumber's line-based table finder as a backup |
| HF Space RAM or cold start (Docling, fastembed, RapidOCR, reranker) | Precompute policy ingestion at image build time; lazy-load models; keep-warm cron; fall back to Render or Fly paid tier if needed |
| WebSocket blocked by the HF proxy | Fall back to Server-Sent Events (SSE) behind the same event bus |
| LangGraph fan-out + `interrupt()` complexity | Run the case graph with per-document subgraphs via `Send`; one interrupt at case level only |
| Graders label differently | Policy and labeler live in YAML and are switchable; show both readings in EVAL_REPORT |

## Cut list if behind schedule (drop in this order)
1. Multi-language: reduce to Spanish only, via Claude vision.
2. Seed-7 generalization run.
3. Corrected dataset: keep only tampered JPEGs for ELA.
4. Supabase and Upstash: use SQLite, local FS and SQLite-Huey inside the container.
5. React Flow pipeline graph: replace with a simple status timeline.
6. Four-eyes approval.

**Never cut:** the 4 rubric metrics in the eval harness, the deterministic decision engine, the policy exclusion
index, the review/override flow, the live deploy, and the README with the demo video.

## Verification
- **Unit tests:**
  - Decision table: every rule, plus precedence property tests.
  - Exclusion-range parser: alphanumeric ranges, overlaps.
  - Expiry checked against date of service.
  - Fraud rules, one fixture per scenario.
  - Audit hash-chain verification and tamper detection.
  - Upload validation: wrong magic bytes, oversize file, decompression bomb.
  - RBAC matrix for every route and role, and the four-eyes override.
- **Integration (replayed LLM cache):** each official cluster runs end to end through API → queue → graph → database.
  Assert the per-document decision against `eval/labels.py`.
- **Eval:**
  - Run `make eval DATASET=official|seed7|corrected`, which writes `docs/EVAL_REPORT.md`.
  - Targets: classification ≥ 97%, extraction ≥ 95%, retrieval Recall@3 ≥ 0.9, decision accuracy ≥ 90% on
    detectable labels.
  - Undetectable labels are reported transparently.
- **Red-team:** run `make redteam`. It covers injected "APPROVE" text, white-on-white instructions, fake "PRE-APPROVED"
  stamps, an injected policy clause, and oversized or malicious files. Target: 0 decision flips; results go in
  `docs/redteam.md`.
- **UI end to end:** a Playwright script logs in, uploads the C_001 bundle, watches the WebSocket pipeline, opens case
  detail and checks the field overlay, overrides as a reviewer, completes four-eyes approval as a senior, verifies the
  audit chain and downloads the PDF. It produces screenshots for the README. The ~150 MB browser download needs user
  approval.
- **Deploy smoke test:** a script hits `/healthz`, logs in, processes one showcase case on the live URL, and checks the
  WebSocket events.

## After approval: housekeeping
- Save a project memory: the MediShield capstone, its decisions and the repo location.
- Leave MediBot untouched.
