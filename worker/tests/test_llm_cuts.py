import json
from typing import Any

from worker.pipeline.llm_cuts import (
    RESPONSE_SCHEMA,
    LlmCut,
    Usage,
    build_user_prompt,
    cut_to_ms,
    detect,
    parse_response,
)
from worker.pipeline.transcript import Window, Word, load_words, render_indexed, windows

W = Window(start=10, end=20, ctx_start=5, ctx_end=25)


def words_from(texts: list[str], step: int = 500, dur: int = 400) -> list[Word]:
    return [Word(i, i * step, i * step + dur, t) for i, t in enumerate(texts)]


def resp(*cuts: dict[str, Any]) -> str:
    return json.dumps({"cuts": list(cuts)}, ensure_ascii=False)


def c(ws: int, we: int, kind: str = "repetition", conf: float = 0.9) -> dict[str, Any]:
    return {"word_start": ws, "word_end": we, "kind": kind, "reason": "r", "confidence": conf}


# --- parse_response ---


def test_valid_cut() -> None:
    r = parse_response(resp(c(11, 12)), W)
    assert r.cuts == [LlmCut(11, 12, "repetition", "r", 0.9)] and r.rejected == []


def test_out_of_window_rejected() -> None:
    # 문맥 구간(5~9, 20~24)은 판단 대상이 아니다
    r = parse_response(resp(c(8, 10), c(19, 20), c(10, 19)), W)
    assert [(x.word_start, x.word_end) for x in r.cuts] == [(10, 19)]
    assert len(r.rejected) == 2


def test_reversed_unknown_kind_bad_confidence_rejected() -> None:
    r = parse_response(resp(c(15, 12), c(11, 11, kind="cough"), c(13, 13, conf=1.5)), W)
    assert r.cuts == [] and len(r.rejected) == 3


def test_non_integer_index_rejected() -> None:
    bad = {"word_start": 11.5, "word_end": 12, "kind": "filler", "reason": "", "confidence": 1}
    assert parse_response(resp(bad), W).cuts == []
    as_float = {"word_start": 11.0, "word_end": 12, "kind": "filler", "reason": "", "confidence": 1}
    assert parse_response(resp(as_float), W).cuts[0].word_start == 11


def test_overlap_keeps_higher_confidence() -> None:
    r = parse_response(resp(c(11, 13, conf=0.6), c(13, 15, conf=0.95), c(17, 17)), W)
    assert [(x.word_start, x.word_end) for x in r.cuts] == [(13, 15), (17, 17)]
    assert any("겹침" in m for m in r.rejected)


def test_garbage_response() -> None:
    assert parse_response("not json", W).cuts == []
    assert parse_response('{"cuts": 3}', W).cuts == []
    assert parse_response("{}", W).rejected


# --- cut_to_ms ---


def test_cut_includes_following_pause() -> None:
    ws = words_from(["어제", "어제", "갔는데"])
    assert cut_to_ms(LlmCut(0, 0, "repetition", "", 1), ws) == (0, 500)


def test_cut_leaves_padding_before_next_word() -> None:
    ws = [Word(0, 0, 400, "어제"), Word(1, 1000, 1400, "어제"), Word(2, 3000, 3400, "갔는데")]
    # 다음 단어(3000) 앞 350ms를 남긴다
    assert cut_to_ms(LlmCut(1, 1, "repetition", "", 1), ws, padding_ms=350) == (1000, 2650)
    # 쉼이 padding보다 짧으면 지운 단어 끝까지만
    ws2 = [Word(0, 0, 400, "a"), Word(1, 500, 900, "b"), Word(2, 1000, 1200, "c")]
    assert cut_to_ms(LlmCut(1, 1, "filler", "", 1), ws2, padding_ms=350) == (500, 900)


def test_cut_at_end_uses_word_end() -> None:
    ws = words_from(["좋아요", "음"])
    assert cut_to_ms(LlmCut(1, 1, "filler", "", 1), ws) == (500, 900)


def test_cut_start_not_before_previous_word_end() -> None:
    ws = [Word(0, 0, 600, "a"), Word(1, 550, 900, "b"), Word(2, 1000, 1200, "c")]
    assert cut_to_ms(LlmCut(1, 1, "filler", "", 1), ws) == (600, 1000)


# --- transcript ---


def test_windows_cover_everything_with_context() -> None:
    ws = windows(650, size=300, context=30)
    assert [(w.start, w.end) for w in ws] == [(0, 300), (300, 600), (600, 650)]
    assert (ws[1].ctx_start, ws[1].ctx_end) == (270, 630)
    assert (ws[2].ctx_start, ws[2].ctx_end) == (570, 650)
    assert windows(0) == []


def test_render_marks_long_pauses() -> None:
    ws = [Word(0, 0, 300, "안녕"), Word(1, 1500, 1800, "하세요"), Word(2, 1900, 2000, "네")]
    assert render_indexed(ws, 0, 3) == "[0]안녕 ⏸1.2s [1]하세요 [2]네"


def test_prompt_states_window() -> None:
    ws = words_from([f"w{i}" for i in range(30)])
    p = build_user_prompt(ws, W)
    assert "판단 범위: [10] ~ [19]" in p and "[5]w5" in p and "[24]w24" in p and "[25]" not in p


def test_load_words_seconds_and_sorting() -> None:
    raw = json.dumps(
        [
            {"start": "1.5", "end": 2, "text": "둘"},
            {"start_ms": 0, "end_ms": 400, "text": "하나", "confidence": 0.8},
            {"start_ms": 10, "end_ms": 20, "text": "  "},
        ]
    )
    assert load_words(raw) == [Word(0, 0, 400, "하나", 0.8), Word(1, 1500, 2000, "둘")]


# --- detect ---


class FakeModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> tuple[str, Usage]:
        assert schema is RESPONSE_SCHEMA and "word_start" in system
        self.prompts.append(user)
        return self.replies.pop(0), Usage(100, 10, 0.001)


def test_detect_runs_each_window_and_sums_usage() -> None:
    ws = words_from([f"w{i}" for i in range(25)])
    fake = FakeModel([resp(c(3, 4)), resp(c(12, 12), c(30, 31)), resp()])
    r = detect(ws, fake, window_size=10, context=2)
    assert len(fake.prompts) == 3 and "판단 범위: [10] ~ [19]" in fake.prompts[1]
    assert [(x.word_start, x.word_end) for x in r.cuts] == [(3, 4), (12, 12)]
    assert len(r.rejected) == 1
    assert r.usage.input_tokens == 300 and abs(r.usage.cost_usd - 0.003) < 1e-9


def test_words_from_offsets_and_roundtrip() -> None:
    from worker.pipeline.transcript import duration_to_ms, words_from_offsets, words_to_json

    assert duration_to_ms("1.250s") == 1250 and duration_to_ms("3s") == 3000
    ws = words_from_offsets(
        [("둘", "1.0s", "1.4s"), ("하나", "0.100s", "0.450s"), ("x", None, "2s"), (" ", "2s", "3s")]
    )
    assert [(w.idx, w.text, w.start_ms, w.end_ms) for w in ws] == [
        (0, "하나", 100, 450),
        (1, "둘", 1000, 1400),
    ]
    assert load_words(words_to_json(ws)) == ws
