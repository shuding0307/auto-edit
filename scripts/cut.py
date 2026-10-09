"""무음 컷 CLI.

python scripts/cut.py input.mp4 --threshold -38 --min 0.7
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker import ffmpeg  # noqa: E402
from worker.pipeline.intervals import complement  # noqa: E402
from worker.pipeline.merge import SilenceCutSettings, silence_to_cuts  # noqa: E402
from worker.pipeline.silence import parse_silencedetect, seconds_to_ms  # noqa: E402
from worker.render import render  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="무음 구간을 잘라낸 MP4를 만든다")
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, help="기본: <input>_edited.mp4")
    p.add_argument("--threshold", type=float, default=-38.0, help="무음 기준 dB (기본 -38)")
    p.add_argument("--min", type=str, default="0.7", help="최소 무음 길이, 초 (기본 0.7)")
    p.add_argument("--padding", type=str, default="0.15", help="말 앞뒤 여유, 초 (기본 0.15)")
    p.add_argument("--dry-run", action="store_true", help="렌더 없이 삭제 구간만 JSON 출력")
    p.add_argument(
        "--encoder",
        choices=["auto", "libx264", "h264_videotoolbox"],
        default="auto",
        help="auto: macOS면 하드웨어(VideoToolbox), 아니면 libx264",
    )
    args = p.parse_args(argv)

    if not ffmpeg.available():
        print("ffmpeg/ffprobe가 PATH에 없습니다 (brew install ffmpeg)", file=sys.stderr)
        return 2

    t0 = time.monotonic()
    info = ffmpeg.probe(args.input)
    settings = SilenceCutSettings(
        padding_ms=seconds_to_ms(args.padding), min_silence_ms=seconds_to_ms(args.min)
    )
    log = ffmpeg.detect_silence(
        args.input, threshold_db=args.threshold, min_silence_s=float(args.min)
    )
    silences = parse_silencedetect(log, info.duration_ms)
    cuts = silence_to_cuts(silences, duration_ms=info.duration_ms, fps=info.fps, settings=settings)
    keeps = complement(cuts, info.duration_ms)
    analyze_s = time.monotonic() - t0

    removed = sum(c.length_ms for c in cuts)
    summary = {
        "input": str(args.input),
        "duration_ms": info.duration_ms,
        "fps": str(info.fps),
        "removed_ms": removed,
        "edited_duration_ms": info.duration_ms - removed,
        "cuts": [{"start_ms": c.start_ms, "end_ms": c.end_ms, "kind": "silence"} for c in cuts],
        "analyze_seconds": round(analyze_s, 2),
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if not keeps:
        print("전부 무음입니다. 렌더할 구간이 없습니다.", file=sys.stderr)
        return 1

    out = args.output or args.input.with_name(f"{args.input.stem}_edited.mp4")
    t1 = time.monotonic()
    edited_ms = info.duration_ms - removed

    def progress(done_ms: int) -> None:
        pct = min(100, done_ms * 100 // max(edited_ms, 1))
        print(f"\r렌더 중… {pct:3d}%  ({time.monotonic() - t1:.0f}s)", end="", file=sys.stderr)

    print(f"분석 완료: 컷 {len(cuts)}개. 렌더 시작 → {out}", file=sys.stderr)
    render(
        args.input,
        out,
        keeps,
        duration_ms=info.duration_ms,
        fps=info.fps,
        has_audio=info.has_audio,
        encoder=args.encoder,
        on_progress=progress,
    )
    print(file=sys.stderr)
    print(
        f"{out}  컷 {len(cuts)}개, {removed / 1000:.2f}s 삭제 "
        f"({info.duration_ms / 1000:.2f}s → {(info.duration_ms - removed) / 1000:.2f}s), "
        f"분석 {analyze_s:.1f}s · 렌더 {time.monotonic() - t1:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
