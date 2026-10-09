from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Interval:
    """원본 기준 [start_ms, end_ms) 반열린 구간."""

    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.end_ms < self.start_ms:
            raise ValueError(f"end_ms < start_ms: {self}")

    @property
    def length_ms(self) -> int:
        return self.end_ms - self.start_ms


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    """겹치거나 맞닿은 구간을 합친다. 길이 0인 구간은 버린다."""
    merged: list[Interval] = []
    for iv in sorted(i for i in intervals if i.length_ms > 0):
        if merged and iv.start_ms <= merged[-1].end_ms:
            last = merged[-1]
            merged[-1] = Interval(last.start_ms, max(last.end_ms, iv.end_ms))
        else:
            merged.append(iv)
    return merged


def clip(intervals: list[Interval], duration_ms: int) -> list[Interval]:
    out = []
    for iv in intervals:
        start, end = max(0, iv.start_ms), min(duration_ms, iv.end_ms)
        if end > start:
            out.append(Interval(start, end))
    return out


def complement(cuts: list[Interval], duration_ms: int) -> list[Interval]:
    """삭제 구간 → 유지 구간."""
    keeps: list[Interval] = []
    cursor = 0
    for cut in merge_intervals(clip(cuts, duration_ms)):
        if cut.start_ms > cursor:
            keeps.append(Interval(cursor, cut.start_ms))
        cursor = cut.end_ms
    if cursor < duration_ms:
        keeps.append(Interval(cursor, duration_ms))
    return keeps
