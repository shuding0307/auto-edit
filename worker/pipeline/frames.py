"""프레임 경계 스냅. fps는 Fraction으로 다뤄 29.97(30000/1001)도 정확히 계산한다."""

from __future__ import annotations

import math
from fractions import Fraction


def frame_floor(ms: int, fps: Fraction) -> int:
    return math.floor(Fraction(ms) * fps / 1000)


def frame_ceil(ms: int, fps: Fraction) -> int:
    return math.ceil(Fraction(ms) * fps / 1000)


def frame_to_ms(frame: int, fps: Fraction) -> int:
    return round(Fraction(frame) * 1000 / fps)


def frame_to_seconds(frame: int, fps: Fraction) -> Fraction:
    return Fraction(frame) / fps


def snap_inward(start_ms: int, end_ms: int, fps: Fraction) -> tuple[int, int] | None:
    """구간을 안쪽 프레임 경계로 줄인다. 한 프레임도 안 남으면 None."""
    first = frame_ceil(start_ms, fps)
    last = frame_floor(end_ms, fps)
    if last <= first:
        return None
    return frame_to_ms(first, fps), frame_to_ms(last, fps)
