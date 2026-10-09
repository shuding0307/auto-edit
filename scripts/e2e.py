"""fixtures 전체 평가. make e2e (LLM 포함: make e2e LLM=1).

fixtures/videos/<name>.(mp4|mov)       테스트 영상
fixtures/expected/<name>.json          정답 컷 {"cuts": [{"start_ms", "end_ms", "kind"?}]}
fixtures/transcripts/<name>.json       (선택) STT 단어 JSON. --llm일 때만 LLM 컷에 사용

결과 표를 출력하고 EVAL_LOG.md에 날짜와 함께 추가한다. 렌더는 하지 않는다 (분석만).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.cut import make_model  # noqa: E402
from worker.analyze import AnalyzeSettings, analyze  # noqa: E402
from worker.config import load_env  # noqa: E402
from worker.pipeline.candidates import accepted_cuts  # noqa: E402
from worker.pipeline.evaluate import evaluate, load_expected  # noqa: E402
from worker.pipeline.intervals import Interval  # noqa: E402
from worker.pipeline.llm_cuts import CutModel  # noqa: E402
from worker.pipeline.transcript import load_words  # noqa: E402

FIX = ROOT / "fixtures"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--llm", action="store_true", help="전사가 있는 영상에 LLM 컷 포함 (비용 발생)")
    p.add_argument("--provider", choices=["gemini", "claude"], default="gemini")
    p.add_argument("--no-log", action="store_true", help="EVAL_LOG.md에 기록하지 않음")
    args = p.parse_args(argv)

    load_env()
    model: CutModel | None = make_model(args.provider, None) if args.llm else None

    videos = sorted(
        v
        for v in (FIX / "videos").iterdir()
        if v.suffix.lower() in (".mp4", ".mov") and "_edited" not in v.stem
    )
    rows: list[str] = []
    skipped: list[str] = []
    total_wrong = 0
    for v in videos:
        exp_path = FIX / "expected" / f"{v.stem}.json"
        if not exp_path.exists():
            skipped.append(f"{v.name} (정답 JSON 없음: {exp_path.relative_to(ROOT)})")
            continue
        tr_path = FIX / "transcripts" / f"{v.stem}.json"
        words = load_words(tr_path.read_text(encoding="utf-8")) if tr_path.exists() else None

        print(f"분석 중: {v.name}", file=sys.stderr)
        a = analyze(v, AnalyzeSettings(), words=words, model=model)
        r = evaluate(
            accepted_cuts(a.candidates),
            [Interval(c.start_ms, c.end_ms) for c in a.candidates],
            load_expected(exp_path.read_text(encoding="utf-8")),
            duration_ms=a.info.duration_ms,
        )
        total_wrong += r.wrong_cuts
        minutes = a.info.duration_ms / 60_000
        boundary = "-" if r.boundary_error_ms is None else f"{r.boundary_error_ms:.0f}"
        llm = "off"
        if words and model:
            served = sorted(set(getattr(model, "served_by", [])))
            llm = f"{args.provider} ({', '.join(served)})" if served else args.provider
        rows.append(
            f"| {v.name} | {llm} | {r.wrong_cuts} ({r.wrong_cut_ms}ms) | "
            f"{r.missed}/{r.expected_total} ({r.missed_ratio:.0%}) | {boundary} | "
            f"{a.seconds / max(minutes, 1e-9):.1f} | ${a.usage.cost_usd / max(minutes, 1e-9):.4f} |"
        )

    if not rows:
        print("평가할 영상이 없습니다.", file=sys.stderr)
        for s in skipped:
            print(f"  건너뜀: {s}", file=sys.stderr)
        return 1

    table = "\n".join(
        [
            "| 영상 | LLM | 잘못 지운 발화 (목표 0) | 놓친 대상 (목표 ≤30%) | "
            "경계 오차 ms (목표 ≤100) | 분석 s/분 | 비용 $/분 |",
            "|---|---|---|---|---|---|---|",
            *rows,
        ]
    )
    print(table)
    for s in skipped:
        print(f"건너뜀: {s}")

    if not args.no_log:
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        log = ROOT / "EVAL_LOG.md"
        header = "" if log.exists() else "# EVAL_LOG\n\n`make e2e` 결과 기록. 최신이 아래.\n"
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{header}\n## {stamp}\n\n{table}\n")
            for s in skipped:
                f.write(f"\n건너뜀: {s}")
            f.write("\n")
        print(f"\n→ {log.relative_to(ROOT)}에 기록", file=sys.stderr)

    return 1 if total_wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
