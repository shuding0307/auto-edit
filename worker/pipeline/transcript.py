"""STT 단어 타임코드와 LLM에 보낼 인덱스 텍스트."""

from __future__ import annotations

import json
from dataclasses import dataclass

from worker.pipeline.silence import seconds_to_ms


@dataclass(frozen=True)
class Word:
    idx: int
    start_ms: int
    end_ms: int
    text: str
    confidence: float = 1.0


@dataclass(frozen=True)
class Window:
    """LLM 호출 단위. [start, end) 단어만 판단하고, [ctx_start, ctx_end)는 문맥으로만 보여준다."""

    start: int
    end: int
    ctx_start: int
    ctx_end: int


def load_words(raw: str) -> list[Word]:
    """STT 공통 포맷 JSON → Word 목록.

    포맷: [{"start_ms": int, "end_ms": int, "text": str, "confidence"?: float}, ...]
    start/end 대신 초 단위 "start"/"end"(문자열 또는 숫자)도 받는다.
    시간순 정렬 후 idx를 다시 매긴다.
    """
    items = json.loads(raw)
    if isinstance(items, dict):
        items = items.get("words", [])
    words: list[tuple[int, int, str, float]] = []
    for it in items:
        start = it["start_ms"] if "start_ms" in it else seconds_to_ms(str(it["start"]))
        end = it["end_ms"] if "end_ms" in it else seconds_to_ms(str(it["end"]))
        text = str(it["text"]).strip()
        if not text or end < start:
            continue
        words.append((int(start), int(end), text, float(it.get("confidence", 1.0))))
    words.sort()
    return [Word(i, s, e, t, c) for i, (s, e, t, c) in enumerate(words)]


def windows(n_words: int, *, size: int = 300, context: int = 30) -> list[Window]:
    out = []
    for start in range(0, n_words, size):
        end = min(start + size, n_words)
        out.append(Window(start, end, max(0, start - context), min(n_words, end + context)))
    return out


def render_indexed(words: list[Word], start: int, end: int, *, pause_ms: int = 500) -> str:
    """'[41]어제 [42]어제 ⏸1.2s [43]갔는데' 형식. 긴 쉼은 판단 근거가 되므로 표시한다."""
    parts: list[str] = []
    for i in range(start, end):
        w = words[i]
        if i > start:
            gap = w.start_ms - words[i - 1].end_ms
            if gap >= pause_ms:
                parts.append(f"⏸{gap / 1000:.1f}s")
        parts.append(f"[{w.idx}]{w.text}")
    return " ".join(parts)


def duration_to_ms(text: str) -> int:
    """Google Duration 문자열('1.250s', '3s') → ms."""
    t = text.strip()
    if not t.endswith("s"):
        raise ValueError(f"Duration 형식이 아님: {text!r}")
    return seconds_to_ms(t[:-1])


def words_to_json(words: list[Word]) -> str:
    """load_words가 읽는 공통 포맷으로 저장."""
    return json.dumps(
        [
            {"start_ms": w.start_ms, "end_ms": w.end_ms, "text": w.text, "confidence": w.confidence}
            for w in words
        ],
        ensure_ascii=False,
        indent=1,
    )


def words_from_offsets(items: list[tuple[str, str | None, str | None]]) -> list[Word]:
    """(단어, start_offset, end_offset) 목록 → Word. 시간이 없는 단어는 버린다."""
    rows = []
    for text, start, end in items:
        if not text.strip() or start is None or end is None:
            continue
        s, e = duration_to_ms(start), duration_to_ms(end)
        if e >= s:
            rows.append({"start_ms": s, "end_ms": e, "text": text})
    return load_words(json.dumps(rows))
