"""FFmpeg silencedetect 출력 파서. 실제 FFmpeg 호출은 worker/ffmpeg.py."""

from __future__ import annotations

import re
from decimal import Decimal

from worker.pipeline.intervals import Interval

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def seconds_to_ms(text: str) -> int:
    """'1.2345' → 1235. float를 거치지 않아 반올림 오차가 없다."""
    return int((Decimal(text) * 1000).quantize(Decimal(1), rounding="ROUND_HALF_UP"))


def parse_silencedetect(stderr: str, duration_ms: int) -> list[Interval]:
    """silencedetect 로그 → 무음 구간 목록.

    끝나지 않은 마지막 silence_start는 영상 끝까지로 본다.
    음수 시작(코덱 지연으로 가끔 나옴)은 0으로 자른다.
    """
    silences: list[Interval] = []
    open_start: int | None = None
    for line in stderr.splitlines():
        if m := _START.search(line):
            open_start = max(0, seconds_to_ms(m.group(1)))
        elif (m := _END.search(line)) and open_start is not None:
            end = min(duration_ms, seconds_to_ms(m.group(1)))
            if end > open_start:
                silences.append(Interval(open_start, end))
            open_start = None
    if open_start is not None and duration_ms > open_start:
        silences.append(Interval(open_start, duration_ms))
    return silences
