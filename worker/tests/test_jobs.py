"""analyze_job → render_job 전체 흐름 (실제 FFmpeg·Postgres·S3, STT·LLM은 가짜)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest

from worker import ffmpeg
from worker.pipeline.llm_cuts import Usage
from worker.pipeline.transcript import Word

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")


class FakeModel:
    served_by = ["fake"]

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> tuple[str, Usage]:
        # 단어 1("어")을 추임새로 판단
        cut = {"word_start": 1, "word_end": 1, "kind": "filler", "reason": "어", "confidence": 0.8}
        return json.dumps({"cuts": [cut]}), Usage(10, 5, 0.0)


def _video(path: Path) -> None:
    # 0~1s 톤, 1~3s 무음, 3~4s 톤, 4~5s 톤 (5초)
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=30:duration=5",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='if(between(t,1,3),0,0.5*sin(2*PI*440*t))':s=48000:d=5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )


def test_analyze_then_render(api: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import storage
    from worker import jobs

    client, queue = api
    src = tmp_path / "in.mp4"
    _video(src)

    body = client.post(
        "/projects",
        json={
            "title": "합성",
            "filename": "in.mp4",
            "content_type": "video/mp4",
            "size_bytes": src.stat().st_size,
        },
    ).json()
    pid = body["project"]["id"]
    assert (
        httpx.put(
            body["upload_url"], content=src.read_bytes(), headers=body["upload_headers"]
        ).status_code
        == 200
    )
    client.post(f"/projects/{pid}/analyze")
    _, _, job_id = queue.calls[-1]

    words = [Word(0, 100, 900, "안녕"), Word(1, 3100, 3900, "어"), Word(2, 4000, 4900, "네")]
    monkeypatch.setattr(jobs, "default_stt", lambda: (lambda _src: words))
    monkeypatch.setattr(jobs, "default_model", lambda: FakeModel())
    jobs.analyze_job(pid, job_id)

    p = client.get(f"/projects/{pid}").json()
    assert p["status"] == "review", p
    assert p["job"]["status"] == "done" and p["duration_ms"] == 5000 and p["fps"] == "30/1"
    assert httpx.get(p["proxy_url"]).status_code == 200
    peaks = httpx.get(p["peaks_url"]).json()
    assert peaks["per_second"] == 100 and abs(len(peaks["peaks"]) - 500) <= 2
    assert max(peaks["peaks"][120:280]) == 0 and max(peaks["peaks"][:90]) > 30  # 무음 구간

    assert [w["text"] for w in client.get(f"/projects/{pid}/transcript").json()] == [
        "안녕",
        "어",
        "네",
    ]
    decisions = client.get(f"/projects/{pid}/decisions").json()
    kinds = {(d["kind"], d["status"]) for d in decisions}
    assert kinds == {("silence", "accepted"), ("filler", "suggested")}

    # 사용자가 추임새 후보를 승인 → 렌더
    filler = next(d for d in decisions if d["kind"] == "filler")
    client.patch(f"/projects/{pid}/decisions/{filler['id']}", json={"status": "accepted"})
    client.post(f"/projects/{pid}/render")
    _, _, render_job_id = queue.calls[-1]
    jobs.render_job(pid, render_job_id)

    assert client.get(f"/projects/{pid}").json()["status"] == "done"
    exports = {e["format"]: e["url"] for e in client.get(f"/projects/{pid}/exports").json()}
    assert set(exports) == {"mp4", "json", "csv", "srt"}
    srt = httpx.get(exports["srt"]).content.decode("utf-8")
    # "어"(추임새, 승인됨)는 자막에서 빠지고, 컷 뒤 단어는 편집본 시간으로 당겨진다
    assert "안녕" in srt and "네" in srt and "어\n" not in srt
    csv_text = httpx.get(exports["csv"]).content.decode("utf-8-sig")
    assert csv_text.splitlines()[0].startswith("처리,종류") and "추임새" in csv_text
    out = tmp_path / "out.mp4"
    out.write_bytes(httpx.get(exports["mp4"]).content)
    removed = sum(
        d["end_ms"] - d["start_ms"] for d in client.get(f"/projects/{pid}/decisions").json()
    )
    dur = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert abs(dur * 1000 - (5000 - removed)) < 60
    assert json.loads(httpx.get(exports["json"]).content)["edited_duration_ms"] == 5000 - removed
    assert storage.head_size(f"projects/{pid}/proxy.mp4")


def test_failed_analyze_marks_project(api: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from worker import jobs

    client, queue = api
    body = client.post(
        "/projects",
        json={
            "title": "깨진 파일",
            "filename": "x.mp4",
            "content_type": "video/mp4",
            "size_bytes": 4,
        },
    ).json()
    pid = body["project"]["id"]
    httpx.put(body["upload_url"], content=b"oops", headers=body["upload_headers"])
    client.post(f"/projects/{pid}/analyze")
    monkeypatch.setattr(jobs, "default_stt", lambda: None)
    monkeypatch.setattr(jobs, "default_model", lambda: None)
    with pytest.raises(ffmpeg.FFmpegError):
        jobs.analyze_job(pid, queue.calls[-1][2])
    p = client.get(f"/projects/{pid}").json()
    assert p["status"] == "failed" and p["error"] and p["job"]["status"] == "failed"
    # 실패 후 재시도 가능
    assert client.post(f"/projects/{pid}/analyze").status_code == 202
