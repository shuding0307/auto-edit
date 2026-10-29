"""컷 편집 CLI.

무음만:     python scripts/cut.py input.mp4 --threshold -38 --min 0.7
+ LLM 컷:  python scripts/cut.py input.mp4 --stt                  (Gemini로 전사부터)
           python scripts/cut.py input.mp4 --transcript words.json  (전사 재사용)
           (words.json 포맷은 worker/pipeline/transcript.py, LLM 기본 Gemini)

결과 (<out> = <input>_edited, 렌더는 승인된 후보만 반영):
  <out>.mp4             편집된 영상
  <out>.decisions.json  승인·제안 후보 전체
  <out>.csv             컷 리포트 (엑셀용)
  <out>.srt             편집본 기준 자막 (전사가 있을 때)
  <out>.fcpxml          --fcpxml 일 때. 원본을 참조하는 컷 타임라인 (CapCut 등 가져오기 검증용)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker import ffmpeg  # noqa: E402
from worker.analyze import AnalyzeSettings, analyze  # noqa: E402
from worker.config import load_env  # noqa: E402
from worker.pipeline.candidates import accepted_cuts  # noqa: E402
from worker.pipeline.fcpxml import build_fcpxml  # noqa: E402
from worker.pipeline.intervals import complement  # noqa: E402
from worker.pipeline.llm_cuts import CutModel  # noqa: E402
from worker.pipeline.merge import SilenceCutSettings  # noqa: E402
from worker.pipeline.report import ReportRow, build_csv  # noqa: E402
from worker.pipeline.silence import seconds_to_ms  # noqa: E402
from worker.pipeline.srt import build_cues, to_srt  # noqa: E402
from worker.pipeline.transcript import load_words, words_to_json  # noqa: E402
from worker.render import DEFAULT_SHORT_SIDE, render  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="무음·말실수 구간을 잘라낸 MP4를 만든다")
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, help="기본: <input>_edited.mp4")
    p.add_argument("--threshold", type=float, default=-38.0, help="무음 기준 dB (기본 -38)")
    p.add_argument("--min", type=str, default="0.7", help="최소 무음 길이, 초 (기본 0.7)")
    p.add_argument("--padding", type=str, default="0.35", help="말 앞뒤 여유, 초 (기본 0.35)")
    p.add_argument("--transcript", type=Path, help="STT 단어 JSON. 주면 LLM 컷도 만든다")
    p.add_argument(
        "--stt", action="store_true", help="Gemini로 전사 후 LLM 컷 (<out>.words.json 저장)"
    )
    p.add_argument(
        "--provider", choices=["gemini", "claude"], default="gemini", help="LLM (기본 gemini)"
    )
    p.add_argument("--model", help="LLM 모델 (기본: gemini-3.8-flash / claude-opus-5-5)")
    p.add_argument("--dry-run", action="store_true", help="렌더 없이 후보만 JSON 출력")
    p.add_argument("--fcpxml", action="store_true", help="FCPXML 타임라인도 저장 (실험적)")
    p.add_argument(
        "--original-size", action="store_true", help="원본 해상도로 렌더 (기본: 짧은 변 1080)"
    )
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

    load_env()
    out = args.output or args.input.with_name(f"{args.input.stem}_edited.mp4")
    words = None
    model: CutModel | None = None
    if args.stt:
        from worker.gemini import transcribe

        print("Gemini 전사 중…", file=sys.stderr)
        words = transcribe(args.input)
        words_path = out.with_suffix(".words.json")
        words_path.write_text(words_to_json(words), encoding="utf-8")
        print(f"전사 → {words_path}", file=sys.stderr)
    elif args.transcript:
        words = load_words(args.transcript.read_text(encoding="utf-8"))
    if words is not None:
        model = make_model(args.provider, args.model)
        print(f"전사 {len(words)}단어 → LLM 컷 판단 ({args.provider})", file=sys.stderr)

    settings = AnalyzeSettings(
        threshold_db=args.threshold,
        silence=SilenceCutSettings(
            padding_ms=seconds_to_ms(args.padding), min_silence_ms=seconds_to_ms(args.min)
        ),
    )
    a = analyze(args.input, settings, words=words, model=model)
    info = a.info
    cuts = accepted_cuts(a.candidates)
    removed = sum(c.length_ms for c in cuts)
    summary = {
        "input": str(args.input),
        "duration_ms": info.duration_ms,
        "fps": str(info.fps),
        "removed_ms": removed,
        "edited_duration_ms": info.duration_ms - removed,
        "analyze_seconds": round(a.seconds, 2),
        "llm": {
            "input_tokens": a.usage.input_tokens,
            "output_tokens": a.usage.output_tokens,
            "cost_usd": round(a.usage.cost_usd, 4),
            "rejected": a.llm_rejected,
        },
        "decisions": [c.to_dict() for c in a.candidates],
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    keeps = complement(cuts, info.duration_ms)
    if not keeps:
        print("전부 삭제 대상입니다. 렌더할 구간이 없습니다.", file=sys.stderr)
        return 1

    decisions_path = out.with_suffix(".decisions.json")
    decisions_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [
        ReportRow(c.start_ms, c.end_ms, c.kind, c.status, c.source, c.confidence, c.reason)
        for c in a.candidates
    ]
    out.with_suffix(".csv").write_bytes(build_csv(rows, cuts, info.duration_ms))
    if words:
        srt = to_srt(build_cues(words, cuts, info.duration_ms))
        out.with_suffix(".srt").write_text(srt, encoding="utf-8")
    if args.fcpxml:
        xml = build_fcpxml(args.input, info, keeps, title=out.stem)
        out.with_suffix(".fcpxml").write_text(xml, encoding="utf-8")

    t1 = time.monotonic()
    edited_ms = info.duration_ms - removed

    def progress(done_ms: int) -> None:
        pct = min(100, done_ms * 100 // max(edited_ms, 1))
        print(f"\r렌더 중… {pct:3d}%  ({time.monotonic() - t1:.0f}s)", end="", file=sys.stderr)

    suggested = sum(c.status == "suggested" for c in a.candidates)
    print(
        f"분석 완료: 승인 {len(a.candidates) - suggested}개, 제안(미반영) {suggested}개. "
        f"후보 → {decisions_path}",
        file=sys.stderr,
    )
    render(
        args.input,
        out,
        keeps,
        duration_ms=info.duration_ms,
        fps=info.fps,
        has_audio=info.has_audio,
        encoder=args.encoder,
        max_short_side=None if args.original_size else DEFAULT_SHORT_SIDE,
        on_progress=progress,
    )
    print(file=sys.stderr)
    print(
        f"{out}  {removed / 1000:.2f}s 삭제 "
        f"({info.duration_ms / 1000:.2f}s → {edited_ms / 1000:.2f}s), "
        f"분석 {a.seconds:.1f}s · 렌더 {time.monotonic() - t1:.1f}s"
        + (f" · LLM ${a.usage.cost_usd:.4f}" if words else "")
    )
    return 0


def make_model(provider: str, model: str | None) -> CutModel:
    if provider == "claude":
        from worker.llm_client import ClaudeCutModel

        return ClaudeCutModel(model) if model else ClaudeCutModel()
    from worker.gemini import GeminiCutModel

    return GeminiCutModel(model) if model else GeminiCutModel()


if __name__ == "__main__":
    raise SystemExit(main())
