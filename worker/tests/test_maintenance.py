"""삭제·만료·멈춘 job 복구 (실제 Postgres + S3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app import storage
from app.db import SessionLocal
from app.models import Job, Project
from worker.maintenance import cleanup_expired, recover_stuck

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _project(status: str = "review", age: timedelta = timedelta(0)) -> str:
    with SessionLocal() as db:
        p = Project(
            title="t",
            filename="a.mp4",
            source_key="k",
            size_bytes=1,
            status=status,
            duration_ms=1000,
            fps="30/1",
            has_audio=True,
            created_at=NOW - age,
        )
        db.add(p)
        db.commit()
        return str(p.id)


def _put(pid: str, tmp: Path, name: str = "source.mp4") -> str:
    f = tmp / "x.bin"
    f.write_bytes(b"data")
    key = f"projects/{pid}/{name}"
    storage.upload(f, key, "application/octet-stream")
    return key


def test_cleanup_removes_only_expired(db_clean: None, tmp_path: Path) -> None:
    old, new = _project(age=timedelta(days=8)), _project(age=timedelta(days=6))
    old_keys = [_put(old, tmp_path), _put(old, tmp_path, "exports/x/edited.mp4")]
    new_key = _put(new, tmp_path)

    assert cleanup_expired(NOW) == [old]
    assert all(storage.head_size(k) is None for k in old_keys)
    assert storage.head_size(new_key) == 4
    with SessionLocal() as db:
        assert db.get(Project, uuid.UUID(old)) is None
        assert db.get(Project, uuid.UUID(new)) is not None


def test_recover_stuck_jobs(db_clean: None) -> None:
    analyzing, rendering, fresh = (
        _project("analyzing"),
        _project("rendering"),
        _project("analyzing"),
    )
    with SessionLocal() as db:
        jobs = [
            Job(
                project_id=uuid.UUID(analyzing),
                type="analyze",
                status="running",
                created_at=NOW - timedelta(minutes=40),
            ),
            Job(
                project_id=uuid.UUID(rendering),
                type="render",
                status="queued",
                created_at=NOW - timedelta(minutes=40),
            ),
            Job(
                project_id=uuid.UUID(fresh),
                type="analyze",
                status="running",
                created_at=NOW - timedelta(minutes=5),
            ),
        ]
        db.add_all(jobs)
        db.commit()

    assert len(recover_stuck(NOW)) == 2
    with SessionLocal() as db:
        status = {}
        for pid in (analyzing, rendering, fresh):
            p = db.get(Project, uuid.UUID(pid))
            assert p is not None
            status[pid] = p.status
    # 분석이 멈추면 실패(재시도 가능), 렌더가 멈추면 검토로 복귀, 진행 중인 건 그대로
    assert status == {analyzing: "failed", rendering: "review", fresh: "analyzing"}


def test_delete_api(api: Any, tmp_path: Path) -> None:
    client, _ = api
    pid = _project("done")
    key = _put(pid, tmp_path)
    assert client.delete(f"/projects/{pid}").status_code == 204
    assert storage.head_size(key) is None
    assert client.get(f"/projects/{pid}").status_code == 404

    busy = _project("analyzing")
    assert client.delete(f"/projects/{busy}").status_code == 409
