from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePath
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.db import get_session
from app.models import EditDecision, Export, Job, Project, TranscriptWord
from app.queue import Enqueue, get_enqueue
from app.schemas import (
    DecisionCreate,
    DecisionOut,
    DecisionPatch,
    ExportOut,
    JobOut,
    ProjectCreate,
    ProjectCreated,
    ProjectOut,
    WordOut,
)
from app.settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    storage.ensure_bucket()
    yield


app = FastAPI(title="AI Cut Editor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = Annotated[Session, Depends(get_session)]
Q = Annotated[Enqueue, Depends(get_enqueue)]

ALLOWED_EXT = {".mp4": "video/mp4", ".mov": "video/quicktime"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _project(db: Session, project_id: uuid.UUID) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "프로젝트가 없습니다")
    return p


def _latest_job(db: Session, project_id: uuid.UUID) -> Job | None:
    return db.scalars(
        select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc()).limit(1)
    ).first()


def _out(db: Session, p: Project) -> ProjectOut:
    out = ProjectOut.model_validate(p)
    job = _latest_job(db, p.id)
    out.job = JobOut.model_validate(job) if job else None
    if p.proxy_key:
        out.proxy_url = storage.presign_get(p.proxy_key)
    if p.peaks_key:
        out.peaks_url = storage.presign_get(p.peaks_key)
    return out


def _start_job(db: Session, enqueue: Enqueue, p: Project, type_: str, status: str) -> None:
    job = Job(project_id=p.id, type=type_, stage="대기 중")
    db.add(job)
    p.status = status
    p.error = None
    db.commit()
    enqueue(f"worker.jobs.{type_}_job", str(p.id), str(job.id))


@app.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: DB) -> ProjectCreated:
    ext = PurePath(body.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(422, "MP4 또는 MOV 파일만 올릴 수 있습니다")
    if body.size_bytes > settings.max_upload_bytes:
        raise HTTPException(422, "파일이 500MB를 넘습니다")
    pid = uuid.uuid4()
    p = Project(
        id=pid,
        title=body.title,
        filename=body.filename,
        source_key=f"projects/{pid}/source{ext}",
        size_bytes=body.size_bytes,
    )
    db.add(p)
    db.commit()
    content_type = ALLOWED_EXT[ext]
    return ProjectCreated(
        project=_out(db, p),
        upload_url=storage.presign_put(p.source_key, content_type),
        upload_headers={"Content-Type": content_type},
    )


@app.get("/projects")
def list_projects(db: DB) -> list[ProjectOut]:
    rows = db.scalars(select(Project).order_by(Project.created_at.desc()).limit(50))
    return [_out(db, p) for p in rows]


@app.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, db: DB) -> ProjectOut:
    return _out(db, _project(db, project_id))


@app.post("/projects/{project_id}/analyze", status_code=202)
def analyze(project_id: uuid.UUID, db: DB, enqueue: Q) -> ProjectOut:
    """업로드 완료 알림 (또는 실패한 분석 재시도)."""
    p = _project(db, project_id)
    if p.status not in ("created", "uploaded", "failed"):
        raise HTTPException(409, f"지금 상태({p.status})에서는 분석을 시작할 수 없습니다")
    size = storage.head_size(p.source_key)
    if size is None:
        raise HTTPException(409, "업로드된 파일이 없습니다")
    if size != p.size_bytes:
        raise HTTPException(409, f"업로드가 완료되지 않았습니다 ({size}/{p.size_bytes} bytes)")
    _start_job(db, enqueue, p, "analyze", "analyzing")
    return _out(db, p)


@app.get("/projects/{project_id}/transcript")
def transcript(project_id: uuid.UUID, db: DB) -> list[WordOut]:
    _project(db, project_id)
    rows = db.scalars(
        select(TranscriptWord)
        .where(TranscriptWord.project_id == project_id)
        .order_by(TranscriptWord.idx)
    )
    return [WordOut.model_validate(w) for w in rows]


@app.get("/projects/{project_id}/decisions")
def decisions(project_id: uuid.UUID, db: DB) -> list[DecisionOut]:
    return [DecisionOut.model_validate(d) for d in _project(db, project_id).decisions]


def _editable(p: Project) -> None:
    if p.status not in ("review", "done"):
        raise HTTPException(409, f"지금 상태({p.status})에서는 수정할 수 없습니다")


def _check_range(p: Project, start: int, end: int) -> None:
    if not (0 <= start < end <= (p.duration_ms or 0)):
        raise HTTPException(422, "구간이 영상 범위를 벗어났거나 시작이 끝보다 늦습니다")


@app.patch("/projects/{project_id}/decisions/{decision_id}")
def patch_decision(
    project_id: uuid.UUID, decision_id: uuid.UUID, body: DecisionPatch, db: DB
) -> DecisionOut:
    p = _project(db, project_id)
    _editable(p)
    d = db.get(EditDecision, decision_id)
    if d is None or d.project_id != p.id:
        raise HTTPException(404, "후보가 없습니다")
    start = body.start_ms if body.start_ms is not None else d.start_ms
    end = body.end_ms if body.end_ms is not None else d.end_ms
    _check_range(p, start, end)
    d.start_ms, d.end_ms = start, end
    if body.status:
        d.status = body.status
    db.commit()
    return DecisionOut.model_validate(d)


@app.post("/projects/{project_id}/decisions", status_code=201)
def add_decision(project_id: uuid.UUID, body: DecisionCreate, db: DB) -> DecisionOut:
    p = _project(db, project_id)
    _editable(p)
    _check_range(p, body.start_ms, body.end_ms)
    d = EditDecision(
        project_id=p.id,
        start_ms=body.start_ms,
        end_ms=body.end_ms,
        kind="manual",
        reason=body.reason or "직접 추가",
        confidence=1.0,
        status="accepted",
        source="user",
    )
    db.add(d)
    db.commit()
    return DecisionOut.model_validate(d)


@app.post("/projects/{project_id}/render", status_code=202)
def render(project_id: uuid.UUID, db: DB, enqueue: Q) -> ProjectOut:
    p = _project(db, project_id)
    _editable(p)
    _start_job(db, enqueue, p, "render", "rendering")
    return _out(db, p)


@app.get("/projects/{project_id}/exports")
def exports(project_id: uuid.UUID, db: DB) -> list[ExportOut]:
    p = _project(db, project_id)
    rows = db.scalars(
        select(Export).where(Export.project_id == p.id).order_by(Export.created_at.desc())
    )
    stem = PurePath(p.filename).stem
    return [
        ExportOut(
            format=e.format,
            url=storage.presign_get(e.object_key, filename=f"{stem}_edited.{e.format}"),
            created_at=e.created_at,
        )
        for e in rows
    ]
