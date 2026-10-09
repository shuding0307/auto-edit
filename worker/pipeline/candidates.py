"""무음 컷 + LLM 컷 → 삭제 후보 (edit_decisions 행)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from typing import Any

from worker.pipeline.frames import snap_inward
from worker.pipeline.intervals import Interval, merge_intervals
from worker.pipeline.llm_cuts import LlmCut, cut_to_ms
from worker.pipeline.transcript import Word


@dataclass(frozen=True)
class Candidate:
    start_ms: int
    end_ms: int
    kind: str  # silence / repetition / false_start / filler
    reason: str
    confidence: float
    source: str  # rule / llm / user
    status: str  # suggested / accepted / rejected

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcceptPolicy:
    """기본은 '제안만'. 자동 승인은 무음과 고신뢰 반복에만."""

    silence: bool = True
    repetition_min_confidence: float = 0.9


DEFAULT_POLICY = AcceptPolicy()


def build_candidates(
    silence_cuts: list[Interval],
    llm_cuts: list[LlmCut],
    words: list[Word],
    *,
    duration_ms: int,
    fps: Fraction,
    policy: AcceptPolicy = DEFAULT_POLICY,
    padding_ms: int = 0,
) -> list[Candidate]:
    out = [
        Candidate(
            c.start_ms,
            c.end_ms,
            "silence",
            f"무음 {c.length_ms / 1000:.1f}s",
            1.0,
            "rule",
            "accepted" if policy.silence else "suggested",
        )
        for c in silence_cuts
    ]
    for cut in llm_cuts:
        start, end = cut_to_ms(cut, words, padding_ms=padding_ms)
        # 영상 끝에 닿는 쪽은 스냅하지 않는다 (merge.py와 같은 규칙)
        snapped = snap_inward(start, end, fps)
        if snapped is None:
            continue
        s = 0 if start == 0 else snapped[0]
        e = duration_ms if end >= duration_ms else snapped[1]
        accepted = cut.kind == "repetition" and cut.confidence >= policy.repetition_min_confidence
        out.append(
            Candidate(
                s,
                e,
                cut.kind,
                cut.reason,
                round(cut.confidence, 3),
                "llm",
                "accepted" if accepted else "suggested",
            )
        )
    return sorted(out, key=lambda c: (c.start_ms, c.end_ms))


def accepted_cuts(candidates: list[Candidate]) -> list[Interval]:
    """렌더에 쓸 삭제 구간 (승인된 후보의 합집합)."""
    return merge_intervals(
        [Interval(c.start_ms, c.end_ms) for c in candidates if c.status == "accepted"]
    )
