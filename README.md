# MediShield — Multi-Agent Claims Intake

**AI Engineering Bootcamp capstone, Assignment 02.** A production-style system that reads a bundle of insurance documents
(claim forms, IDs, discharge summaries, prescriptions, policy amendments), checks identity, coverage and fraud, and returns
**Approve / Reject / Escalate** with evidence and a justification. It includes a case-management UI for the operations
team and a **role-aware assistant** that answers questions with citations.

| | |
|---|---|
| **Live demo** | https://d3064azeabhrfe.cloudfront.net (AWS: Bedrock AgentCore + Lambda + DynamoDB). Logins on request; there are no public demo passwords. |
| **Demo video** | _link added after recording_ |
| **Evaluation report** | [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md): every number below is reproducible with `make eval` / `make report` |
| **Sample documents** | [22 labelled synthetic documents, 6 complete cases and both policies](docs/samples/medishield-samples.zip), reproducible with `make samples`. |
| **Repository** | Private for now. Demo video and final submission visibility remain pending. |
| **Slides** | [Dark presentation](docs/MediShield_capstone.pptx): eight main slides plus four appendix slides, with an 8-minute demo script in speaker notes. |
| **Try it** | [docs/manual_testing.md](docs/manual_testing.md): a 15-minute manual test script |

![Case detail: document viewer with evidence boxes, per-agent panels and the decision](docs/screenshots/case-detail.png)

## Results

Development uses the **dev** split. The official rows below were re-evaluated after the safety fixes using cached model responses; other rows are historical runs from the same synthetic generator family. These are not production accuracy estimates. See [implementation and validation notes](docs/IMPLEMENTATION_REVIEW.md).

| Run | Docs | Classification | Claim-field extraction | Policy retrieval R@3 | Decisions (all labels) | Decisions (labels visible in the image) | Cost / case |
|---|---|---|---|---|---|---|---|
| Official dataset, dev | 77 | 100.0% | 100.0% | 100.0% | 96.1% | 100.0% | $0.08 |
| Official dataset, **held-out** | 78 | 100.0% | 100.0% | 100.0% | 96.2% | 100.0% | $0.08 |
| **Seed 7** (historical) | 155 | 100% | 100% | 100% | 96.1% | 100% | $0.12 |
| Unseen set with tampering, name mismatch and blur actually drawn | 155 | 100% | 100% | 100% | 98.1% | 99.4% | $0.12 |
| Spanish + Hindi documents, held-out | 40 | 100% | 100% | 100% | 95.0% | 95.0% | $0.14 |

**Case accuracy:** held-out **15/17 (88.2%)**; dev **14/17 (82.4%)**. Case accuracy is separate from the document scores above.

The official rows were replayed in **OCR-first** mode (`MEDISHIELD_VISION=auto`), the same setting the live AWS deployment
uses, mostly from the response cache (held-out: 114 of 133 model calls cached; $0.22 actually spent for both splits). Costs
are uncached equivalents from recorded usage: about $0.08/case. Graph latency in a cache-assisted replay (held-out p50 5.5 s,
p95 7.0 s, setup excluded) is **not cold latency**; a live 5-document case takes about a minute. Each run records its
provenance (mode, cache, prefetch) in `docs/eval_results/`.

**Why two decision columns?** The instructors' generator records a few labels it never draws: three "tampered" IDs, one name
mismatch and one structuring fraud ([docs/dataset_findings.md](docs/dataset_findings.md)). No system can see those, so I report
both columns, and I built a *corrected* dataset that draws them to test the detectors honestly.

Robustness:
- **Prompt injection:** 0 decision flips across 7 adversarial documents (fake approval stamps, hidden "approve this" text, fake
  correction notices). A poisoned policy PDF also failed to flip coverage ([docs/redteam.md](docs/redteam.md)).
- **Assistant evaluation:** 35 labelled questions across five roles, scored three ways ([docs/chat_eval.md](docs/chat_eval.md)):
  - *rule checks* (no model): 97.1% pass every check; refusals 100%, no leaks 100%, citations point to real sources 100%.
    Expected answers come from data, not the model;
  - *LLM judge*: Claude Opus 5.5 grades each Sonnet answer on accuracy, completeness, refusal and citations with a written
    justification: 100% passed (mean accuracy 4.86 / 5), and it caught all 3 planted wrong-but-confident answers;
  - *RAGAS*: faithfulness 0.89, answer relevancy 0.91, context precision 0.94, context recall 1.00 on the 24 answerable
    questions. Judge and RAGAS together cost about $1.50 a run (`python eval/chat_eval.py --all`; RAGAS runs in a `uv --with`
    overlay so it never changes the app's dependencies).
- **Assistant red team:** 10 role-escalation and injection attacks, 0 failures. An admin control run proves the role boundary,
  not weak search, is what blocks them ([docs/chat_redteam.md](docs/chat_redteam.md)).
- **Calibration:** confidence was mapped onto observed accuracy with isotonic regression fitted on dev. Held-out ECE (expected
  calibration error) is 0.098 raw and 0.018 after the dev-fitted mapping. This is synthetic held-out evidence, not a guarantee on new scans.

## Architecture

```mermaid
flowchart LR
  subgraph Web["Browser"]
    UI["Next.js 16 UI<br/>dashboard · case detail · review queue · audit · insights · assistant"]
  end
  UI -- "/api/* (JWT, 5 roles)" --> API["FastAPI<br/>(Lambda via Mangum on AWS)"]
  UI -- "signed upload forms" --> S3[("S3<br/>documents")]
  API -- "InvokeAgentRuntime" --> PIPE
  API -- "InvokeAgentRuntime" --> ASSIST
  API <--> DB[("DynamoDB / SQLite<br/>cases · audit chain · ledger")]

  subgraph PIPE["AgentCore Runtime: case pipeline (LangGraph)"]
    direction TB
    R["RECEIVED"] --> P["PERCEIVE per document<br/>RapidOCR + quality · Classifier · Extractor"]
    P --> C["CLASSIFIED"] --> SP["SPECIALISTS in parallel<br/>KYC · Claims · Policy RAG"]
    SP --> F["FRAUD_CHECK"] --> D["DECIDED<br/>deterministic rules + justification"]
    D -- "ESCALATE" --> H["HUMAN_REVIEW<br/>(interrupt, four-eyes over $10k)"]
  end

  subgraph ASSIST["AgentCore Runtime: role-aware assistant"]
    direction TB
    RT["Router (topic)"] --> AC{"role allowed?<br/>(permission matrix)"}
    AC -- no --> X["refusal + audit event"]
    AC -- yes --> T["tools: policy search · case lookup ·<br/>per-role read-only SQL"] --> A["answer with [n] citations"]
  end

  SP --> Q[("Qdrant (in-memory)<br/>bge-small + BM25 → RRF → jina reranker")]
  PIPE --> LLM["Claude Sonnet 5.5 (perception, policy, fraud, summaries)<br/>Claude Opus 5.5 (retries, tamper second opinion)"]
  ASSIST --> LLM
  ASSIST <--> MEM[("AgentCore Memory<br/>conversation + per-user")]
  PIPE -. traces .-> LS["LangSmith (PHI-scrubbed)"]
```

| Brief component | Implementation | Model / tool |
|---|---|---|
| Ingestion API | FastAPI multipart upload or direct-to-S3 signed forms; PNG/JPEG/PDF/TIFF; magic-byte checks, size and page limits, PDF→pages, idempotency keys. Email too: `POST /intake/email` (.eml) and optional SES inbound mail from allow-listed senders ([docs/aws.md](docs/aws.md#email-intake-optional)) | — |
| Classifier agent | Vision LLM + deterministic title-keyword evidence; confidence comes from **agreement × image quality**, not the model's self-report. Low confidence or UNKNOWN goes to review | Sonnet 5.5, Opus 5.5 retry |
| OCR / pre-processor | RapidOCR (local, free) + quality metrics; extractor grounds **every field** against the OCR lines and returns `{fields, raw_text, bounding_boxes}` | RapidOCR, Sonnet 5.5 |
| KYC agent | Each claim verifies policy number, name, DOB and active membership (no separate ID required); IDs additionally check expiry **at the date of service**, typography forensics (retyped dates), advisory ELA, two-model visual tamper review, near-miss name rule | Sonnet + Opus agreement |
| Claims agent | ICD-10 / CPT / NPI / amount validation against the claim standard | deterministic |
| Policy agent (RAG) | Docling ingestion → hybrid search (dense + BM25, RRF, reranked) with section/page citations; **exclusions are decided by the parsed table**; approval also needs a mapped benefit and code-specific evidence; incomplete analysis goes to review | Sonnet 5.5 (Opus measured: same accuracy, higher cost) |
| Fraud agent | Duplicate claims (claim number, member/date/amount, perceptual image hash), frequency and billing-pattern baselines from claim history, plus model-found anomalies | rules + Sonnet 5.5 |
| Orchestrator | The brief's rules in `decision_policy.yaml` (deterministic, unit-tested); the model only writes the justification | Sonnet 5.5 |
| Case UI | Dashboard, case detail (document viewer with evidence boxes, collapsible agent panels, live pipeline graph), review queue with override and four-eyes approval, audit log, insights, assistant | Next.js 16, shadcn, TanStack Query, React Flow |

## Role-aware assistant

![Assistant: cited coverage answer, then a blocked request for the audit trail](docs/screenshots/assistant.png)

People ask questions in plain English and get answers with citations, limited to what their role may see. It follows the same
pattern as my earlier RBAC chatbot assignment: access is enforced **where the data is read**, not in the prompt.

| Role | Policy coverage | Own cases | Any case | Review queue | Audit trail | Ops metrics |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| submitter | ✅ | ✅ | 🔒 | 🔒 | 🔒 | 🔒 |
| reviewer | ✅ | ✅ | ✅ | ✅ | 🔒 | ✅ |
| senior reviewer, admin | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| auditor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

- **Hard boundaries:**
  - Policy search only returns policy chunks.
  - Case tools only return cases the user may see. Other ids are "not visible", without revealing whether they exist.
  - Analytics questions run NL→SQL on a **per-request, read-only SQLite database** that contains only the tables the role may
    query (a submitter's contains only their own rows), guarded by a SQLite authorizer.
- **Router:** only chooses the path and words the refusal, which is generated from the permission matrix. Blocked questions are
  written to the tamper-evident audit log.
- **Leak guard:** raises an error if any out-of-scope passage ever reaches the model.
- **Memory:** follow-ups ("and on Silver?") and per-user memory across sessions (AgentCore Memory); text is PHI-redacted before
  storage. "Clear my memory" deletes it.
- **Warm-up:** opening the page starts the agent and loads its search models, so the first answer isn't slow.
- **Ask about this case:** a side panel on the case page scopes the conversation to that case ("why?", "what would change
  the decision?", "which clause applies?"). No extra model call: the router is told the case id, and the case tool still
  decides visibility (someone else's case is "not visible").
- **MCP server:** the same tools and role permissions for Claude Code and Claude Desktop at `/api/mcp` ([docs/mcp.md](docs/mcp.md)).

## More product features

| Feature | What it does |
|---|---|
| **AI quality monitor** (Insights) | How often reviewers keep or override the AI, which rules they disagree with, AI → final decision transitions, reason codes, confidence of overturned vs kept cases, four-eyes outcomes, time to final. Built from recorded overrides and audit events, so it needs no model calls |
| **Ask about this case** | A side panel on the case page that scopes the assistant to that case ("why?", "what would change the decision?") with the same access checks |
| **Policy upload on AWS** | An admin uploads a new policy PDF; a pay-per-use Docling Lambda parses it (exclusion table, clauses, pages), and new agent sessions use it. No code change for a new plan |
| **Email intake** | `POST /intake/email` takes an .eml; with a domain configured, SES delivers mail from allow-listed senders straight into the pipeline (off by default, $0) |
| **MCP server** | Claude Desktop / Claude Code use MediShield as tools: coverage checks, cases, review queue, the assistant, all under the caller's role |

| | |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Sign-in](docs/screenshots/login.png) |
| ![Review queue](docs/screenshots/review-queue.png) | ![Insights: measured quality and calibration](docs/screenshots/insights.png) |

## Safety and guardrails

- **Access control:** JWT with 5 roles and a single permission matrix used by the API, the UI and the assistant.
- **Four-eyes approval:** overrides above $10,000 need a second senior reviewer, and nobody can approve their own request.
- **Tamper-evident audit log:** a hash-chained log covers every view, override, report download and blocked question;
  `GET /audit/verify` locates any edited or deleted row.
- **Prompt injection:** document text is data, never instructions. Decisions come from deterministic rules over grounded
  facts, so an injected "APPROVE" cannot decide a case. Red-teamed on every agent.
- **PHI:** redacted from logs, LangSmith traces and assistant memory. Images never leave for tracing.
- **Upload hardening:** content sniffing, size and page caps, rate limits, idempotency.
- **Cost guardrails:**
  - A hard model-spend cap and a daily cap, enforced across all workers via atomic counters.
  - An AWS budget alert.
  - Pay-per-use services only: about $1.25/month idle ([docs/aws.md](docs/aws.md)).

## Bonus challenges (all six)

| Challenge | Where |
|---|---|
| Confidence calibration | Reliability curve, ECE/Brier and isotonic calibrator: Insights page and [EVAL_REPORT](docs/EVAL_REPORT.md#confidence-calibration) |
| Streaming updates | WebSocket per case, with SSE and polling fallbacks; live pipeline graph in the UI |
| Tamper detection (ELA) | `forensics/ela.py` (heatmap toggle in the viewer) + typography check; measured in `docs/eval_results/forensics.json` |
| Multi-language | Spanish and Hindi documents (Devanagari OCR second pass, language-aware extraction); dedicated dataset and results |
| Audit export | "Download case report": a PDF with every agent output and the audit trail |
| LangSmith tracing | Every agent call with tokens, cost and latency per case; inputs scrubbed of PHI |

## Run it locally

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.12), Node 24, an Anthropic API key.

```bash
git clone https://github.com/raghav010126/Capstone.git medishield-capstone && cd medishield-capstone
cp .env.example .env                 # set ANTHROPIC_API_KEY; everything else has local defaults
uv sync                              # Python dependencies (includes Docling for policy ingestion)
make dataset                         # generate the official dataset + ground truth (seed 42)

make api                             # FastAPI + worker on http://localhost:8100 (Swagger at /docs)
scripts/web.sh install && make web   # UI on http://localhost:3000
```

Log in as `submitter`, `reviewer`, `senior`, `auditor` or `admin`. Local demo passwords are `<username>-demo`; they are seeded
only when `MEDISHIELD_DEMO_USERS=1` and are never used in production.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude access (required) |
| `MEDISHIELD_BUDGET_USD` / `MEDISHIELD_DAILY_BUDGET_USD` | hard spend caps; model calls stop when reached |
| `MEDISHIELD_VISION` | `always` (default) = page images to the model; `auto` = optional OCR-first mode (historical A/B ~25% cheaper). Record the chosen mode when comparing runs |
| `MEDISHIELD_LLM_OFFLINE=1` | replay cached responses only (free, deterministic demos and tests) |
| `JWT_SECRET`, `MEDISHIELD_ENV=production` | production refuses to start with the default secret |
| `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | optional tracing |
| `MEDISHIELD_DB=dynamodb`, `STORAGE_BACKEND=s3`, `MEDISHIELD_QUEUE=agentcore` | the AWS configuration (set by the deploy) |

Everything else is in [.env.example](.env.example).

**Tests and gates:**
- `make test-fast` runs 312 tests offline: agents, decision engine, API and roles, audit chain, forensics, assistant access
  boundaries, missing-output graph paths, claim identity and monetary validation.
- `make test-dynamo` runs the same suite against DynamoDB.
- `make gates` checks 28 quality gates over the published evaluation (including the LLM judge and RAGAS thresholds), for example decisions on visible labels ≥ 95% held-out,
  0 injection flips, calibrated ECE ≤ 0.05 and cost ≤ $0.25 per case.
- `make e2e` runs a 22-step browser flow.

GitHub Actions runs lint, both deterministic test suites, the saved-result gates and UI builds on every push. The graph safety tests run in CI; a fresh live-model benchmark does not.

Offline replay setup: `make dataset`, then `uv run python scripts/preflight_replay.py --download` once with network access.
Run `make replay-preflight` and `HF_HUB_OFFLINE=1 MEDISHIELD_LLM_OFFLINE=1 uv run pytest -q -m integration`.
The two replay tests require cached LLM responses from an earlier evaluation; model assets alone do not provide those responses.

`make eval` publishes a complete successful split and archives the previous result. Direct `eval/run_eval.py` writes a run directory; use `--publish` explicitly to update Insights, and `--no-prefetch` when measuring graph execution without prefetch.
Do not call a cached run cold. Calibration is fitted on official dev only.

## Walkthrough: one case end to end

Upload the five documents of cluster `C_012` (claim form, ID, discharge summary, prescription, policy amendment):

1. **Upload:** `POST /cases` (or, on AWS, direct-to-S3 forms then `POST /cases/from-uploads`) stores the files, creates
   `CASE-…` with status RECEIVED, writes `case_created` to the audit chain, and hands the case to the pipeline runtime.
2. **Perceive (per document, in parallel):** RapidOCR reads each page. The classifier labels the claim form CLAIM_FORM; the
   printed title words settle it on a clean page, so no model call is needed in OCR-first mode. The extractor reads ICD-10
   codes, CPT `17000` and `44970`, the NPI and the total, and grounds each field to a box on the page.
3. **Specialists (in parallel):**
   - **KYC:** the member is found, the ID is valid on the date of service, and the forensics are clean.
   - **Claims:** the schema is valid.
   - **Policy:** retrieval finds Gold plan §4.1, and the exclusion table places `17000` in 17000–17999 "cosmetic, S4(a)":
     **NOT_COVERED**. `44970` is covered at 80%.
4. **Fraud:** no duplicate and no anomaly above threshold. Risk is LOW.
5. **Decide:** rule R2 (procedure not covered) gives **REJECT** for the claim form. The other four documents are approved. Case
   confidence is 0.98, and the justification cites the clause and page.
6. **UI:** the case page shows the live pipeline graph, the claim image with evidence boxes, each agent's panel and the
   decision. A reviewer could override it with a reason code; above $10k a senior must approve.
7. **Ask:** the submitter asks the assistant "Why was my claim rejected?" and gets the exclusion with a link to the case. "Is
   that procedure covered on Silver instead?" resolves "that procedure" from memory and cites Silver table 4.1, p.6.

The live deployment processed exactly this case in 92 s (including a cold start) with the result above.

## Deployment (AWS, pay-per-use)

`scripts/aws_deploy.sh <account-id> <alert-email>` builds an ARM64 image in CodeBuild and deploys one CloudFormation stack:
- **Hosting:** CloudFront + S3 (static UI), Lambda (API), DynamoDB (on-demand), S3 (documents).
- **Agents:** two Bedrock AgentCore Runtimes (pipeline and assistant) and AgentCore Memory.
- **Operations:** SSM Parameter Store (secrets) and an AWS Budget alert.

Idle cost is about $1.25/month, mostly stored container images. `scripts/aws_destroy.sh` removes everything. Details and the trade-offs against the local build
are in [docs/aws.md](docs/aws.md).

## Design decisions and limitations

The key decisions and their trade-offs, plus an honest list of what does not work yet, are in
[docs/decisions.md](docs/decisions.md). The short version:
- **Models read, rules decide.** LLMs read documents and write explanations; a versioned, unit-tested rule file makes every
  decision.
- **Evidence-based confidence.** Confidence comes from grounding, agent agreement and image quality, not from what the model says.
- **Measure before shipping.** Every optimisation was A/B-tested, for example OCR-first routing (25% cheaper, same accuracy),
  Sonnet instead of Opus for policy and fraud (36% cheaper per case, identical decisions on dev and held-out) and a 7× smaller
  reranker (better MRR on the gold set).

## Repository layout

```
backend/src/medishield/
  agents/      classifier · extractor · kyc · claims · policy · fraud · orchestrator · lean (OCR-first routing)
  graph/       LangGraph case graph (+ human-review interrupt)
  decision/    decision_policy.yaml + deterministic engine
  rag/         Docling ingestion, exclusion-table parser, hybrid retrieval
  forensics/   ELA, typography
  chat/        role-aware assistant: access map, router, tools, per-role analytics SQL, memory
  api/         FastAPI app, routes, JWT/roles, upload hardening
  db/          repo interface, SQL + DynamoDB backends, hash-chained audit
  agentcore_app.py · aws_handlers.py      AgentCore Runtime and Lambda entry points
frontend/      Next.js 16 app (App Router), e2e browser flow
eval/          evaluation harness, metrics, calibration, red teams, report builder
datagen/       official generator (unchanged) + corrected, multilingual and adversarial datasets
infra/         CloudFormation, Dockerfile, CodeBuild spec
docs/          evaluation report, dataset findings, decisions, AWS guide, red-team results, API notes
```
