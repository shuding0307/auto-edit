import csv
import io

from worker.pipeline.intervals import Interval
from worker.pipeline.report import ReportRow, build_csv
from worker.pipeline.srt import Cue, build_cues, is_cut, to_srt, wrap
from worker.pipeline.transcript import Word


def words(*items: tuple[str, int, int]) -> list[Word]:
    return [Word(i, s, e, t) for i, (t, s, e) in enumerate(items)]


# --- SRT ---


def test_cut_words_dropped_and_times_on_edited_timeline() -> None:
    ws = words(
        ("안녕하세요.", 0, 800), ("어", 1000, 1300), ("오늘은", 2000, 2400), ("날씨가", 2400, 2900)
    )
    cues = build_cues(ws, [Interval(950, 1900)], 5000)
    # "어"는 삭제, 2000ms는 편집본에서 2000-950=1050
    assert [c.text for c in cues] == ["안녕하세요.", "오늘은 날씨가"]
    assert cues[1].start_ms == 1050 and cues[1].end_ms == 2900 - 950 + 250


def test_breaks_on_long_pause_and_sentence_end() -> None:
    ws = words(("하나", 0, 300), ("둘", 1200, 1500), ("셋?", 1500, 1800), ("넷", 1900, 2100))
    assert [c.text for c in build_cues(ws, [], 5000)] == ["하나", "둘 셋?", "넷"]


def test_length_limit_and_two_lines() -> None:
    texts = ["가나다라마", "바사아자차", "카타파하", "가나다라마", "바사아자차", "카타파하", "끝"]
    ws = words(*[(t, i * 300, i * 300 + 250) for i, t in enumerate(texts)])
    cues = build_cues(ws, [], 10_000)
    assert all(len(line) <= 18 for c in cues for line in c.text.split("\n"))
    assert all(c.text.count("\n") <= 1 for c in cues)
    assert " ".join(c.text.replace("\n", " ") for c in cues) == " ".join(texts)


def test_cues_never_overlap_and_have_min_duration() -> None:
    ws = words(("짧", 0, 100), ("다.", 100, 150), ("다음", 300, 500))
    cues = build_cues(ws, [], 5000)
    assert cues[0].end_ms <= cues[1].start_ms
    assert cues[1].end_ms - cues[1].start_ms >= 700


def test_cue_clamped_to_edited_duration() -> None:
    (c,) = build_cues(words(("끝", 4800, 4990)), [], 5000)
    assert c.end_ms == 5000


def test_long_sentence_splits_evenly_without_orphan_tail() -> None:
    # 탐욕 분할이면 마지막 "했고"가 혼자 남는다
    texts = "저는 작년에 교환학생을 다녀온 뒤로 해외에서 살고 싶다는 생각을 했고".split()
    ws = words(*[(t, i * 400, i * 400 + 350) for i, t in enumerate(texts)])
    cues = build_cues(ws, [], 20_000)
    assert len(cues) == 2
    sizes = [len(c.text.replace("\n", " ")) for c in cues]
    assert min(sizes) >= 10


def test_wrap() -> None:
    assert wrap("짧은 줄") == "짧은 줄"
    assert wrap("가나다라마 바사아자차 카타파하 가나다") == "가나다라마 바사아자차\n카타파하 가나다"
    # 가운데 공백이 한 줄을 18자 넘게 만들면 두 줄 모두 맞는 공백을 고른다
    text = "지금 남친이 또 외국인이라서 졸업하면 해외에"
    assert all(len(line) <= 18 for line in wrap(text).split("\n"))


def test_is_cut_half_rule() -> None:
    cuts = [Interval(1000, 2000)]
    assert is_cut(Word(0, 1100, 1900, "a"), cuts)
    assert not is_cut(Word(0, 1800, 2400, "a"), cuts)
    assert is_cut(Word(0, 1500, 1500, "a"), cuts)


def test_srt_format() -> None:
    srt = to_srt([Cue(0, 1500, "안녕"), Cue(3_725_004, 3_726_000, "두\n줄")])
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,500\n안녕\n\n2\n01:02:05,004 --> 01:02:06,000\n두\n줄\n\n"
    )


# --- CSV ---


def test_csv_report() -> None:
    rows = [
        ReportRow(5000, 6000, "repetition", "suggested", "llm", 0.7, "다시 말함"),
        ReportRow(1000, 2000, "silence", "accepted", "rule", 1.0, "무음 1.0s"),
    ]
    data = build_csv(rows, [Interval(1000, 2000)], 10_000)
    assert data.startswith(b"\xef\xbb\xbf")  # 엑셀용 BOM
    table = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert table[0][0] == "처리"
    assert table[1][:7] == ["삭제", "무음", "규칙", "1.000", "2.000", "1.000", "1.000"]
    # 컷 뒤 5.0초는 편집본 4.0초
    assert table[2][:7] == ["제안(미반영)", "반복", "AI", "5.000", "6.000", "1.000", "4.000"]
    assert table[2][8] == "다시 말함"


# --- FCPXML ---


def test_fcpxml_clips_follow_keeps() -> None:
    from fractions import Fraction
    from pathlib import Path
    from xml.etree import ElementTree as ET

    from worker.pipeline.fcpxml import build_fcpxml
    from worker.pipeline.probe import MediaInfo

    info = MediaInfo(10_000, Fraction(30000, 1001), True, 1920, 1080)
    keeps = [Interval(0, 1000), Interval(3000, 10_000)]
    xml = build_fcpxml(Path("/data/a b.mov"), info, keeps, title="t")
    root = ET.fromstring(xml.split("\n", 2)[2])

    def attr(path: str, name: str) -> str | None:
        el = root.find(path)
        assert el is not None, path
        return el.get(name)

    assert attr("resources/format", "frameDuration") == "1001/30000s"
    assert attr("resources/asset/media-rep", "src") == "file:///data/a%20b.mov"
    clips = root.findall(".//spine/asset-clip")
    # 1000ms@29.97 = 30프레임, 3000ms = 90프레임, 10000ms = 300프레임
    assert [(c.get("offset"), c.get("start"), c.get("duration")) for c in clips] == [
        ("0s", "0s", "1001/1000s"),
        ("1001/1000s", "3003/1000s", "7007/1000s"),
    ]
    assert attr(".//sequence", "duration") == "1001/125s"  # 240프레임 (약분된 유리수)
