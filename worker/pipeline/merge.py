"""무음 구간 → 삭제 구간."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from worker.pipeline.frames import snap_inward
from worker.pipeline.intervals import Interval, clip, merge_intervals


@dataclass(frozen=True)
class SilenceCutSettings:
    padding_ms: int = 150
    """말 앞뒤로 남겨 둘 여유. 영상 시작·끝 쪽에는 적용하지 않는다."""
    min_silence_ms: int = 700
    """이보다 짧은 무음은 자르지 않는다 (padding 적용 전 길이 기준)."""


def silence_to_cuts(
    silences: list[Interval],
    *,
    duration_ms: int,
    fps: Fraction,
    settings: SilenceCutSettings,
) -> list[Interval]:
    """무음 구간에 padding·최소 길이·프레임 스냅을 적용해 삭제 구간을 만든다.

    스냅은 안쪽으로만 한다. 그래서 삭제 구간은 항상 원래 무음 안에 있다.
    """
    cuts: list[Interval] = []
    for s in merge_intervals(clip(silences, duration_ms)):
        if s.length_ms < settings.min_silence_ms:
            continue
        start = s.start_ms if s.start_ms == 0 else s.start_ms + settings.padding_ms
        end = s.end_ms if s.end_ms == duration_ms else s.end_ms - settings.padding_ms
        if end <= start:
            continue
        snapped = snap_inward(start, end, fps)
        if snapped is None:
            continue
        # 영상 시작·끝에 붙은 쪽은 스냅하지 않는다 (끝에 1프레임 미만 조각이 남지 않게)
        cut_start = 0 if start == 0 else snapped[0]
        cut_end = duration_ms if end == duration_ms else snapped[1]
        cuts.append(Interval(cut_start, cut_end))
    return merge_intervals(cuts)
