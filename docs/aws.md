# Deploying MediShield on AWS (serverless, pay-per-use)

```
 browser ── CloudFront ──┬── /            S3 (static Next.js export)
                         └── /api/*       Lambda Function URL ── API Lambda (FastAPI via Mangum)
                                                  │  send                │ read / write
                                                 SQS ──► Worker Lambda ──┤  DynamoDB (one table, on-demand)
                                                         (case graph)    │  S3 (uploaded documents)
                                                                         └─ Anthropic API (key in SSM Parameter Store)
```

Everything is created by one CloudFormation template (`infra/template.yaml`) and removed by one script.

## Why it is cheap

| Piece | Billing | Idle cost |
|---|---|---|
| Lambda (API 1.5 GB, worker 3 GB) | per request and GB-second | $0 |
| DynamoDB | on-demand: $0.625 / M writes, $0.125 / M reads | $0 (storage: first 25 GB free) |
| SQS | $0.40 / M requests (first 1 M free) | $0 |
| S3 | per GB-month and request | cents |
| CloudFront | `PriceClass_100`; first 1 TB / month free | $0 |
| ECR (the Lambda image, about 2 GB, two images kept) | $0.10 / GB-month | about $0.40 |
| SSM Parameter Store (standard) | free | $0 |
| CloudWatch Logs | 7-day retention | cents |

Not used because they bill while idle: NAT gateway, WAF, provisioned concurrency, RDS, OpenSearch, point-in-time recovery.

**Idle total: about $1 a month.** Processing one case costs about $0.002 of Lambda time plus the model spend (about $0.11 to $0.16 per case, see `docs/EVAL_REPORT.md`).

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
* Policy **upload** needs the Docling parser (about 3 GB with PyTorch), which is left out of the image; the two bundled policies are
  pre-parsed and baked in. The endpoint answers 501 in this deployment.
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
