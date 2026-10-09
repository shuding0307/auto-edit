"""edit_report.csv: 후보 전체와 처리 결과. 엑셀에서 한글이 깨지지 않게 UTF-8 BOM."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass

from worker.pipeline.intervals import Interval
from worker.pipeline.timemap import TimeMap

KIND_KO = {
    "silence": "무음",
    "repetition": "반복",
    "false_start": "말 끊김",
    "filler": "추임새",
    "manual": "직접 추가",
}
STATUS_KO = {"accepted": "삭제", "suggested": "제안(미반영)", "rejected": "유지"}
SOURCE_KO = {"rule": "규칙", "llm": "AI", "user": "사용자"}


@dataclass(frozen=True)
class ReportRow:
    start_ms: int
    end_ms: int
    kind: str
    status: str
    source: str
    confidence: float
    reason: str


def _sec(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def build_csv(rows: Iterable[ReportRow], cuts: list[Interval], duration_ms: int) -> bytes:
    tm = TimeMap(cuts, duration_ms)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "처리",
            "종류",
            "출처",
            "원본 시작(초)",
            "원본 끝(초)",
            "길이(초)",
            "편집본 위치(초)",
            "신뢰도",
            "이유",
        ]
    )
    for r in sorted(rows, key=lambda r: (r.start_ms, r.end_ms)):
        w.writerow(
            [
                STATUS_KO.get(r.status, r.status),
                KIND_KO.get(r.kind, r.kind),
                SOURCE_KO.get(r.source, r.source),
                _sec(r.start_ms),
                _sec(r.end_ms),
                _sec(r.end_ms - r.start_ms),
                # 삭제된 구간은 편집본에서 이 지점으로 이어 붙는다
                _sec(tm.to_edited(r.start_ms)),
                f"{r.confidence:.2f}",
                r.reason,
            ]
        )
    return buf.getvalue().encode("utf-8-sig")
