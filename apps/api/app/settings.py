"""환경변수 설정. 레포 루트 .env 를 먼저 읽는다."""

from __future__ import annotations

import os
from dataclasses import dataclass

from worker.config import load_env

load_env()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://cut:cut@localhost:5434/cut"
    )
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    s3_endpoint: str = os.environ.get("S3_ENDPOINT", "http://localhost:8333")
    s3_access_key: str = os.environ.get("S3_ACCESS_KEY", "devaccess")
    s3_secret_key: str = os.environ.get("S3_SECRET_KEY", "devsecret123")
    s3_bucket: str = os.environ.get("S3_BUCKET", "cut-editor")
    max_upload_bytes: int = 500 * 1024 * 1024
    max_duration_ms: int = 10 * 60 * 1000
    web_origin: str = os.environ.get("WEB_ORIGIN", "http://localhost:3000")


def _normalize(url: str) -> str:
    # .env.example 의 postgresql:// 를 psycopg3 드라이버로
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


settings = Settings(database_url=_normalize(Settings().database_url))
