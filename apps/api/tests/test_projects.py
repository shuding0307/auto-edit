"""프로젝트·후보 API (실제 Postgres + S3, 큐는 가짜)."""

from __future__ import annotations

import uuid
from typing import Any

import httpx

from app.db import SessionLocal
from app.models import EditDecision, Project

Api = tuple[Any, Any]


def create(client: Any, size: int = 5, filename: str = "talk.MOV") -> dict[str, Any]:
    res = client.post(
        "/projects",
        json={
            "title": "t",
            "filename": filename,
            "content_type": "video/quicktime",
            "size_bytes": size,
        },
    )
    assert res.status_code == 201, res.text
    return dict(res.json())


def test_create_validates_file(api: Api) -> None:
    client, _ = api
    bad = {"title": "t", "content_type": "x", "size_bytes": 10}
    assert client.post("/projects", json={**bad, "filename": "a.avi"}).status_code == 422
    big = {**bad, "filename": "a.mp4", "size_bytes": 600 * 1024 * 1024}
    assert client.post("/projects", json=big).status_code == 422


def test_upload_then_analyze(api: Api) -> None:
    client, queue = api
    body = create(client, size=5)
    pid = body["project"]["id"]
    assert body["project"]["status"] == "created"

    # 업로드 전 분석 요청은 거절
    assert client.post(f"/projects/{pid}/analyze").status_code == 409
    # presigned URL로 브라우저처럼 직접 PUT (Content-Type 일치해야 함)
    put = httpx.put(body["upload_url"], content=b"12345", headers=body["upload_headers"])
    assert put.status_code == 200, put.text

    res = client.post(f"/projects/{pid}/analyze")
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "analyzing"
    assert res.json()["job"]["type"] == "analyze"
    assert queue.calls == [("worker.jobs.analyze_job", pid, res.json()["job"]["id"])]
    # 분석 중에 다시 요청하면 거절
    assert client.post(f"/projects/{pid}/analyze").status_code == 409


def test_partial_upload_is_rejected(api: Api) -> None:
    client, queue = api
    body = create(client, size=10)
    httpx.put(body["upload_url"], content=b"123", headers=body["upload_headers"])
    res = client.post(f"/projects/{body['project']['id']}/analyze")
    assert res.status_code == 409 and "완료되지" in res.json()["detail"]
    assert queue.calls == []


def _review_project() -> tuple[str, str]:
    """분석이 끝난 상태의 프로젝트와 후보 하나를 DB에 직접 만든다."""
    with SessionLocal() as db:
        p = Project(
            title="t",
            filename="a.mp4",
            source_key="k",
            size_bytes=1,
            status="review",
            duration_ms=10_000,
            fps="30/1",
            has_audio=True,
        )
        db.add(p)
        db.flush()
        d = EditDecision(
            project_id=p.id,
            start_ms=1000,
            end_ms=2000,
            kind="filler",
            reason="음",
            confidence=0.7,
            status="suggested",
            source="llm",
        )
        db.add(d)
        db.commit()
        return str(p.id), str(d.id)


def test_review_edits(api: Api) -> None:
    client, _ = api
    pid, did = _review_project()
    url = f"/projects/{pid}/decisions/{did}"

    res = client.patch(url, json={"status": "accepted", "start_ms": 1100})
    assert res.status_code == 200
    assert (res.json()["status"], res.json()["start_ms"], res.json()["end_ms"]) == (
        "accepted",
        1100,
        2000,
    )

    assert client.patch(url, json={"end_ms": 900}).status_code == 422  # 시작보다 앞
    assert client.patch(url, json={"end_ms": 10_001}).status_code == 422  # 영상 밖
    assert client.patch(url, json={"status": "maybe"}).status_code == 422
    other = f"/projects/{uuid.uuid4()}/decisions/{did}"
    assert client.patch(other, json={"status": "rejected"}).status_code == 404

    res = client.post(f"/projects/{pid}/decisions", json={"start_ms": 5000, "end_ms": 5500})
    assert res.status_code == 201
    assert (res.json()["source"], res.json()["status"], res.json()["kind"]) == (
        "user",
        "accepted",
        "manual",
    )

    listed = client.get(f"/projects/{pid}/decisions").json()
    assert [d["start_ms"] for d in listed] == [1100, 5000]


def test_render_only_from_review(api: Api) -> None:
    client, queue = api
    pid, did = _review_project()
    res = client.post(f"/projects/{pid}/render")
    assert res.status_code == 202 and res.json()["status"] == "rendering"
    assert queue.calls[0][0] == "worker.jobs.render_job"
    # 렌더 중에는 수정·재렌더 불가
    assert client.post(f"/projects/{pid}/render").status_code == 409
    url = f"/projects/{pid}/decisions/{did}"
    assert client.patch(url, json={"status": "rejected"}).status_code == 409
