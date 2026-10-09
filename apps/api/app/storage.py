"""S3 호환 저장소 (로컬: SeaweedFS). 영상은 API 서버를 거치지 않고 presigned URL로 직접 오간다."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from app.settings import settings


@cache
def client() -> Any:
    # SeaweedFS는 SigV4 + path-style 이어야 presigned PUT이 통과한다 (CLAUDE.md 함정)
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


# SeaweedFS + 병렬 범위 다운로드(8MB 초과 시 boto3 기본)는 ETag 검증에서 실패한다.
# 로컬·같은 망에서는 단일 스트림으로도 충분히 빠르다 (267MB ≈ 수 초).
_SINGLE_STREAM = TransferConfig(multipart_threshold=5 * 1024**3, use_threads=False)


def ensure_bucket() -> None:
    """버킷 생성 + CORS. 브라우저가 presigned URL로 직접 PUT/GET 하려면 CORS가 필요하다."""
    try:
        client().head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client().create_bucket(Bucket=settings.s3_bucket)
    client().put_bucket_cors(
        Bucket=settings.s3_bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": [settings.web_origin],
                    "AllowedMethods": ["GET", "PUT", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": ["ETag", "Content-Length", "Content-Range"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )


def presign_put(key: str, content_type: str, expires: int = 3600) -> str:
    return str(
        client().generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.s3_bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires,
        )
    )


def presign_get(key: str, expires: int = 3600, filename: str | None = None) -> str:
    params: dict[str, str] = {"Bucket": settings.s3_bucket, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return str(client().generate_presigned_url("get_object", Params=params, ExpiresIn=expires))


def head_size(key: str) -> int | None:
    try:
        return int(client().head_object(Bucket=settings.s3_bucket, Key=key)["ContentLength"])
    except ClientError:
        return None


def download(key: str, dst: Path) -> None:
    client().download_file(settings.s3_bucket, key, str(dst), Config=_SINGLE_STREAM)


def upload(src: Path, key: str, content_type: str) -> None:
    client().upload_file(str(src), settings.s3_bucket, key, ExtraArgs={"ContentType": content_type})


def get_bytes(key: str) -> bytes:
    return bytes(client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read())
