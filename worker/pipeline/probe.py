"""ffprobe JSON 출력 파서."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction

from worker.pipeline.silence import seconds_to_ms


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    fps: Fraction
    has_audio: bool


def _rate(text: str | None) -> Fraction | None:
    num, _, den = (text or "0/0").partition("/")
    try:
        n, d = int(num), int(den or "1")
    except ValueError:
        return None
    return Fraction(n, d) if n > 0 and d > 0 else None


def parse_ffprobe(raw: str) -> MediaInfo:
    data = json.loads(raw)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("비디오 스트림이 없습니다")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    # iPhone 등은 avg_frame_rate가 678240/28261(≈23.999) 같은 흔들린 값으로 나온다.
    # 공칭 fps(r_frame_rate)와 0.05% 안에서 같으면 공칭 값을 쓴다 (29.97 vs 30은 0.1%라 구분됨).
    avg = _rate(video.get("avg_frame_rate"))
    nominal = _rate(video.get("r_frame_rate"))
    if avg and nominal and abs(avg - nominal) / nominal < Fraction(1, 2000):
        fps = nominal
    else:
        picked = avg or nominal
        if picked is None:
            raise ValueError(f"fps를 알 수 없습니다: {video.get('avg_frame_rate')}")
        fps = picked

    duration = data.get("format", {}).get("duration") or video.get("duration")
    if duration is None:
        raise ValueError("길이를 알 수 없습니다")
    return MediaInfo(duration_ms=seconds_to_ms(duration), fps=fps, has_audio=has_audio)
