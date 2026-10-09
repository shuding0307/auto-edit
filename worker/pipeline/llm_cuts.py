"""LLM 반복·말실수 컷.

LLM에는 단어 인덱스가 붙은 텍스트만 보내고, 단어 인덱스 범위로만 답하게 한다.
타임코드는 서버가 인덱스에서 계산한다 (LLM이 시간을 지어낼 수 없음).
LLM 호출 자체는 CutModel 인터페이스 뒤에 있고, 여기엔 네트워크 코드가 없다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from worker.pipeline.transcript import Window, Word, render_indexed, windows

KINDS = ("repetition", "false_start", "filler")

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cuts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word_start": {"type": "integer"},
                    "word_end": {"type": "integer"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["word_start", "word_end", "kind", "reason", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cuts"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
너는 한국어 말하기 영상의 편집자다. 음성 인식 결과에서 지워야 할 단어 구간을 찾는다.

입력의 각 단어 앞에는 [번호]가 붙어 있고, ⏸는 말 사이의 쉼이다.
찾을 것:
- repetition: 같은 말을 다시 한 경우. 앞쪽(실패한 쪽)을 지운다.
- false_start: 말하다 멈추고 처음부터 다시 시작한 경우. 버려진 시작 부분을 지운다.
- filler: 의미 없는 추임새("음", "어", "그" 등). 문장 의미에 기여하면 지우지 않는다.

규칙:
- word_start와 word_end는 지울 첫 단어와 마지막 단어의 번호다 (둘 다 포함).
- "판단 범위"로 지정된 번호 안에서만 답한다. 그 밖의 단어는 문맥 참고용이다.
- 정상 발화를 지우는 것이 놓치는 것보다 훨씬 나쁘다. 확신이 없으면 confidence를 낮게 주거나 빼라.
- reason은 사람이 검토할 때 볼 짧은 한국어 설명이다.
- 지울 것이 없으면 cuts를 빈 배열로 답한다."""


def build_user_prompt(words: list[Word], window: Window) -> str:
    text = render_indexed(words, window.ctx_start, window.ctx_end)
    return f"판단 범위: [{window.start}] ~ [{window.end - 1}]\n\n전사:\n{text}"


@dataclass(frozen=True)
class LlmCut:
    word_start: int
    word_end: int  # 포함
    kind: str
    reason: str
    confidence: float


@dataclass
class ParseResult:
    cuts: list[LlmCut] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    """버린 항목과 이유. 로그·프롬프트 개선용."""


def parse_response(text: str, window: Window) -> ParseResult:
    """LLM 응답 검증. 범위 밖·역순·알 수 없는 kind·겹치는 구간은 버린다."""
    result = ParseResult()
    try:
        data = json.loads(text)
        items = data["cuts"]
        if not isinstance(items, list):
            raise TypeError("cuts is not a list")
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        result.rejected.append(f"응답 파싱 실패: {e}")
        return result

    valid: list[LlmCut] = []
    for raw in items:
        try:
            cut = LlmCut(
                word_start=_as_int(raw["word_start"]),
                word_end=_as_int(raw["word_end"]),
                kind=str(raw["kind"]),
                reason=str(raw.get("reason", "")),
                confidence=float(raw["confidence"]),
            )
        except (KeyError, TypeError, ValueError) as e:
            result.rejected.append(f"형식 오류 {raw!r}: {e}")
            continue
        problem = _problem(cut, window)
        if problem:
            result.rejected.append(f"{problem}: {cut}")
        else:
            valid.append(cut)

    # 겹치면 신뢰도 높은 쪽을 남긴다
    for cut in sorted(valid, key=lambda c: -c.confidence):
        clash = next((k for k in result.cuts if _overlaps(k, cut)), None)
        if clash is None:
            result.cuts.append(cut)
        else:
            result.rejected.append(f"겹침({clash.word_start}-{clash.word_end}): {cut}")
    result.cuts.sort(key=lambda c: c.word_start)
    return result


def _as_int(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int | float) or v != int(v):
        raise ValueError(f"정수가 아님: {v!r}")
    return int(v)


def _problem(cut: LlmCut, window: Window) -> str | None:
    if cut.kind not in KINDS:
        return "알 수 없는 kind"
    if cut.word_end < cut.word_start:
        return "역순 범위"
    if cut.word_start < window.start or cut.word_end >= window.end:
        return "판단 범위 밖"
    if not 0.0 <= cut.confidence <= 1.0:
        return "confidence 범위 밖"
    return None


def _overlaps(a: LlmCut, b: LlmCut) -> bool:
    return a.word_start <= b.word_end and b.word_start <= a.word_end


def cut_to_ms(cut: LlmCut, words: list[Word], *, padding_ms: int = 0) -> tuple[int, int]:
    """단어 범위 → ms. 지운 단어 뒤의 쉼까지 함께 지우되, 다음 단어 앞에 padding_ms를 남긴다.

    padding은 무음 컷과 같은 규칙이다: 다시 말하기 전의 숨·첫음절을 먹지 않게 한다.
    STT 단어 시각은 100ms 단위로 거칠어서 다음 단어 시작에 딱 붙이면 첫음절이 잘린다.
    시작은 앞 단어 끝보다 앞서지 않게 한다 (STT 타임코드가 겹치는 경우 대비).
    """
    first, last = words[cut.word_start], words[cut.word_end]
    start = first.start_ms
    if cut.word_start > 0:
        start = max(start, words[cut.word_start - 1].end_ms)
    if cut.word_end + 1 < len(words):
        end = max(last.end_ms, words[cut.word_end + 1].start_ms - padding_ms)
    else:
        end = last.end_ms
    return start, max(start, end)


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
        )


class CutModel(Protocol):
    """LLM 호출 인터페이스. 실제 구현은 worker/llm_client.py, 테스트는 가짜."""

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> tuple[str, Usage]: ...


@dataclass
class DetectResult:
    cuts: list[LlmCut]
    rejected: list[str]
    usage: Usage


def detect(
    words: list[Word], model: CutModel, *, window_size: int = 300, context: int = 30
) -> DetectResult:
    cuts: list[LlmCut] = []
    rejected: list[str] = []
    usage = Usage()
    for w in windows(len(words), size=window_size, context=context):
        text, u = model.complete(SYSTEM_PROMPT, build_user_prompt(words, w), RESPONSE_SCHEMA)
        usage += u
        parsed = parse_response(text, w)
        cuts.extend(parsed.cuts)
        rejected.extend(parsed.rejected)
    return DetectResult(cuts=cuts, rejected=rejected, usage=usage)
