"""filtergraph 단위 테스트 + 합성 영상 통합 테스트 (ffmpeg 없으면 skip)."""

from fractions import Fraction
from pathlib import Path

import pytest

from worker import ffmpeg
from worker.pipeline.intervals import Interval, complement
from worker.pipeline.merge import SilenceCutSettings, silence_to_cuts
from worker.pipeline.silence import parse_silencedetect
from worker.render import build_filtergraph, render


def test_filtergraph_two_segments() -> None:
    graph, maps = build_filtergraph(
        [Interval(0, 1000), Interval(2500, 4000)], duration_ms=4000, has_audio=True
    )
    assert "[0:v]trim=start=0.000:end=1.000,setpts=PTS-STARTPTS[v0]" in graph
    assert "[0:a]atrim=start=2.500:end=4.000" in graph
    # 첫 구간은 영상 시작이라 fade-in 없음, 컷 쪽에만 fade-out
    first_audio = graph.split(";")[1]
    assert "t=in" not in first_audio and "afade=t=out:st=0.990:d=0.010" in first_audio
    # 마지막 구간은 영상 끝이라 fade-out 없음
    last_audio = graph.split(";")[3]
    assert "afade=t=in:st=0:d=0.010" in last_audio and "t=out" not in last_audio
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[cv][outa]" in graph
    # 기본은 짧은 변 1080으로 축소 (원본이 작으면 그대로)
    assert graph.endswith(
        "[cv]scale='if(gt(iw,ih),-2,min(1080,iw))':'if(gt(iw,ih),min(1080,ih),-2)'[outv]"
    )
    assert maps == ["-map", "[outv]", "-map", "[outa]"]


def test_filtergraph_without_audio() -> None:
    graph, maps = build_filtergraph(
        [Interval(0, 1000)], duration_ms=1000, has_audio=False, max_short_side=None
    )
    # 원본 해상도 유지: 축소 필터 없이 concat이 바로 출력
    assert "[0:a]" not in graph and graph.endswith("[v0]concat=n=1:v=1:a=0[outv]")
    assert maps == ["-map", "[outv]"]


def test_filtergraph_requires_keeps() -> None:
    with pytest.raises(ValueError):
        build_filtergraph([], duration_ms=1000, has_audio=True)


needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg not installed")


@needs_ffmpeg
def test_end_to_end_synthetic(tmp_path: Path) -> None:
    """1s 톤 · 2s 무음 · 1s 톤 → 무음 대부분이 빠지고 A/V 길이가 1프레임 안에서 일치."""
    src = tmp_path / "in.mp4"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x240:rate=30:duration=4",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='if(between(t,1,3),0,0.5*sin(2*PI*440*t))':s=48000:d=4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ]
    )
    info = ffmpeg.probe(src)
    log = ffmpeg.detect_silence(src, threshold_db=-38, min_silence_s=0.7)
    silences = parse_silencedetect(log, info.duration_ms)
    cuts = silence_to_cuts(
        silences,
        duration_ms=info.duration_ms,
        fps=info.fps,
        settings=SilenceCutSettings(padding_ms=100, min_silence_ms=700),
    )
    assert len(cuts) == 1

    dst = tmp_path / "out.mp4"
    render(
        src,
        dst,
        complement(cuts, info.duration_ms),
        duration_ms=info.duration_ms,
        fps=info.fps,
        has_audio=True,
    )

    expected_ms = info.duration_ms - cuts[0].length_ms
    v_ms, a_ms = _stream_durations_ms(dst)
    frame_ms = 1000 / float(info.fps)
    assert abs(v_ms - expected_ms) <= frame_ms + 1
    assert abs(v_ms - a_ms) <= frame_ms + 25  # AAC 프레임(≈21ms) 패딩 허용
    assert info.fps == Fraction(30)


def _stream_durations_ms(path: Path) -> tuple[float, float]:
    import json
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    streams = json.loads(out)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    return float(v["duration"]) * 1000, float(a["duration"]) * 1000


@needs_ffmpeg
@pytest.mark.parametrize(
    ("size", "expected"),
    [("1440x2560", (1080, 1920)), ("2560x1440", (1920, 1080)), ("640x360", (640, 360))],
)
def test_output_short_side_capped_at_1080(
    tmp_path: Path, size: str, expected: tuple[int, int]
) -> None:
    src = tmp_path / "in.mp4"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(src),
        ]
    )
    dst = tmp_path / "out.mp4"
    render(src, dst, [Interval(0, 1000)], duration_ms=1000, fps=Fraction(30), has_audio=False)
    import json
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(dst)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    v = json.loads(out)["streams"][0]
    assert (v["width"], v["height"]) == expected
