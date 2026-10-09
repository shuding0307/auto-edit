from worker.pipeline.intervals import Interval
from worker.pipeline.timemap import TimeMap

# 원본 30초, 5~9초와 20~21초를 삭제 → 편집 25초
TM = TimeMap([Interval(5000, 9000), Interval(20_000, 21_000)], 30_000)


def test_edited_duration() -> None:
    assert TM.edited_duration_ms == 25_000


def test_to_edited() -> None:
    assert TM.to_edited(0) == 0
    assert TM.to_edited(4999) == 4999
    assert TM.to_edited(9000) == 5000
    assert TM.to_edited(25_000) == 20_000  # "원본 25초 → 편집 20초"
    assert TM.to_edited(30_000) == 25_000


def test_to_edited_inside_cut_maps_to_cut_start() -> None:
    assert TM.to_edited(7000) == 5000
    assert TM.to_edited(20_500) == 16_000


def test_to_source() -> None:
    assert TM.to_source(0) == 0
    assert TM.to_source(5000) == 9000
    assert TM.to_source(16_000) == 21_000
    assert TM.to_source(25_000) == 30_000


def test_round_trip_on_kept_times() -> None:
    for t in range(0, 30_000, 250):
        if TM.is_kept(t):
            assert TM.to_source(TM.to_edited(t)) == t


def test_cut_at_start() -> None:
    tm = TimeMap([Interval(0, 1000)], 5000)
    assert tm.to_edited(500) == 0
    assert tm.to_source(0) == 1000


def test_no_cuts_is_identity() -> None:
    tm = TimeMap([], 5000)
    assert tm.to_edited(1234) == 1234 and tm.to_source(1234) == 1234


def test_everything_cut() -> None:
    tm = TimeMap([Interval(0, 5000)], 5000)
    assert tm.edited_duration_ms == 0
    assert tm.to_edited(2500) == 0 and tm.to_source(0) == 0
