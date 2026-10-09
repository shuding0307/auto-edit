"""주기 작업: 만료 프로젝트 삭제, 멈춘 job 복구. scripts/maintenance.py 가 실행한다."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import storage
from app.db import SessionLocal
from app.models import Job, Project

RETENTION = timedelta(days=7)
JOB_TIMEOUT = timedelta(minutes=35)
"""RQ job_timeout(30분) + 여유. 이보다 오래 running/queued면 워커가 죽은 것으로 본다."""


def delete_project(project_id: object) -> None:
    """S3 객체(원본·프록시·내보내기)와 DB 행(cascade)을 함께 지운다."""
    storage.delete_prefix(f"projects/{project_id}/")
    with SessionLocal() as db:
        p = db.get(Project, project_id)
        if p is not None:
            db.delete(p)
            db.commit()


def cleanup_expired(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    with SessionLocal() as db:
        ids = list(db.scalars(select(Project.id).where(Project.created_at < now - RETENTION)))
    for pid in ids:
        delete_project(pid)
    return [str(i) for i in ids]


def recover_stuck(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    recovered = []
    with SessionLocal() as db:
        stuck = db.scalars(
            select(Job).where(
                Job.status.in_(("queued", "running")), Job.created_at < now - JOB_TIMEOUT
            )
        ).all()
        for job in stuck:
            job.status = "failed"
            job.error = "작업이 제한 시간 안에 끝나지 않았습니다 (워커 중단 추정)"
            job.finished_at = now
            p = db.get(Project, job.project_id)
            if p is not None and p.status in ("analyzing", "rendering"):
                # 렌더가 멈춘 경우 검토 상태로 돌려 다시 렌더할 수 있게
                p.status = "review" if job.type == "render" else "failed"
                p.error = job.error
            recovered.append(str(job.id))
        db.commit()
    return recovered
