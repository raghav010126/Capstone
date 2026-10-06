"""The Lambda entry points, run against moto (DynamoDB + SQS + S3). No AWS account is involved."""

from __future__ import annotations

import json

import boto3
import pytest
from conftest import png_bytes
from moto import mock_aws


@pytest.fixture
def aws(env, monkeypatch, fake_pipeline):
    for k, v in (("AWS_ACCESS_KEY_ID", "t"), ("AWS_SECRET_ACCESS_KEY", "t"), ("AWS_DEFAULT_REGION", "us-east-1"),
                 ("MEDISHIELD_DB", "dynamodb"), ("DYNAMO_TABLE", "t"), ("MEDISHIELD_QUEUE", "sqs"), ("API_BASE_PATH", "/api"),
                 ("STORAGE_BACKEND", "s3"), ("S3_BUCKET", "docs"), ("MEDISHIELD_QUEUE_IMMEDIATE", "0")):
        monkeypatch.setenv(k, v)
    with mock_aws():
        from conftest import reset_runtime
        from medishield import aws_handlers
        from medishield.db.dynamo import get_dynamo_repo

        reset_runtime()
        aws_handlers._ready, aws_handlers._api = False, None
        get_dynamo_repo().ensure_table()
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="docs")
        url = boto3.client("sqs", region_name="us-east-1").create_queue(QueueName="q")["QueueUrl"]
        monkeypatch.setenv("SQS_QUEUE_URL", url)
        reset_runtime()
        yield url


def function_url_event(method, path, body=None, headers=None, is_b64=False):
    return {"version": "2.0", "rawPath": path, "rawQueryString": "", "headers": {"host": "x.lambda-url.aws", **(headers or {})},
            "requestContext": {"http": {"method": method, "path": path, "sourceIp": "1.2.3.4", "protocol": "HTTP/1.1"},
                               "stage": "$default"},
            "body": body, "isBase64Encoded": is_b64}


def call(event):
    from medishield import aws_handlers

    out = aws_handlers.api_handler(event, None)
    return out["statusCode"], json.loads(out["body"]) if out["body"] else None


def test_api_serves_under_the_api_prefix_and_logs_in(aws):
    assert call(function_url_event("GET", "/api/healthz"))[0] == 200
    code, body = call(function_url_event("POST", "/api/auth/login", json.dumps({"username": "submitter", "password": "submitter-demo"}),
                                         {"content-type": "application/json"}))
    assert code == 200 and body["access_token"]


def test_upload_goes_to_sqs_and_the_worker_decides_the_case(aws):
    from medishield import aws_handlers

    code, tok = call(function_url_event("POST", "/api/auth/login", json.dumps({"username": "submitter", "password": "submitter-demo"}),
                                        {"content-type": "application/json"}))
    assert code == 200
    import base64
    boundary = "xBOUNDARYx"
    data = png_bytes()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"a.png\"\r\nContent-Type: image/png\r\n\r\n"
            ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    code, created = call(function_url_event("POST", "/api/cases", base64.b64encode(body).decode(),
                                            {"content-type": f"multipart/form-data; boundary={boundary}",
                                             "authorization": f"Bearer {tok['access_token']}"}, is_b64=True))
    assert code == 202, created
    msgs = boto3.client("sqs", region_name="us-east-1").receive_message(QueueUrl=aws, MaxNumberOfMessages=1)["Messages"]
    assert json.loads(msgs[0]["Body"]) == {"task": "process_case", "arg": created["case_id"]}

    aws_handlers.worker_handler({"Records": [{"body": msgs[0]["Body"]}]}, None)
    code, detail = call(function_url_event("GET", f"/api/cases/{created['case_id']}",
                                           headers={"authorization": f"Bearer {tok['access_token']}"}))
    assert code == 200 and detail["status"] in ("IN_REVIEW", "DECIDED") and detail["agent_runs"]


def test_spend_ledger_lives_in_dynamodb(aws):
    from medishield.llm import ledger
    from medishield.llm.cost import Usage

    ledger().record("x", "claude-sonnet-5-5", Usage(10, 5), 0.25)
    ledger().record("x", "claude-sonnet-5-5", Usage(10, 5), 0.5)
    assert abs(ledger().total - 0.75) < 1e-9 and abs(ledger().spent_today() - 0.75) < 1e-9


def test_large_cases_upload_straight_to_s3(aws, monkeypatch):
    """Lambda caps a request at 6 MB, so on AWS the browser uploads to S3 with a signed form and the API reads it from there."""
    sent = []
    from medishield.worker import queue
    monkeypatch.setattr(queue, "_send_sqs", lambda task, arg: sent.append(arg))

    def login(user):
        _code, tok = call(function_url_event("POST", "/api/auth/login", json.dumps({"username": user, "password": f"{user}-demo"}),
                                            {"content-type": "application/json"}))
        return {"authorization": f"Bearer {tok['access_token']}", "content-type": "application/json"}

    sub = login("submitter")
    code, mode = call(function_url_event("GET", "/api/cases/upload-mode", headers=sub))
    assert code == 200 and mode["mode"] == "presigned"
    code, grant = call(function_url_event("POST", "/api/cases/uploads",
                                          json.dumps({"files": [{"filename": "a.png", "size": 1000}, {"filename": "b.png", "size": 1000}]}), sub))
    assert code == 200 and len(grant["uploads"]) == 2 and grant["uploads"][0]["fields"]["key"].startswith("uploads/submitter/")
    s3 = boto3.client("s3", region_name="us-east-1")
    for i, t in enumerate(grant["uploads"]):                        # what the browser does with each signed form
        s3.put_object(Bucket="docs", Key=t["key"], Body=png_bytes(text_seed=i + 3))
    # another user cannot turn someone else's upload into a case
    code, _ = call(function_url_event("POST", "/api/cases/from-uploads", json.dumps({"upload_id": grant["upload_id"]}), login("reviewer")))
    assert code == 404
    code, created = call(function_url_event("POST", "/api/cases/from-uploads", json.dumps({"upload_id": grant["upload_id"]}), sub))
    assert code == 202 and len(created["documents"]) == 2 and sent == [created["case_id"]]
    assert not s3.list_objects_v2(Bucket="docs", Prefix="uploads/").get("Contents")      # temporary uploads are removed
    code, _ = call(function_url_event("POST", "/api/cases/uploads", json.dumps({"files": [{"filename": "x.png", "size": 50_000_000}]}), sub))
    assert code == 413


def test_lambda_api_answers_the_keep_warm_ping_without_touching_the_app(aws):
    import importlib

    from medishield import lambda_api
    importlib.reload(lambda_api)                                     # runs the init phase under the moto environment
    assert lambda_api.handler({"warm": True}, None) == {"warm": True}
    out = lambda_api.handler(function_url_event("GET", "/api/healthz"), None)
    assert out["statusCode"] == 200
