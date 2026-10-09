"""파형 데이터. 검토 화면이 원본 영상을 디코딩하지 않고 타임라인을 그릴 수 있게 한다."""

from __future__ import annotations

import array


def compute_peaks(pcm_s16le: bytes, *, sample_rate: int, per_second: int = 100) -> list[int]:
    """모노 16bit PCM → 구간별 최대 진폭(0~100). 길이 = ceil(초 × per_second)."""
    samples = array.array("h")
    samples.frombytes(pcm_s16le[: len(pcm_s16le) // 2 * 2])
    bucket = max(1, sample_rate // per_second)
    out: list[int] = []
    for i in range(0, len(samples), bucket):
        chunk = samples[i : i + bucket]
        peak = max((abs(s) for s in chunk), default=0)
        out.append(min(100, round(peak * 100 / 32767)))
    return out
