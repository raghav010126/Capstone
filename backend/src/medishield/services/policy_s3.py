"""Uploaded policies on AWS: S3 holds each PDF (``policies/<plan>-<sha>.pdf``) and its parsed index
(``policies/index/<name>.json``), so any process can use a policy without the PDF parser.

The API puts the PDF; the ingest Lambda (``medishield.aws_ingest``) parses it and publishes the index; the agent runtimes fetch
both into their local cache before building the policy store, where ``load_or_ingest`` finds the index and never needs Docling.
"""

from __future__ import annotations

import logging
from pathlib import Path

from botocore.exceptions import ClientError

from medishield.config import get_settings
from medishield.rag.ingest import _cache_file

log = logging.getLogger(__name__)
PREFIX = "policies/"


def enabled() -> bool:
    """S3 is the source of truth for uploaded policies (the AWS configuration)."""
    return get_settings().storage_backend == "s3"


def lambda_ingest() -> bool:
    """Policies are parsed by the ingest Lambda instead of a local worker."""
    return enabled() and bool(get_settings().policy_ingest_function)


def pdf_key(pdf: Path) -> str:
    return f"{PREFIX}{pdf.name}"


def index_key(pdf: Path) -> str:
    return f"{PREFIX}index/{_cache_file(pdf).name}"          # the same name the local index cache uses


def _storage():
    from medishield.storage.base import get_storage

    return get_storage()


def _download(key: str, dst: Path) -> None:
    if dst.exists():
        return
    data = _storage().get(key)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(dst)


def put_pdf(pdf: Path, data: bytes) -> None:
    _storage().put(pdf_key(pdf), data, "application/pdf")


def download_pdf(pdf: Path) -> None:
    _download(pdf_key(pdf), pdf)


def publish_index(pdf: Path) -> None:
    """Store the parsed index that ``load_or_ingest`` cached for ``pdf``."""
    _storage().put(index_key(pdf), _cache_file(pdf).read_bytes(), "application/json")


def fetch(pdf: Path) -> bool:
    """Bring a READY policy's PDF and parsed index into the local cache. False (with a warning) if either is missing in S3."""
    try:
        download_pdf(pdf)
        _download(index_key(pdf), _cache_file(pdf))
        return True
    except ClientError as e:
        log.warning("uploaded policy %s is not available in S3 (%s); skipped", pdf.name, e.response["Error"].get("Code"))
        return False
