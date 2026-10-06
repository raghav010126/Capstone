#!/usr/bin/env bash
# Remove everything scripts/aws_deploy.sh created (stack, buckets' contents, images, secrets). Usage: scripts/aws_destroy.sh <account-id>
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-default}" AWS_REGION="${AWS_REGION:-us-east-1}" AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
STACK="${STACK:-medishield}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
[ "$ACCOUNT" = "${1:?usage: aws_destroy.sh <account-id>}" ] || { echo "signed in to $ACCOUNT - stopping"; exit 1; }
out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text 2>/dev/null || true; }
for k in WebBucketName DocsBucketName SourceBucketName; do b="$(out $k)"; [ -n "$b" ] && [ "$b" != None ] && aws s3 rm "s3://$b" --recursive --only-show-errors || true; done
# SES refuses to delete the active receipt rule set: deactivate ours first (only exists when email intake was enabled)
RS="$(out InboundRuleSetName)"
if [ -n "$RS" ] && [ "$RS" != None ] && [ "$(aws ses describe-active-receipt-rule-set --query Metadata.Name --output text 2>/dev/null)" = "$RS" ]; then
  aws ses set-active-receipt-rule-set
fi
aws cloudformation delete-stack --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --stack-name "$STACK"
for p in anthropic_api_key langsmith_api_key langsmith_project jwt_secret intake_senders; do aws ssm delete-parameter --name "/medishield/$p" 2>/dev/null || true; done
echo "removed stack $STACK"
