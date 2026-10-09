from fractions import Fraction

from worker.pipeline.candidates import Candidate, accepted_cuts, build_candidates
from worker.pipeline.evaluate import evaluate, load_expected
from worker.pipeline.intervals import Interval
from worker.pipeline.llm_cuts import LlmCut
from worker.pipeline.transcript import Word

FPS = Fraction(25)  # 프레임 = 40ms, 계산이 쉽다
WORDS = [Word(i, i * 1000, i * 1000 + 600, f"w{i}") for i in range(10)]


def build(llm: list[LlmCut], silence: list[Interval] | None = None) -> list[Candidate]:
    return build_candidates(silence or [], llm, WORDS, duration_ms=10_000, fps=FPS)


def test_silence_accepted_llm_suggested_by_default() -> None:
    cands = build([LlmCut(2, 2, "filler", "음", 0.95)], [Interval(5600, 6000)])
    assert [(c.kind, c.source, c.status) for c in cands] == [
        ("filler", "llm", "suggested"),
        ("silence", "rule", "accepted"),
    ]
    assert (cands[0].start_ms, cands[0].end_ms) == (2000, 3000)


def test_only_high_confidence_repetition_auto_accepted() -> None:
    cands = build(
        [
            LlmCut(1, 1, "repetition", "", 0.95),
            LlmCut(3, 3, "repetition", "", 0.7),
            LlmCut(5, 5, "false_start", "", 0.99),
        ]
    )
    assert [c.status for c in cands] == ["accepted", "suggested", "suggested"]


def test_llm_boundaries_snap_inward_to_frames() -> None:
    words = [Word(0, 0, 500, "a"), Word(1, 1010, 1300, "b"), Word(2, 2030, 2500, "c")]
    (c,) = build_candidates([], [LlmCut(1, 1, "filler", "", 0.5)], words, duration_ms=3000, fps=FPS)
    assert (c.start_ms, c.end_ms) == (1040, 2000)


def test_last_word_cut_reaches_video_end() -> None:
    words = [Word(0, 0, 500, "a"), Word(1, 1000, 1990, "음")]
    (c,) = build_candidates([], [LlmCut(1, 1, "filler", "", 0.5)], words, duration_ms=1990, fps=FPS)
    assert c.end_ms == 1990


def test_accepted_cuts_union() -> None:
    cands = build([LlmCut(1, 1, "repetition", "", 0.95)], [Interval(1500, 2400)])
    assert accepted_cuts(cands) == [Interval(1000, 2400)]


# --- evaluate ---


def test_load_expected() -> None:
    raw = '{"cuts": [{"start_ms": 500, "end_ms": 900}, {"start_ms": 0, "end_ms": 600}]}'
    assert load_expected(raw) == [Interval(0, 900)]


def test_evaluate_counts_wrong_and_missed() -> None:
    expected = [Interval(1000, 2000), Interval(5000, 6000), Interval(8000, 9000)]
    accepted = [
        Interval(1020, 1980),  # 정확
        Interval(3000, 3500),  # 정상 발화 500ms 삭제
        Interval(5000, 6050),  # 50ms 넘침: 허용치 안
    ]
    all_ = [*accepted, Interval(8100, 8200)]  # 8000~9000은 10%만 덮음 → 놓침
    r = evaluate(accepted, all_, expected, duration_ms=10_000)
    assert (r.wrong_cuts, r.wrong_cut_ms) == (1, 500)
    assert r.missed == 1 and abs(r.missed_ratio - 1 / 3) < 1e-9
    assert r.boundary_error_ms == (20 + 25) / 2


def test_evaluate_nothing_expected() -> None:
    r = evaluate([], [], [], duration_ms=1000)
    assert r.missed_ratio == 0 and r.boundary_error_ms is None and r.wrong_cuts == 0
