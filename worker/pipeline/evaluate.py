"""정답 컷(fixtures/expected/*.json)과 예측 비교.

정답 포맷: {"cuts": [{"start_ms": int, "end_ms": int, "kind"?: str}, ...]}
정답 컷이 아닌 부분은 전부 "지우면 안 되는 구간"으로 본다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from worker.pipeline.intervals import Interval, complement, merge_intervals


def load_expected(raw: str) -> list[Interval]:
    data = json.loads(raw)
    return merge_intervals([Interval(int(c["start_ms"]), int(c["end_ms"])) for c in data["cuts"]])


def _overlap(a: Interval, b: Interval) -> int:
    return max(0, min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms))


@dataclass(frozen=True)
class EvalResult:
    wrong_cuts: int
    """정상 발화를 tolerance보다 많이 지운 예측 컷 수. 목표 0."""
    wrong_cut_ms: int
    missed: int
    expected_total: int
    boundary_error_ms: float | None
    """찾은 정답 컷의 시작·끝 평균 오차."""

    @property
    def missed_ratio(self) -> float:
        return self.missed / self.expected_total if self.expected_total else 0.0


def evaluate(
    predicted_accepted: list[Interval],
    predicted_all: list[Interval],
    expected: list[Interval],
    *,
    duration_ms: int,
    tolerance_ms: int = 80,
    found_ratio: float = 0.5,
) -> EvalResult:
    """
    predicted_accepted: 실제로 렌더에서 지워질 구간 → 잘못 지운 발화 계산
    predicted_all: 승인+제안 후보 전체 → 놓친 대상 계산 (사용자가 검토로 보완하므로)
    tolerance_ms: 손으로 표시한 경계의 부정확함을 감안한 허용치
    """
    keeps = complement(expected, duration_ms)
    wrong = 0
    wrong_ms = 0
    for p in predicted_accepted:
        over = sum(_overlap(p, k) for k in keeps)
        if over > tolerance_ms:
            wrong += 1
            wrong_ms += over

    missed = 0
    errors: list[float] = []
    for e in expected:
        best = max(predicted_all, key=lambda p: _overlap(p, e), default=None)
        if best is None or _overlap(best, e) < e.length_ms * found_ratio:
            missed += 1
            continue
        errors.append((abs(best.start_ms - e.start_ms) + abs(best.end_ms - e.end_ms)) / 2)

    return EvalResult(
        wrong_cuts=wrong,
        wrong_cut_ms=wrong_ms,
        missed=missed,
        expected_total=len(expected),
        boundary_error_ms=sum(errors) / len(errors) if errors else None,
    )
