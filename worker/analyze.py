"""분석 job: 무음 탐지 (+ 전사가 있으면 LLM 컷) → 삭제 후보. CLI·e2e·워커가 공유한다."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from worker import ffmpeg
from worker.pipeline.candidates import Candidate, build_candidates
from worker.pipeline.llm_cuts import CutModel, Usage, detect
from worker.pipeline.merge import SilenceCutSettings, silence_to_cuts
from worker.pipeline.probe import MediaInfo
from worker.pipeline.silence import parse_silencedetect
from worker.pipeline.transcript import Word


@dataclass(frozen=True)
class AnalyzeSettings:
    threshold_db: float = -38.0
    silence: SilenceCutSettings = field(default_factory=SilenceCutSettings)


@dataclass
class Analysis:
    info: MediaInfo
    candidates: list[Candidate]
    llm_rejected: list[str]
    usage: Usage
    seconds: float


def analyze(
    src: Path,
    settings: AnalyzeSettings,
    *,
    words: list[Word] | None = None,
    model: CutModel | None = None,
) -> Analysis:
    """words와 model이 둘 다 있을 때만 LLM 컷을 만든다."""
    t0 = time.monotonic()
    info = ffmpeg.probe(src)
    log = ffmpeg.detect_silence(
        src,
        threshold_db=settings.threshold_db,
        min_silence_s=settings.silence.min_silence_ms / 1000,
    )
    silences = parse_silencedetect(log, info.duration_ms)
    silence_cuts = silence_to_cuts(
        silences, duration_ms=info.duration_ms, fps=info.fps, settings=settings.silence
    )

    llm_cuts, rejected, usage = [], [], Usage()
    if words and model is not None:
        result = detect(words, model)
        llm_cuts, rejected, usage = result.cuts, result.rejected, result.usage

    candidates = build_candidates(
        silence_cuts,
        llm_cuts,
        words or [],
        duration_ms=info.duration_ms,
        fps=info.fps,
        padding_ms=settings.silence.padding_ms,
    )
    return Analysis(info, candidates, rejected, usage, time.monotonic() - t0)
