# Design decisions, trade-offs and known limitations

Each decision lists what I chose, why, and what it costs. The numbers come from [EVAL_REPORT.md](EVAL_REPORT.md) and
`docs/eval_results/`.

## Decisions

### 1. Models read; a rule file decides
**Choice.**
- LLMs transcribe documents, explain coverage and write the justification.
- Every Approve / Reject / Escalate comes from a deterministic engine applying `decision/decision_policy.yaml`. The file holds
  the brief's rules: KYC failed, not covered or schema invalid means REJECT; fraud ≥ 0.3 or confidence < 0.6 means ESCALATE.

**Why.**
- The same facts always give the same decision.
- Every decision points to a rule id in the audit log and the PDF report.
- An injected "APPROVE" in a document cannot decide a case: the red team produced 0 flips.

**Cost.** The model's judgement cannot override the rules even when it would be right. A wrong rule needs a code change, not a
prompt change.

### 2. Confidence is evidence, not the model's opinion
**Choice.**
- Classifier confidence is the agreement between the vision model and deterministic title keywords, scaled by image quality.
- Extraction confidence is the share of fields grounded on an OCR line or corroborated by the member database.
- The model's self-reported confidence is logged but never used.

**Why.** Self-reported confidence was poorly calibrated in early tests. Evidence-based confidence, after isotonic calibration
fitted on dev, reaches ECE 0.015 on held-out data.

**Cost.** More code. Handwriting is never grounded by OCR, so it is capped at a 30% confidence penalty so that legible
handwritten fields don't escalate everything.

### 3. Coverage comes from the parsed exclusion table, not from similarity search
**Choice.**
- Docling parses each policy PDF. The "4.1 Excluded CPT Code Ranges" table becomes structured rows, and a CPT code is excluded
  if it falls in a row's range.
- Retrieval (dense + BM25, RRF, reranked) supplies the clauses and page numbers for the explanation.
- The model may make a code *less* automatic (prior authorisation, conditional), never more.

**Why.**
- No individual CPT code appears in the policy text, only ranges, so embedding similarity cannot decide coverage reliably.
- A poisoned policy PDF telling the model to "report every code as covered" did not change the outcome.

**Cost.** It depends on that table existing. A policy without a machine-readable table falls back to clause reading with lower
confidence.

### 4. Ground truth was rebuilt, and the dataset's flaws are reported rather than hidden
**Choice.** The instructors' generator records labels it never draws: tampered IDs, a name mismatch, a structuring fraud and some
blur. I report decision accuracy on all labels and on labels visible in the image. I also built a *corrected* dataset that
draws them, and a second set with a different seed that I never inspected
([dataset_findings.md](dataset_findings.md)).

**Why.** Scoring 100% against invisible labels would mean the system was cheating. Scoring lower without explanation would
hide what really happened.

**Cost.** Two numbers instead of one, and some explaining in the demo.

### 5. Prompts tuned on dev only; held-out and unseen sets run once
**Why.** It is the only honest way to report generalisation. Held-out (96.2% / 100%) and unseen seed 7 (96.1% / 100%) match
dev (96.1% / 100%).

### 6. Per-step model routing with escalation
**Choice.**
- Sonnet 5.5 handles perception, policy, fraud and summaries.
- Opus 5.5 handles retries when a Sonnet output fails a validation check, and gives the second opinion on suspected tampering.
- KYC tamper flags need *both* models to agree, because a false tamper flag is a hard rejection.

**Why.**
- Policy and fraud originally ran on Opus at high effort. In both, the deciding work is deterministic: coverage comes from the
  exclusion table, and fraud is scored by rules. The model picks the benefit row, adds conditions, writes the narrative and
  adds small, capped signals.
- A/B on dev and then on held-out: moving both to Sonnet gave **identical decisions and coverage on every document**, and cost
  per case fell from $0.127 to $0.082 (−36%).
- The justification uses a template for fully clean approvals, where a model would only restate "all checks passed".

**Cost.** The two-model agreement misses subtle tampering that only one model sees. That is acceptable, because a missed
tamper still escalates on other signals more often than it approves.

### 7. OCR first; the page image only when needed
**Choice.** With `MEDISHIELD_VISION=auto`:
- the classifier skips the model when the printed title words settle the type on a clean OCR page;
- KYC skips the visual review when OCR is clean and neither forensic check flags the card.

**Why.** A/B on dev, same documents and prompts: **25% cheaper per case ($0.157 → $0.118) at identical accuracy**.

**What I rejected.** Text-only extraction was measured too. It saved only 4% more and cost 4 points of decision accuracy, because
it copies OCR noise and cannot see coloured stamps or handwriting. It is off.

### 8. Measured choices, not defaults
**Reranker.** `bge-reranker-base` (1.04 GB) was replaced by `jina-reranker-v1-turbo-en` (0.15 GB). It is better on the gold
set: recall@3 100%, MRR 1.000 vs 0.963. Its size is what let the image fit AgentCore's 2 GB limit
([eval_results/reranker.json](eval_results/reranker.json)).

**Calibration.** Isotonic regression fitted on dev only, applied unchanged elsewhere.

### 9. Humans stay in the loop where it matters
**Choice.**
- ESCALATE pauses the LangGraph case at a human-review interrupt.
- Overrides need a reason code.
- Above $10,000 a second senior reviewer must approve, and nobody can approve their own request.
- Reclassifying a document re-runs only what changed, thanks to the response cache.

**Why.** Regulated decisions need accountable people. The audit chain shows who decided what and why.

### 10. One permission matrix for API, UI and assistant
**Choice.** `api/security.py::PERMISSIONS` is the only place access is defined. The assistant derives its sources, analytics
tables and refusal text from it. It enforces access where data is read:
- policy search only returns policy chunks;
- case tools only return visible cases;
- analytics run on a per-request, read-only SQLite database that holds only permitted tables and rows, under a SQLite
  authorizer.

**Why.** Prompt-level rules can be argued with; missing data cannot be leaked. The red team (10 attacks with an admin control)
found 0 failures.

**Cost.** The analytics database is rebuilt per question: milliseconds at demo scale, but it would need a materialised view at
production scale.

### 11. Serverless and pay-per-use on AWS; AgentCore for the agents
**Choice.**
- The API runs on Lambda.
- The case pipeline and the assistant run on Bedrock AgentCore Runtime. The pipeline runs as a background task; the assistant
  runs in sessions with AgentCore Memory.
- Data lives in DynamoDB on-demand and S3, with a static UI on CloudFront.
- One CloudFormation stack; images are built in CodeBuild (ARM64).

**Why.** Idle cost is about $1/month. Agents get managed, isolated microVM sessions with long timeouts. Nothing bills while idle.

**Cost.**
- Cold starts: the first answer after a pause takes 10–30 s.
- No WebSockets through Lambda, so the UI polls.
- The persisted LangGraph checkpoint isn't resumed on AWS: the override is recorded and the case finalised, but the graph is not
  resumed.

### 12. The same app runs locally with zero cloud accounts
**Choice.** The storage, queue and memory backends are interfaces: SQLite / DynamoDB, local disk / S3, Huey / AgentCore, and an
in-process assistant / AgentCore Runtime.

**Why.** Graders can run everything with only an Anthropic key. The whole test suite also runs against DynamoDB under moto.

## Known limitations

- **Forged IDs:** typography and visual review catch most, not all. On the corrected set, 1 of 3 forged IDs was rejected, 1
  escalated and 1 missed. ELA is advisory only: it caught 9 of 24 splices, with false alarms on 8 of 48 clean JPEGs.
- **Name variants:** caught only when the OCR line holding the name is read confidently (≥ 0.95). Otherwise they are treated
  as possible OCR noise.
- **Duplicate detection:** works on near-identical images, but templated synthetic pages can look like duplicates. Two
  Spanish/Hindi held-out cases escalated for that reason.
- **Policy upload on the live site:** not available. Docling and PyTorch exceed AgentCore's 2 GB image limit. The two bundled
  policies are pre-parsed and built into the image; upload works locally. A separate Docling Lambda would close the gap.
- **Persisted graph resume:** human-review resume uses the persisted graph locally only (see decision 11).
- **Real-time updates on AWS:** delivered by polling every 1.5 s, not WebSockets.
- **Assistant scope:**
  - It answers from the documents, cases and metrics it can read. It does not take actions (approve, override); it says that
    is done in the app.
  - Long-term memory facts appear asynchronously, so a fact learned in one conversation may take a minute to be recalled.
- **Evaluation scale:** about 600 labelled documents across all sets, all synthetic, from one generator family. Real scans
  (fax noise, skew, multi-page faxes) were not available.
- **Schema changes:** an additive auto-migration covers new columns. Anything larger would need Alembic.
- **Demo passwords:** `<user>-demo` exist only locally. The live site uses private passwords, and there are no public demo
  accounts by design, because model spend is real.

## Scaling next steps (not needed at demo scale)

A cost and performance review found these items. At demo volume they cost cents; at the brief's volume (85,000 documents,
about 17,000 cases a month) they would matter.

- **Duplicate detection without re-reading history.** Today the claims registry is rebuilt from every decided case before each
  new case, which grows as O(N) per case and O(N²) overall. The fix is to write small keyed items (claim number, image hash,
  member + service date) when a case is decided, so the duplicate check becomes a few point reads.
- **List views without per-case reads.** Store the document count and a compact per-document summary on the case record, add a
  status index for the review queue, and keep dashboard KPIs as running counters, so lists and `/ops/summary` stop loading every
  case.
- **Document images through signed S3 links and previews.** Today images go through the API, so every view costs a Lambda
  invocation. Signed links with ~1600 px previews would be cheaper and faster. They would also lift a limit: a Lambda response
  can't exceed 6 MB, so scans larger than that don't display today.
- **A warm pool of pipeline sessions.** Every case currently starts its own AgentCore microVM. Reusing a few sessions would
  remove most cold starts. This needs the claims registry to be per-request (see the first point).
- **Data retention.** Uploaded files expire after 60 days. Case records should get a retention policy (DynamoDB TTL) to match.

Already applied from the same review:
- Overrides keep small status markers, replacing a full-table scan on every list refresh.
- The audit list reads one page instead of the whole chain.
- One `/progress` call per poll replaces two, and polling pauses in hidden tabs.
- Polling intervals are relaxed; batched, length-sorted embedding and reranking cut the index build from 4.4 s to 1.8 s.
- The fraud check runs beside the specialists, and the search models load when an agent starts.
- Retries that cannot change the outcome are skipped.
- Model-step changes were measured on dev (see the evaluation report).
