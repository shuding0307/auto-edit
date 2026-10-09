import json
from fractions import Fraction

import pytest

from worker.pipeline.probe import parse_ffprobe


def _raw(rate: str = "30000/1001", audio: bool = True, duration: str = "12.345") -> str:
    streams = [{"codec_type": "video", "avg_frame_rate": rate, "r_frame_rate": "30/1"}]
    if audio:
        streams.append({"codec_type": "audio"})
    return json.dumps({"streams": streams, "format": {"duration": duration}})


def test_parses_ntsc() -> None:
    info = parse_ffprobe(_raw())
    assert info.fps == Fraction(30000, 1001)
    assert info.duration_ms == 12_345
    assert info.has_audio


def test_falls_back_to_r_frame_rate() -> None:
    assert parse_ffprobe(_raw(rate="0/0")).fps == Fraction(30)


def test_no_audio() -> None:
    assert not parse_ffprobe(_raw(audio=False)).has_audio


def test_no_video_raises() -> None:
    with pytest.raises(ValueError):
        parse_ffprobe(json.dumps({"streams": [{"codec_type": "audio"}], "format": {}}))


def test_iphone_jittery_avg_uses_nominal() -> None:
    raw = json.dumps(
        {
            "streams": [
                {"codec_type": "video", "avg_frame_rate": "678240/28261", "r_frame_rate": "24/1"}
            ],
            "format": {"duration": "58.877083"},
        }
    )
    assert parse_ffprobe(raw).fps == Fraction(24)
