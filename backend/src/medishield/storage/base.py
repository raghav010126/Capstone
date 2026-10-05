"""Object storage interface. ``local_path`` gives the pipeline (OCR / vision) a real file on disk."""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from medishield.config import get_settings


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def local_path(self, key: str) -> Path: ...


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:                      # keys are server-generated; belt and braces
            raise ValueError(f"unsafe storage key {key!r}")
        return p

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def local_path(self, key: str) -> Path:
        return self._path(key)


class S3Storage(Storage):
    """S3-compatible (AWS S3, Supabase Storage, Cloudflare R2, MinIO). Objects are cached locally for the pipeline."""

    def __init__(self, bucket: str, client=None, cache_dir: Path | None = None):
        import boto3

        s = get_settings()
        self.bucket = bucket
        self.client = client or boto3.client("s3", region_name=s.s3_region, endpoint_url=s.s3_endpoint_url or None)
        self.cache = cache_dir or Path(tempfile.gettempdir()) / "medishield-s3-cache"
        self.cache.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def local_path(self, key: str) -> Path:
        p = self.cache / key
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(self.get(key))
        return p


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        if not s.s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
        return S3Storage(s.s3_bucket)
    return LocalStorage(s.upload_dir)
