"""RQ job: analyze_job / render_job. API가 큐에 넣고, 워커가 실행한다.

워커 실행: make worker   (macOS는 fork 문제로 SimpleWorker 사용)
"""

from __future__ import annotations

import json
import os
import tempfile
import traceback
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from sqlalchemy import delete, select

from app import storage
from app.db import SessionLocal
from app.models import EditDecision, Export, Job, Project, TranscriptWord
from app.settings import settings
from worker import ffmpeg
from worker.analyze import AnalyzeSettings, analyze
from worker.pipeline.intervals import Interval, complement, merge_intervals
from worker.pipeline.llm_cuts import CutModel
from worker.pipeline.peaks import compute_peaks
from worker.pipeline.transcript import Word
from worker.render import render

PEAK_RATE = 100  # 파형 값 개수/초


def _set(job_id: str, **fields: object) -> None:
    with SessionLocal() as db:
        job = db.get(Job, uuid.UUID(job_id))
        assert job is not None
        for k, v in fields.items():
            setattr(job, k, v)
        db.commit()


def _progress(job_id: str, stage: str, progress: float) -> None:
    _set(job_id, stage=stage, progress=round(progress, 3))


@contextmanager
def _job(project_id: str, job_id: str, ok_status: str) -> Iterator[Path]:
    """상태 전이·실패 기록을 한 곳에서. 실패하면 프로젝트 failed + 에러 메시지."""
    _set(job_id, status="running")
    try:
        with tempfile.TemporaryDirectory(prefix="cutjob-") as tmp:
            yield Path(tmp)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        _set(job_id, status="failed", error=msg[:2000], finished_at=datetime.now(UTC))
        with SessionLocal() as db:
            p = db.get(Project, uuid.UUID(project_id))
            assert p is not None
            # 렌더 실패는 검토 상태로 되돌린다 (후보 수정 내용은 그대로)
            p.status = "review" if ok_status == "done" else "failed"
            p.error = msg[:2000]
            db.commit()
        traceback.print_exc()
        raise
    else:
        _set(job_id, status="done", progress=1.0, stage="완료", finished_at=datetime.now(UTC))
        with SessionLocal() as db:
            p = db.get(Project, uuid.UUID(project_id))
            assert p is not None
            p.status = ok_status
            db.commit()


def _encoder() -> str:
    return "h264_videotoolbox" if ffmpeg.has_encoder("h264_videotoolbox") else "libx264"


def default_stt() -> Callable[[Path], list[Word]] | None:
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    from worker.gemini import transcribe

    return transcribe


def default_model() -> CutModel | None:
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    from worker.gemini import GeminiCutModel

    return GeminiCutModel()


def analyze_job(project_id: str, job_id: str) -> None:
    """STT·LLM은 default_stt/default_model로 만든다 (테스트는 이 둘을 바꿔 끼운다)."""
    stt_fn = default_stt()
    cut_model = default_model()
    with _job(project_id, job_id, "review") as tmp:
        with SessionLocal() as db:
            p = db.get(Project, uuid.UUID(project_id))
            assert p is not None
            source_key, ext = p.source_key, Path(p.source_key).suffix

        _progress(job_id, "원본 내려받는 중", 0.02)
        src = tmp / f"source{ext}"
        storage.download(source_key, src)

        info = ffmpeg.probe(src)
        if info.duration_ms > settings.max_duration_ms:
            raise ValueError(f"영상이 10분을 넘습니다 ({info.duration_ms / 60000:.1f}분)")
        with SessionLocal() as db:
            p = db.get(Project, uuid.UUID(project_id))
            assert p is not None
            p.duration_ms = info.duration_ms
            p.fps = f"{info.fps.numerator}/{info.fps.denominator}"
            p.has_audio = info.has_audio
            db.commit()
        if not info.has_audio:
            raise ValueError("오디오 트랙이 없는 영상입니다")

        _progress(job_id, "검토용 미리보기 만드는 중", 0.1)
        proxy, base = tmp / "proxy.mp4", f"projects/{project_id}"
        ffmpeg.make_proxy(src, proxy, encoder=_encoder())
        storage.upload(proxy, f"{base}/proxy.mp4", "video/mp4")
        peaks = compute_peaks(
            ffmpeg.pcm_mono(src, sample_rate=8000), sample_rate=8000, per_second=PEAK_RATE
        )
        peaks_path = tmp / "peaks.json"
        peaks_path.write_text(json.dumps({"per_second": PEAK_RATE, "peaks": peaks}))
        storage.upload(peaks_path, f"{base}/peaks.json", "application/json")

        words: list[Word] | None = None
        if stt_fn is not None:
            _progress(job_id, "음성 인식 중", 0.35)
            words = stt_fn(src)

        _progress(job_id, "컷 후보 찾는 중", 0.6)
        a = analyze(src, AnalyzeSettings(), words=words, model=cut_model if words else None)

        with SessionLocal() as db:
            pid = uuid.UUID(project_id)
            p = db.get(Project, pid)
            assert p is not None
            p.proxy_key, p.peaks_key = f"{base}/proxy.mp4", f"{base}/peaks.json"
            db.execute(delete(TranscriptWord).where(TranscriptWord.project_id == pid))
            db.execute(delete(EditDecision).where(EditDecision.project_id == pid))
            for w in words or []:
                db.add(
                    TranscriptWord(
                        project_id=pid,
                        idx=w.idx,
                        start_ms=w.start_ms,
                        end_ms=w.end_ms,
                        text=w.text,
                        confidence=w.confidence,
                    )
                )
            for c in a.candidates:
                db.add(
                    EditDecision(
                        project_id=pid,
                        start_ms=c.start_ms,
                        end_ms=c.end_ms,
                        kind=c.kind,
                        reason=c.reason,
                        confidence=c.confidence,
                        status=c.status,
                        source=c.source,
                    )
                )
            job = db.get(Job, uuid.UUID(job_id))
            assert job is not None
            job.cost_usd = a.usage.cost_usd
            job.meta = {
                "words": len(words or []),
                "llm_input_tokens": a.usage.input_tokens,
                "llm_output_tokens": a.usage.output_tokens,
                "llm_rejected": a.llm_rejected[:50],
                "llm_served_by": sorted(set(getattr(cut_model, "served_by", []) or [])),
                "stt": stt_fn is not None,
            }
            db.commit()


def render_job(project_id: str, job_id: str) -> None:
    with _job(project_id, job_id, "done") as tmp:
        with SessionLocal() as db:
            p = db.get(Project, uuid.UUID(project_id))
            assert p is not None and p.duration_ms and p.fps
            source_key, ext = p.source_key, Path(p.source_key).suffix
            duration_ms, fps, has_audio = p.duration_ms, Fraction(p.fps), bool(p.has_audio)
            rows = db.scalars(
                select(EditDecision).where(
                    EditDecision.project_id == p.id, EditDecision.status == "accepted"
                )
            ).all()
            cuts = merge_intervals([Interval(d.start_ms, d.end_ms) for d in rows])
            decisions = [
                {
                    "start_ms": d.start_ms,
                    "end_ms": d.end_ms,
                    "kind": d.kind,
                    "reason": d.reason,
                    "source": d.source,
                }
                for d in sorted(rows, key=lambda d: d.start_ms)
            ]

        keeps = complement(cuts, duration_ms)
        if not keeps:
            raise ValueError("승인된 컷이 영상 전체를 덮습니다")

        _progress(job_id, "원본 내려받는 중", 0.02)
        src = tmp / f"source{ext}"
        storage.download(source_key, src)

        edited_ms = sum(k.length_ms for k in keeps)
        _progress(job_id, "렌더링 중", 0.1)
        out = tmp / "edited.mp4"
        render(
            src,
            out,
            keeps,
            duration_ms=duration_ms,
            fps=fps,
            has_audio=has_audio,
            on_progress=lambda done: _progress(
                job_id, "렌더링 중", 0.1 + 0.8 * min(1.0, done / max(edited_ms, 1))
            ),
        )

        _progress(job_id, "업로드 중", 0.92)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        base = f"projects/{project_id}/exports/{stamp}"
        decisions_path = tmp / "edit_decisions.json"
        decisions_path.write_text(
            json.dumps(
                {"duration_ms": duration_ms, "edited_duration_ms": edited_ms, "cuts": decisions},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        storage.upload(out, f"{base}/edited.mp4", "video/mp4")
        storage.upload(decisions_path, f"{base}/edit_decisions.json", "application/json")
        with SessionLocal() as db:
            pid = uuid.UUID(project_id)
            db.add(Export(project_id=pid, format="mp4", object_key=f"{base}/edited.mp4"))
            db.add(Export(project_id=pid, format="json", object_key=f"{base}/edit_decisions.json"))
            db.commit()
