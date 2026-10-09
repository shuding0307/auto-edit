"""API·워커 통합 테스트 공용 픽스처.

실제 Postgres(테스트 DB cut_test)와 S3(버킷 cut-editor-test)를 쓴다. docker compose가
떠 있지 않으면 해당 테스트는 skip. app 모듈을 import 하기 전에 환경변수를 바꿔야 한다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from worker.config import load_env

load_env()
_BASE_DB = os.environ.get("DATABASE_URL", "postgresql://cut:cut@localhost:5434/cut").replace(
    "postgresql://", "postgresql+psycopg://", 1
)
TEST_DB = _BASE_DB.rsplit("/", 1)[0] + "/cut_test"
os.environ["DATABASE_URL"] = TEST_DB
os.environ["S3_BUCKET"] = "cut-editor-test"


def _infra_error() -> str | None:
    import socket

    for port in (5434, 8333):
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return f"localhost:{port} 응답 없음 (make dev 필요)"
    return None


@pytest.fixture(scope="session")
def infra() -> Iterator[None]:
    err = _infra_error()
    if err:
        pytest.skip(err)
    from sqlalchemy import create_engine, text

    admin = create_engine(_BASE_DB, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.execute(text("select 1 from pg_database where datname='cut_test'")).first():
            c.execute(text("create database cut_test"))
    admin.dispose()

    from app import storage
    from app.db import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    storage.ensure_bucket()
    yield


@pytest.fixture
def db_clean(infra: None) -> Iterator[None]:
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as c:
        c.execute(
            text("truncate projects, transcript_words, edit_decisions, jobs, exports cascade")
        )
    yield


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, func: str, project_id: str, job_id: str) -> None:
        self.calls.append((func, project_id, job_id))


@pytest.fixture
def api(db_clean: None) -> Iterator[tuple[Any, FakeQueue]]:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.queue import get_enqueue

    q = FakeQueue()
    app.dependency_overrides[get_enqueue] = lambda: q
    with TestClient(app) as client:
        yield client, q
    app.dependency_overrides.clear()
