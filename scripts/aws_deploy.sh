#!/usr/bin/env bash
# Deploy MediShield to AWS (serverless, pay-per-use). Needs: `aws login --profile default` done, uv venv, project Node.
#   scripts/aws_deploy.sh <expected-12-digit-account-id> <alert-email>
# Refuses to run unless the signed-in account matches the one you pass, so nothing is ever created in the wrong account.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_REGION="${AWS_REGION:-us-east-1}" AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_EXPECTED="${1:?usage: aws_deploy.sh <account-id> <alert-email>}"
EMAIL="${2:?usage: aws_deploy.sh <account-id> <alert-email>}"
STACK="${STACK:-medishield}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
export UV_PROJECT_ENVIRONMENT="$HOME/.cache/medishield/venv"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
[ "$ACCOUNT" = "$ACCOUNT_EXPECTED" ] || { echo "signed in to $ACCOUNT, expected $ACCOUNT_EXPECTED - stopping"; exit 1; }
echo "account $ACCOUNT, region $AWS_REGION, profile $AWS_PROFILE"

# optional email intake: INBOUND_EMAIL_DOMAIN=claims.example.com enables it (docs/aws.md); set it empty to remove it again
deploy() { aws cloudformation deploy --stack-name "$STACK" --template-file infra/template.yaml --capabilities CAPABILITY_IAM \
             --no-fail-on-empty-changeset --parameter-overrides AlertEmail="$EMAIL" ImageTag="$1" DemoUsers=0 \
             ${INBOUND_EMAIL_DOMAIN+"InboundEmailDomain=$INBOUND_EMAIL_DOMAIN"} "${@:2}"; }
out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }

# Stage 1 only on a first deploy. Re-running it on a live stack would set ImageTag=none and delete the application.
if aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
  echo "== stack exists: skipping stage 1"
else
  echo "== stage 1: registry and image builder"
  deploy none
fi

echo "== secrets -> SSM Parameter Store (values are read from .env and never printed)"
set -a; . ./.env; set +a
put() { [ -n "${2:-}" ] && aws ssm put-parameter --name "/medishield/$1" --type SecureString --overwrite --value "$2" >/dev/null && echo "  stored $1"; }
put anthropic_api_key "${ANTHROPIC_API_KEY:-}"
put langsmith_api_key "${LANGSMITH_API_KEY:-}"
put langsmith_project "${LANGSMITH_PROJECT:-medishield-capstone}"
[ -z "${INTAKE_SENDERS:-}" ] || put intake_senders "$INTAKE_SENDERS"   # email intake allow-list {"address": "username"}
aws ssm get-parameter --name /medishield/jwt_secret >/dev/null 2>&1 || put jwt_secret "$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"

if ! aws ssm get-parameter --name /medishield/admin_password >/dev/null 2>&1; then     # admin-only site: password goes to a private file
  PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')"
  put admin_password "$PW"
  ( umask 077; printf 'username: admin\npassword: %s\n' "$PW" > .aws-admin-login )
  echo "  admin login written to .aws-admin-login (git-ignored)"
fi

echo "== build the Lambda image in CodeBuild"
TAG="$(date +%Y%m%d%H%M%S)"
uv run --python 3.12 python scripts/aws_bundle.py build/source.zip
aws s3 cp build/source.zip "s3://$(out SourceBucketName)/source.zip" --only-show-errors
BUILD_ID="$(aws codebuild start-build --project-name "$(out BuildProject)" --environment-variables-override name=IMAGE_TAG,value="$TAG" --query build.id --output text)"
while :; do
  S="$(aws codebuild batch-get-builds --ids "$BUILD_ID" --query 'builds[0].buildStatus' --output text)"
  [ "$S" = IN_PROGRESS ] || break; sleep 20
done
[ "$S" = SUCCEEDED ] || { echo "image build $S - see CodeBuild log for $BUILD_ID"; exit 1; }

echo "== stage 2: the application"
deploy "$TAG"
echo "== log retention for the agents (their log groups are created by AgentCore; keep 14 days, not forever)"
for g in $(aws logs describe-log-groups --log-group-name-prefix /aws/bedrock-agentcore/runtimes/ --query 'logGroups[].logGroupName' --output text); do
  aws logs put-retention-policy --log-group-name "$g" --retention-in-days 14
done
echo "== AgentCore runtimes: ready + MMDSv2"
uv run --python 3.12 python scripts/aws_agentcore_check.py "$(out PipelineRuntimeArn)" "$(out AssistantRuntimeArn)"

echo "== website"
STATIC_EXPORT=1 NEXT_PUBLIC_API_URL=/api scripts/web.sh run build
WEB="s3://$(out WebBucketName)"
# hashed build files never change: browsers keep them for a year; pages are revalidated so a deploy shows up at once
aws s3 sync frontend/out/_next/static "$WEB/_next/static" --cache-control "public,max-age=31536000,immutable" --only-show-errors
aws s3 sync frontend/out "$WEB" --exclude "_next/static/*" --cache-control "no-cache" --delete --only-show-errors
aws cloudfront create-invalidation --distribution-id "$(out DistributionId)" --paths '/*' >/dev/null

SITE="$(out SiteUrl)"
echo "== smoke test"
for i in 1 2 3 4 5 6; do curl -fsS "$SITE/api/healthz" && break || sleep 10; done
echo; echo "deployed: $SITE"
