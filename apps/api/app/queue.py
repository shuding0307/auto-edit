"""RQ 큐. 무거운 일(FFmpeg, STT, LLM)은 전부 워커가 한다."""

from __future__ import annotations

from collections.abc import Callable
from functools import cache

from redis import Redis
from rq import Queue

from app.settings import settings

Enqueue = Callable[[str, str, str], None]
"""(job 함수 경로, project_id, job_id) → None. 테스트에서는 가짜로 바꾼다."""


@cache
def _queue() -> Queue:
    return Queue("cut", connection=Redis.from_url(settings.redis_url))


def rq_enqueue(func: str, project_id: str, job_id: str) -> None:
    _queue().enqueue(func, project_id, job_id, job_id=job_id, job_timeout=30 * 60)


def get_enqueue() -> Enqueue:
    return rq_enqueue
