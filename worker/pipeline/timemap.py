"""원본 ↔ 편집 시간 변환. 편집 시간은 저장하지 않고 승인된 컷에서 매번 계산한다."""

from __future__ import annotations

import bisect

from worker.pipeline.intervals import Interval, complement


class TimeMap:
    def __init__(self, cuts: list[Interval], duration_ms: int) -> None:
        self.duration_ms = duration_ms
        self.keeps = complement(cuts, duration_ms)
        # keeps[i]가 편집 영상에서 시작하는 시각
        self._edited_starts: list[int] = []
        acc = 0
        for k in self.keeps:
            self._edited_starts.append(acc)
            acc += k.length_ms
        self.edited_duration_ms = acc

    def to_edited(self, source_ms: int) -> int:
        """원본 시각 → 편집 시각. 삭제된 구간 안이면 그 컷이 시작되는 편집 시각."""
        source_ms = min(max(source_ms, 0), self.duration_ms)
        i = bisect.bisect_right([k.start_ms for k in self.keeps], source_ms) - 1
        if i < 0:
            return 0
        k = self.keeps[i]
        return self._edited_starts[i] + min(source_ms, k.end_ms) - k.start_ms

    def is_kept(self, source_ms: int) -> bool:
        return any(k.start_ms <= source_ms < k.end_ms for k in self.keeps)

    def to_source(self, edited_ms: int) -> int:
        """편집 시각 → 원본 시각."""
        if not self.keeps:
            return 0
        edited_ms = min(max(edited_ms, 0), self.edited_duration_ms)
        i = bisect.bisect_right(self._edited_starts, edited_ms) - 1
        # 경계값(정확히 다음 유지 구간 시작)은 다음 구간의 시작으로 본다
        k = self.keeps[i]
        return k.start_ms + edited_ms - self._edited_starts[i]
