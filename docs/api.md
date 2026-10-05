# API notes (checkpoint 3)

Run: `make api` (port 8100; Swagger UI at `/docs`), or `scripts/demo_api.sh C_002` for a curl walkthrough.
The worker runs inside the API process by default; `MEDISHIELD_WORKER=external` + `make worker` runs it separately.

## Roles
| Role | Can |
|---|---|
| submitter | upload cases, see **own** cases only |
| reviewer | see all cases, work the review queue, override (≤ $10k applies immediately), reclassify, download reports |
| senior_reviewer | everything a reviewer can, plus approve/reject high-value overrides |
| auditor | read-only: cases, review queue, audit log + verification, reports, ops KPIs |
| admin | everything, plus policy upload and user list |

Demo accounts (dev / demo deploys only): `submitter`, `reviewer`, `senior`, `auditor`, `admin`, password `<name>-demo`.

## Case lifecycle
`RECEIVED → PROCESSING → DECIDED` (automatic APPROVE/REJECT) or `→ IN_REVIEW → FINALIZED` (ESCALATE, resolved by a human).
An override on an `IN_REVIEW` case resumes the paused LangGraph run from its SQLite checkpoint; overriding an already
decided case records the new final decision. Above `FOUR_EYES_AMOUNT` an override is only *requested*; a different
senior reviewer/admin must approve it (nobody approves their own).

## Guarantees worth knowing
- Uploads: type by magic bytes (PNG/JPEG/PDF/TIFF), size cap, file-count cap, PDF/TIFF page cap, pixel cap
  (decompression-bomb guard), filenames never used as paths, byte-identical files in one upload ignored,
  `Idempotency-Key` makes retries safe, per-user rate limit, daily LLM budget cap.
- Every state change (login, upload, view of a document, decision, override, policy upload) is appended to a
  hash-chained audit log; `GET /audit/verify` recomputes the chain and names the first broken event.
- Logs pass through a PHI redactor (SSNs, DOBs, policy numbers, NPIs, names, bearer tokens).
- Live status: `WS /ws/cases/{id}?token=` or SSE `GET /cases/{id}/stream?token=`; both stream from the `case_events` table.
