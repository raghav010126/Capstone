# Deploying MediShield on AWS (serverless, pay-per-use)

```
 browser ── CloudFront ──┬── /            S3 (static Next.js export)
                         └── /api/*       Lambda Function URL ── API Lambda (FastAPI via Mangum)
                                                  │  send                │ read / write
                                                 SQS ──► Worker Lambda ──┤  DynamoDB (one table, on-demand)
                                                         (case graph)    │  S3 (uploaded documents)
                                                                         └─ Anthropic API (key in SSM Parameter Store)
                                                  │  invoke (async), once per uploaded policy
                                                  └──► Ingest Lambda (Docling, own image) ── S3 policies/ + DynamoDB
```

Everything is created by one CloudFormation template (`infra/template.yaml`) and removed by one script.

## Why it is cheap

| Piece | Billing | Idle cost |
|---|---|---|
| Lambda (API 1.5 GB, worker 3 GB, policy ingest 3 GB) | per request and GB-second | $0 |
| DynamoDB | on-demand: $0.625 / M writes, $0.125 / M reads | $0 (storage: first 25 GB free) |
| SQS | $0.40 / M requests (first 1 M free) | $0 |
| S3 | per GB-month and request | cents |
| CloudFront | `PriceClass_100`; first 1 TB / month free | $0 |
| ECR (the Lambda image, about 2 GB, two images kept) | $0.10 / GB-month | about $0.40 |
| ECR (the policy-ingest image: Docling, CPU PyTorch, models; estimated 1 to 1.5 GB compressed, two kept) | $0.10 / GB-month | about $0.25 |
| SSM Parameter Store (standard) | free | $0 |
| CloudWatch Logs | 7-day retention | cents |

Not used because they bill while idle: NAT gateway, WAF, provisioned concurrency, RDS, OpenSearch, point-in-time recovery.

**Idle total: about $1.25 a month.** Processing one case costs about $0.002 of Lambda time plus the model spend (about $0.11 to $0.16 per case, see `docs/EVAL_REPORT.md`).
Parsing an uploaded policy costs under half a cent (one to two minutes at 3 GB, no model calls), and policies are uploaded rarely.

## Guardrails against a surprise bill

* **Model spend (the real cost)** is capped by the application: `ModelBudgetUsd` (total for the live site, default $10; development on the laptop has its own cap) and `DailyModelBudgetUsd`
  (default $5) are kept as atomic counters in DynamoDB, so they hold across every Lambda invocation. When a cap is reached the API
  answers 503 and the worker stops calling the model.
* **AWS bill alert**: an AWS Budget emails at 50 % and 100 % of `MonthlyBudgetUsd` (default $10), actual and forecast.
* **Concurrency**: the worker runs at most two cases at once (event-source `MaximumConcurrency`), batch size 1.
* **Upload limits**: 10 MB per file (uploaded straight to S3 with signed forms), at most 10 uploads a minute per user and instance, JWT-protected API.
* **Teardown**: `scripts/aws_destroy.sh <account-id>` deletes the stack, the buckets' contents, the images and the secrets.

## What differs from the local build

* Progress is **polled** (every 1.5 s) instead of pushed: Lambda Function URLs do not carry WebSockets or server-sent events.
* Policy **upload** works, but the parsing runs elsewhere. Docling needs PyTorch, which does not fit AgentCore's 2 GB image, so the
  agents' image leaves it out (the two bundled policies are pre-parsed and baked in). Instead:
  * the API stores the PDF in S3 (`policies/`), records the policy as INGESTING and invokes the **ingest Lambda** asynchronously;
  * that Lambda has its own arm64 image (`infra/Dockerfile.ingest`: Docling on CPU-only PyTorch, models baked in, tagged
    `ingest-<tag>` in the same ECR repository). It parses the PDF, writes the index JSON to `policies/index/` and marks the policy
    READY (or FAILED with the error);
  * every new agent session (each case, each new conversation) downloads the READY policies' indexes from S3 before building its
    search index, so the next claim uses the new policy without Docling.

  Limits: a PDF can be at most about 4 MB on AWS, because a Lambda request is capped at 6 MB. A parse that times out (900 s) or runs
  out of memory is not retried and stays INGESTING; its log is in `/aws/lambda/medishield-ingest`. Deploy with `POLICY_INGEST=0` to
  skip the ingest image; the endpoint then answers 501, as before.
* A human override resumes the case without the persisted LangGraph checkpoint (Lambda has no durable disk); the decision, the audit
  chain and the override record are the same.

## Deploy

```bash
aws login --profile default                       # once; the profile must be the account you intend to use
aws sts get-caller-identity                       # note the 12-digit account id
scripts/aws_deploy.sh <account-id> <your-email>   # stage 1 -> secrets -> image build -> stage 2 -> website -> smoke test
```

The script stops if the signed-in account is not the id you passed. Secrets are read from the git-ignored `.env` and stored as
SecureString parameters under `/medishield/`; they are never printed and never appear in the template.
