"""AWS Lambda handler for SES inbound mail: ``medishield.intake.ses.handler`` (the app image with a command override).

The receipt rule for intake@<domain> runs two actions in order: an S3 action stores the raw message in the documents bucket
under ``inbound/<SES message id>``, then a Lambda action invokes this function asynchronously with the SES event. The event
carries SES's spam, virus, SPF, DKIM and DMARC verdicts and the parsed common headers, not the message itself.

Checks run cheapest and safest first, so mail that is spoofed or from an unknown sender is never downloaded or parsed:
1. every available SES verdict must be PASS (``service.verdict_failures``)
2. the From address SES evaluated must be allow-listed and map to an active user who may create cases
3. the raw message is read from S3 and parsed; its From must be that same address
4. the case is created for the mapped user (idempotent on the Message-ID, so a re-delivery returns the same case) and queued
The raw message is deleted afterwards either way; a lifecycle rule also expires ``inbound/`` after 3 days. An unexpected
error (S3 or DynamoDB unavailable) propagates, so Lambda's asynchronous retries try again with the message still in place.
"""

from __future__ import annotations

import logging
import re

from medishield.api.uploads import UploadError
from medishield.services.cases import should_enqueue

log = logging.getLogger(__name__)
INBOUND_PREFIX = "inbound/"


def handler(event, context):
    from medishield.aws_handlers import _init

    _init()
    results = []
    for rec in (event or {}).get("Records", []):
        if rec.get("eventSource") != "aws:ses" or "ses" not in rec:
            log.warning("ignoring a record that is not from SES")
            continue
        results.append(process(rec["ses"]))
    return {"results": results}


def process(ses: dict) -> dict:
    from medishield.db.repo import repo_scope
    from medishield.intake import service
    from medishield.intake.email import parse, sender_of
    from medishield.storage.base import get_storage
    from medishield.worker import queue

    mail, receipt = ses.get("mail") or {}, ses.get("receipt") or {}
    ses_id = str(mail.get("messageId", ""))
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", ses_id):
        log.error("SES event without a usable message id; ignored")
        return {"status": "ignored"}
    key = INBOUND_PREFIX + ses_id
    try:
        claimed = sender_of(list((mail.get("commonHeaders") or {}).get("from") or []))
    except UploadError:
        claimed = ""

    case = None
    with repo_scope() as db:
        try:
            failures = service.verdict_failures(receipt)
            if failures:
                raise UploadError("SES checks did not pass: " + ", ".join(failures), 403)
            if not claimed:
                raise UploadError("the message must have exactly one valid From address", 422)
            owner = service.resolve_sender(db, claimed)
            raw = _fetch(get_storage(), key)
            if raw is None:                                    # an at-least-once re-delivery after the first one finished
                log.info("inbound mail %s: already handled", ses_id)
                return {"status": "gone"}
            parsed = parse(raw)
            if parsed.sender != claimed:
                raise UploadError("the From address differs from the one SES evaluated", 403)
            case, _warnings, created = service.submit(db, owner, parsed, "ses")
            result = {"status": "created" if created else "duplicate", "case_id": case.id}
        except UploadError as e:
            # internet mail is unauthenticated: log rejections (CloudWatch) instead of growing the audit chain with them
            log.warning("inbound mail rejected (sender domain %s): %s", service.domain_of(claimed), e)
            result = {"status": "rejected", "reason": str(e)}
    if case is not None and should_enqueue(case, result["status"] == "created"):
        queue.enqueue_case(case.id)
    _discard(key)
    log.info("inbound mail %s: %s", ses_id, result.get("reason", result["status"]))
    return result


def _fetch(storage, key: str) -> bytes | None:
    from botocore.exceptions import ClientError

    try:
        return storage.get(key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise


def _discard(key: str) -> None:
    from medishield.storage.base import get_storage

    try:
        get_storage().delete(key)
    except Exception:
        log.warning("could not delete %s (the lifecycle rule will expire it)", key, exc_info=True)
