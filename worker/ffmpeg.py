"""FFmpeg/ffprobe 호출은 전부 여기서만 한다 (CLAUDE.md)."""

from __future__ import annotations

import functools
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from worker.pipeline.probe import MediaInfo, parse_ffprobe


class FFmpegError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"{args[0]} 실패 (exit {proc.returncode}):\n{tail}")
    return proc


def probe(path: Path) -> MediaInfo:
    proc = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    return parse_ffprobe(proc.stdout)


def detect_silence(path: Path, *, threshold_db: float, min_silence_s: float) -> str:
    """silencedetect 로그(stderr)를 그대로 돌려준다. 파싱은 pipeline/silence.py."""
    proc = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            f"silencedetect=noise={threshold_db}dB:d={min_silence_s}",
            "-f",
            "null",
            "-",
        ]
    )
    return proc.stderr


def run(args: list[str], on_progress: Callable[[int], None] | None = None) -> None:
    """임의의 ffmpeg 명령 실행. args는 'ffmpeg' 뒤의 인자.

    on_progress를 주면 출력 기준 처리된 시간(ms)을 주기적으로 넘긴다.
    """
    base = ["ffmpeg", "-hide_banner", "-nostats", "-y"]
    if on_progress is None:
        _run([*base, *args])
        return
    with tempfile.TemporaryFile(mode="w+") as err:
        proc = subprocess.Popen(
            [*base, "-progress", "pipe:1", *args], stdout=subprocess.PIPE, stderr=err, text=True
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and value.isdigit():
                on_progress(int(value) // 1000)
        if proc.wait() != 0:
            err.seek(0)
            tail = "\n".join(err.read().strip().splitlines()[-15:])
            raise FFmpegError(f"ffmpeg 실패 (exit {proc.returncode}):\n{tail}")


@functools.cache
def has_encoder(name: str) -> bool:
    proc = _run(["ffmpeg", "-hide_banner", "-encoders"])
    return any(line.split()[1:2] == [name] for line in proc.stdout.splitlines())


def extract_audio(src: Path, dst: Path) -> None:
    """STT용 16kHz 모노 FLAC. 4K 영상 대신 이걸 업로드해 전송량을 줄인다."""
    run(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(dst)])

