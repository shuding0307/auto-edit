"""S3 왕복. 8MB를 넘으면 boto3가 병렬 범위 전송을 쓰는데, SeaweedFS에선 그게 깨졌었다."""

from __future__ import annotations

import os
from pathlib import Path

from app import storage


def test_large_roundtrip(infra: None, tmp_path: Path) -> None:
    data = os.urandom(20 * 1024 * 1024)
    src, dst = tmp_path / "big.bin", tmp_path / "back.bin"
    src.write_bytes(data)
    storage.upload(src, "test/big.bin", "application/octet-stream")
    assert storage.head_size("test/big.bin") == len(data)
    storage.download("test/big.bin", dst)
    assert dst.read_bytes() == data


def test_browser_cors_preflight(infra: None) -> None:
    import httpx

    from app.settings import settings

    res = httpx.options(
        f"{settings.s3_endpoint}/{settings.s3_bucket}/any/key.mov",
        headers={
            "Origin": settings.web_origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == settings.web_origin
