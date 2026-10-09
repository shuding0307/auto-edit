"""Gemini STT로 단어 타임코드 JSON 만들기.

python scripts/transcribe.py fixtures/videos/sample.MOV    → fixtures/transcripts/sample.json
python scripts/transcribe.py a.mp4 -o words.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from worker.config import load_env  # noqa: E402
from worker.pipeline.transcript import words_to_json  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="영상 → 단어 타임코드 JSON (Gemini STT)")
    p.add_argument("inputs", type=Path, nargs="+")
    p.add_argument(
        "-o", "--output", type=Path, help="입력이 하나일 때만. 기본 fixtures/transcripts/"
    )
    p.add_argument("--language", default="ko-KR")
    args = p.parse_args(argv)
    if args.output and len(args.inputs) > 1:
        p.error("-o 는 입력이 하나일 때만 쓸 수 있습니다")

    load_env()
    from worker.gemini import transcribe

    for src in args.inputs:
        out = args.output or ROOT / "fixtures" / "transcripts" / f"{src.stem}.json"
        t0 = time.monotonic()
        print(f"전사 중: {src.name}", file=sys.stderr)
        words = transcribe(src, language=args.language)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(words_to_json(words), encoding="utf-8")
        preview = " ".join(w.text for w in words[:15])
        print(f"{out}  {len(words)}단어, {time.monotonic() - t0:.1f}s  | {preview} …")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
