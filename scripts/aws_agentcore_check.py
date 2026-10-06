"""After a deploy: make sure each AgentCore runtime is READY and requires MMDSv2.

Since 2026-06-30 AgentCore rejects invocations unless a runtime has metadataConfiguration.requireMMDSV2=true, and that setting
exists only on UpdateAgentRuntime (not in CloudFormation). UpdateAgentRuntime replaces the whole configuration, so the current
one is read back and re-sent unchanged apart from that flag.

Usage: python scripts/aws_agentcore_check.py <runtime-arn> [...]
"""

from __future__ import annotations

import sys
import time

import boto3

KEEP = ("agentRuntimeArtifact", "roleArn", "networkConfiguration", "description", "protocolConfiguration",
        "environmentVariables", "lifecycleConfiguration", "authorizerConfiguration", "requestHeaderConfiguration")


def wait_ready(client, rid: str) -> dict:
    for _ in range(90):
        rt = client.get_agent_runtime(agentRuntimeId=rid)
        if rt["status"] in ("READY", "CREATE_FAILED", "UPDATE_FAILED"):
            return rt
        time.sleep(10)
    raise TimeoutError(f"{rid} not ready")


def main(arns: list[str]) -> int:
    client = boto3.client("bedrock-agentcore-control")
    for arn in arns:
        rid = arn.rsplit("/", 1)[-1]
        rt = wait_ready(client, rid)
        if rt["status"] != "READY":
            print(f"{rid}: {rt['status']} {rt.get('failureReason', '')}")
            return 1
        meta = rt.get("metadataConfiguration") or {}
        if meta.get("requireMMDSV2"):
            print(f"{rid}: READY, MMDSv2 required")
            continue
        kw = {k: rt[k] for k in KEEP if rt.get(k)}
        client.update_agent_runtime(agentRuntimeId=rid, metadataConfiguration={"requireMMDSV2": True}, **kw)
        rt = wait_ready(client, rid)
        print(f"{rid}: {rt['status']}, MMDSv2 now {(rt.get('metadataConfiguration') or {}).get('requireMMDSV2')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
