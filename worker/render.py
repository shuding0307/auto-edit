"""유지 구간 → 최종 MP4. filtergraph 구성은 순수 함수, 실행은 ffmpeg.py."""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from worker import ffmpeg
from worker.pipeline.intervals import Interval


def _sec(ms: int) -> str:
    """정수 ms → 정확한 초 문자열 (float 미사용)."""
    sign = "-" if ms < 0 else ""
    ms = abs(ms)
    return f"{sign}{ms // 1000}.{ms % 1000:03d}"


def build_filtergraph(
    keeps: list[Interval], *, duration_ms: int, has_audio: bool, fade_ms: int = 10
) -> tuple[str, list[str]]:
    """trim/atrim + concat filtergraph와 출력 매핑(-map 인자)을 만든다.

    컷 경계에는 오디오 클릭 방지용 짧은 페이드를 넣는다. 영상 시작·끝에는 넣지 않는다.
    """
    if not keeps:
        raise ValueError("유지 구간이 없습니다")
    parts: list[str] = []
    labels: list[str] = []
    for i, k in enumerate(keeps):
        s, e = _sec(k.start_ms), _sec(k.end_ms)
        parts.append(f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
        if has_audio:
            chain = f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS"
            fade = min(fade_ms, k.length_ms // 2)
            if fade > 0 and k.start_ms > 0:
                chain += f",afade=t=in:st=0:d={_sec(fade)}"
            if fade > 0 and k.end_ms < duration_ms:
                chain += f",afade=t=out:st={_sec(k.length_ms - fade)}:d={_sec(fade)}"
            parts.append(chain + f"[a{i}]")
            labels.append(f"[a{i}]")
    a = 1 if has_audio else 0
    parts.append(
        f"{''.join(labels)}concat=n={len(keeps)}:v=1:a={a}[outv]" + ("[outa]" if a else "")
    )
    maps = ["-map", "[outv]"] + (["-map", "[outa]"] if a else [])
    return ";".join(parts), maps


def render(
    src: Path,
    dst: Path,
    keeps: list[Interval],
    *,
    duration_ms: int,
    fps: Fraction,
    has_audio: bool,
    encoder: str = "auto",
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """dst는 렌더가 끝난 뒤에만 생긴다 (임시 파일에 쓰고 이름 변경).

    encoder: "auto"면 VideoToolbox(macOS 하드웨어)가 있으면 그걸, 없으면 libx264.
    on_progress: 출력 기준 처리된 ms.
    """
    if encoder == "auto":
        encoder = "h264_videotoolbox" if ffmpeg.has_encoder("h264_videotoolbox") else "libx264"
    graph, maps = build_filtergraph(keeps, duration_ms=duration_ms, has_audio=has_audio)
    tmp = dst.with_name(f".{dst.stem}.partial{dst.suffix}")
    try:
        ffmpeg.run(
            [
                "-i",
                str(src),
                "-filter_complex",
                graph,
                *maps,
                "-r",
                f"{fps.numerator}/{fps.denominator}",
                "-fps_mode",
                "cfr",
                *video_codec_args(encoder),
                "-pix_fmt",
                "yuv420p",
                *(["-c:a", "aac", "-b:a", "192k"] if has_audio else []),
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            on_progress=on_progress,
        )
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)


def video_codec_args(encoder: str) -> list[str]:
    if encoder == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
    if encoder == "h264_videotoolbox":
        # -q:v 는 Apple Silicon에서만 동작하는 고정 품질 모드 (1~100, 높을수록 고품질).
        # 55 ≈ iPhone 4K 원본 비트레이트(약 36Mbps)
        return ["-c:v", "h264_videotoolbox", "-q:v", "55", "-allow_sw", "1"]
    raise ValueError(f"지원하지 않는 인코더: {encoder}")
