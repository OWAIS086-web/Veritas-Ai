"""S3-compatible object store (SeaweedFS in Docker Compose, AWS S3 or any S3 API in production).

boto3 is synchronous, so calls run in a worker thread.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import anyio
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.integrations.storage.base import (
    ObjectExistsError,
    ObjectNotFoundError,
    ObjectStore,
    validate_key,
)

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_MISSING = {"404", "NoSuchKey", "NotFound", "NoSuchObject"}


class S3Store:
    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket
        self._bucket_ready = False

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in _MISSING | {"NoSuchBucket"}:
                raise
            self._client.create_bucket(Bucket=self._bucket)
        self._bucket_ready = True

    def _exists_sync(self, key: str) -> bool:
        self._ensure_bucket()
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                return False
            raise

    def _put_sync(self, key: str, data: bytes, content_type: str, *, new_only: bool) -> None:
        self._ensure_bucket()
        if new_only and self._exists_sync(key):
            raise ObjectExistsError(key)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def _get_sync(self, key: str) -> bytes:
        self._ensure_bucket()
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                raise ObjectNotFoundError(key) from exc
            raise
        return response["Body"].read()

    async def put_new(self, key: str, data: bytes, content_type: str) -> None:
        validate_key(key)
        if not key.endswith("/original"):
            raise ValueError("put_new is reserved for originals")
        await anyio.to_thread.run_sync(
            lambda: self._put_sync(key, data, content_type, new_only=True)
        )

    async def put_derived(self, key: str, data: bytes, content_type: str) -> None:
        validate_key(key)
        if "/derived/" not in key:
            raise ValueError("put_derived cannot write originals")
        await anyio.to_thread.run_sync(
            lambda: self._put_sync(key, data, content_type, new_only=False)
        )

    async def get(self, key: str) -> bytes:
        validate_key(key)
        return await anyio.to_thread.run_sync(lambda: self._get_sync(key))

    async def exists(self, key: str) -> bool:
        validate_key(key)
        return await anyio.to_thread.run_sync(lambda: self._exists_sync(key))


@lru_cache
def get_store() -> ObjectStore:
    s = get_settings()
    scheme = "https" if s.storage_secure else "http"
    client = boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{s.storage_endpoint}",
        aws_access_key_id=s.storage_access_key,
        aws_secret_access_key=s.storage_secret_key,
        region_name=s.storage_region,
        config=Config(
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3},
            connect_timeout=5,
            read_timeout=60,
        ),
    )
    return S3Store(client, s.storage_bucket)
