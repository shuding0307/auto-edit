"""편집본 시간축 자막(SRT). 단어 타임코드(원본 기준) + 승인된 컷 → 자막 큐.

규칙 (한국어 자막 관행 기준):
- 한 줄 최대 18자, 최대 2줄. 넘으면 다음 큐로.
- 문장 끝(. ? ! 등)·0.7초 넘는 쉼·6초 넘는 큐에서 끊는다.
- 큐는 최소 0.7초 보이게 하되 다음 큐와 겹치지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from worker.pipeline.intervals import Interval
from worker.pipeline.timemap import TimeMap
from worker.pipeline.transcript import Word

LINE_CHARS = 18
MAX_LINES = 2
PAUSE_BREAK_MS = 700
MAX_CUE_MS = 6000
MIN_CUE_MS = 700
HANG_MS = 250
"""말이 끝난 뒤 자막을 조금 더 남겨 두는 시간."""

SENTENCE_END = (".", "?", "!", "…", "。")


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str  # 줄바꿈 포함


def is_cut(word: Word, cuts: list[Interval]) -> bool:
    """단어가 컷에 절반 이상 덮이면 삭제된 단어 (web lib/cuts.ts isWordCut과 같은 규칙)."""
    length = word.end_ms - word.start_ms
    if length <= 0:
        return any(c.start_ms <= word.start_ms < c.end_ms for c in cuts)
    covered = sum(max(0, min(c.end_ms, word.end_ms) - max(c.start_ms, word.start_ms)) for c in cuts)
    return covered * 2 >= length


def wrap(text: str, width: int = LINE_CHARS) -> str:
    """한 줄을 넘으면 두 줄로. 두 줄 모두 width 이하가 되는 공백 중 가운데에 가장 가까운 곳."""
    if len(text) <= width:
        return text
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return text
    fits = [i for i in spaces if i <= width and len(text) - i - 1 <= width]
    mid = len(text) / 2
    i = min(fits or spaces, key=lambda s: abs(s - mid))
    return f"{text[:i]}\n{text[i + 1 :]}"


Item = tuple[str, int, int]  # (단어, 편집본 시작, 편집본 끝)


def _text(items: list[Item]) -> str:
    return " ".join(t for t, _, _ in items)


def _phrases(items: list[Item]) -> list[list[Item]]:
    """문장 끝·긴 쉼에서 끊는다 (반드시 끊어야 하는 곳)."""
    out: list[list[Item]] = []
    for item in items:
        if out and not (
            out[-1][-1][0].endswith(SENTENCE_END) or item[1] - out[-1][-1][2] >= PAUSE_BREAK_MS
        ):
            out[-1].append(item)
        else:
            out.append([item])
    return out


def _too_big(items: list[Item]) -> bool:
    return len(_text(items)) > LINE_CHARS * MAX_LINES or items[-1][2] - items[0][1] > MAX_CUE_MS


def _split_even(items: list[Item]) -> list[list[Item]]:
    """너무 긴 구절을 비슷한 길이 k조각으로. 탐욕 분할의 '했고.' 같은 꼬리 조각을 막는다."""
    for k in range(2, len(items) + 1):
        target = len(_text(items)) / k
        chunks: list[list[Item]] = [[]]
        for item in items:
            cur = chunks[-1]
            if cur and len(chunks) < k and len(_text([*cur, item])) > target * 1.15:
                chunks.append([item])
            else:
                cur.append(item)
        if not any(_too_big(c) for c in chunks):
            return chunks
    return [[i] for i in items]


def build_cues(words: list[Word], cuts: list[Interval], duration_ms: int) -> list[Cue]:
    tm = TimeMap(cuts, duration_ms)
    kept: list[Item] = [
        (w.text, tm.to_edited(w.start_ms), tm.to_edited(w.end_ms))
        for w in words
        if not is_cut(w, cuts)
    ]
    groups: list[list[Item]] = []
    for phrase in _phrases(kept):
        groups.extend(_split_even(phrase) if _too_big(phrase) else [phrase])

    cues: list[Cue] = []
    for i, g in enumerate(groups):
        start = g[0][1]
        end = max(e for _, _, e in g) + HANG_MS
        end = max(end, start + MIN_CUE_MS)
        if i + 1 < len(groups):
            end = min(end, groups[i + 1][0][1])
        end = min(end, tm.edited_duration_ms)
        if end > start:
            cues.append(Cue(start, end, wrap(_text(g))))
    return cues


def _ts(ms: int) -> str:
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, msec = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"


def to_srt(cues: list[Cue]) -> str:
    return "".join(
        f"{i}\n{_ts(c.start_ms)} --> {_ts(c.end_ms)}\n{c.text}\n\n" for i, c in enumerate(cues, 1)
    )
