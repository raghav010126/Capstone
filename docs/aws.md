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
| SES inbound + email Lambda (optional, [email intake](#email-intake-optional)) | per message received | $0 |

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

## Email intake (optional)

The brief says documents arrive "via email, mobile uploads, and physical scanning stations". A phone mail app or a scanning
station can send to `intake@<your domain>`, and the attachments become a case:

```
 sender ── SES (receipt rule: TLS required, spam/virus scan) ──┬── S3 action: documents bucket, inbound/<id> (expires after 3 days)
                                                               └── Lambda action: medishield-email (the app image, handler
                                                                   medishield.intake.ses.handler) ── case + pipeline, as for an upload
```

**Who may send.** An explicit allow-list, `INTAKE_SENDERS` = `{"address": "username"}` (SSM `/medishield/intake_senders`, or
`.env` locally). It was chosen over an email field on users: no schema change in either database, one place to revoke a sender,
and an empty or malformed list rejects everything. The mapped user must be active and allowed to create cases; the case is theirs.

**Spoofing.** A From header is easy to forge, so the allow-list alone is not enough. SES reports SPF, DKIM, DMARC, spam and
virus verdicts, and the handler requires **PASS for every verdict SES reports** (GRAY and PROCESSING_FAILED count as failures;
DISABLED is skipped). DMARC is the check that ties the authenticated domain to the visible From address, so allow-listed senders
need SPF, DKIM and DMARC on their domain (Gmail and Microsoft 365 have them). Mail that fails, or comes from an unknown sender,
is never downloaded or parsed: it is deleted and recorded as `email_rejected` in the audit log with the sender's domain and the
reason only. Accepted mail goes through the upload checks unchanged (content sniffing, size, page and pixel caps), is idempotent
on its Message-ID, and is audited as `case_created_by_email`. Nobody is sent a reply (no SES sending, no backscatter).

**Enable** (SES receives mail only in some regions; us-east-1 is one):
1. Verify the domain in SES (console → Identities → Create identity → Domain, Easy DKIM) and add the three DKIM CNAME records.
   A subdomain such as `claims.example.com` keeps the main domain's mail untouched.
2. Add an MX record: `claims.example.com  MX  10 inbound-smtp.us-east-1.amazonaws.com`.
3. Put the allow-list in `.env`: `INTAKE_SENDERS='{"scanner@clinic.example": "submitter"}'`.
4. `INBOUND_EMAIL_DOMAIN=claims.example.com scripts/aws_deploy.sh <account-id> <email>`: adds the rule set and rule, the email
   function and its 7-day log group, the bucket policy that lets SES write `inbound/`, and the 3-day expiry.
5. Activate the rule set once (CloudFormation cannot; a region has one active set, so if yours already has one, add the rule
   there instead): `aws ses set-active-receipt-rule-set --rule-set-name medishield-inbound`.

Allow-list changes reach a function at its next cold start; to apply a revocation at once, change any setting of
`medishield-email` and `medishield-api` (for example their description). To turn intake off, deactivate the rule set
(`aws ses set-active-receipt-rule-set`) and deploy with `INBOUND_EMAIL_DOMAIN=`; `scripts/aws_destroy.sh` deactivates it for you.

**Cost.** SES charges per message received, about $0.10 per 1,000 messages plus $0.09 per 1,000 incoming 256 KB chunks (check
the SES pricing page for your region). A 2 MB email costs under $0.001 in SES, Lambda and S3 together, and nothing is billed
while idle. The model spend for an accepted case is the same as for an upload and falls under the same caps.

**Demo without a domain.** `POST /intake/email` takes a saved `.eml` file (most mail clients can "Save as" or "Download message"),
as a multipart field `file` or as the raw body. The caller needs `case:create` and owns the case; the From address must be on the
allow-list, and a submitter may only send mail from an address mapped to them (staff accounts can act as a mail gateway). This
endpoint trusts the caller's token, not the SPF or DKIM headers inside the file, which it cannot verify. The New case page has a
"Submit an email" button that does the same.

```bash
# .env: INTAKE_SENDERS='{"you@example.com": "submitter"}'  (restart the API)
TOKEN=$(curl -s localhost:8100/auth/login -H 'content-type: application/json' \
          -d '{"username":"submitter","password":"submitter-demo"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8100/intake/email -H "authorization: Bearer $TOKEN" -H 'content-type: message/rfc822' --data-binary @claim.eml
```
