from fractions import Fraction

import pytest

from worker.pipeline.frames import frame_to_ms, snap_inward
from worker.pipeline.intervals import Interval, complement, merge_intervals
from worker.pipeline.merge import SilenceCutSettings, silence_to_cuts

FPS30 = Fraction(30)
NTSC = Fraction(30000, 1001)
S = SilenceCutSettings(padding_ms=100, min_silence_ms=500)


def cuts(
    silences: list[Interval],
    duration: int = 10_000,
    fps: Fraction = FPS30,
    settings: SilenceCutSettings = S,
) -> list[Interval]:
    return silence_to_cuts(silences, duration_ms=duration, fps=fps, settings=settings)


def test_padding_shrinks_both_sides_and_snaps_to_frames() -> None:
    # 2000+100=2100 → 프레임 63 = 2100ms, 3000-100=2900 → 프레임 87 = 2900ms
    assert cuts([Interval(2000, 3000)]) == [Interval(2100, 2900)]


def test_snap_is_inward() -> None:
    # 2010+100=2110 → ceil 프레임 64 = 2133, 3010-100=2910 → floor 프레임 87 = 2900
    assert cuts([Interval(2010, 3010)]) == [Interval(2133, 2900)]


def test_short_silence_is_ignored() -> None:
    assert cuts([Interval(2000, 2499)]) == []


def test_padding_longer_than_silence_drops_it() -> None:
    big = SilenceCutSettings(padding_ms=400, min_silence_ms=500)
    assert cuts([Interval(2000, 2700)], settings=big) == []


def test_no_padding_at_video_start_and_end() -> None:
    assert cuts([Interval(0, 1000), Interval(9000, 10_000)]) == [
        Interval(0, 900),
        Interval(9100, 10_000),
    ]


def test_end_not_on_frame_boundary_is_cut_to_the_end() -> None:
    # 10_010ms는 프레임 경계가 아니지만 끝에 조각이 남으면 안 된다
    assert cuts([Interval(9000, 10_010)], duration=10_010) == [Interval(9100, 10_010)]


def test_adjacent_silences_merge_before_padding() -> None:
    assert cuts([Interval(2000, 2400), Interval(2400, 3000)]) == [Interval(2100, 2900)]


def test_overlapping_input_and_unsorted() -> None:
    got = cuts([Interval(6000, 7000), Interval(2000, 2800), Interval(2500, 3000)])
    assert got == [Interval(2100, 2900), Interval(6100, 6900)]


def test_whole_video_silent() -> None:
    assert cuts([Interval(0, 10_000)]) == [Interval(0, 10_000)]


def test_silence_outside_duration_is_clipped() -> None:
    assert cuts([Interval(9500, 12_000)]) == [Interval(9600, 10_000)]


def test_ntsc_boundaries_are_exact_frames() -> None:
    (c,) = cuts([Interval(2000, 3000)], fps=NTSC)
    for edge in (c.start_ms, c.end_ms):
        frame = round(Fraction(edge) * NTSC / 1000)
        assert frame_to_ms(frame, NTSC) == edge
    assert 2100 <= c.start_ms and c.end_ms <= 2900


def test_snap_inward_less_than_one_frame() -> None:
    assert snap_inward(1000, 1020, FPS30) is None


def test_merge_intervals_drops_empty() -> None:
    assert merge_intervals([Interval(5, 5), Interval(1, 3), Interval(3, 4)]) == [Interval(1, 4)]


def test_complement() -> None:
    assert complement([Interval(0, 100), Interval(400, 500)], 1000) == [
        Interval(100, 400),
        Interval(500, 1000),
    ]
    assert complement([], 1000) == [Interval(0, 1000)]
    assert complement([Interval(0, 1000)], 1000) == []


def test_interval_rejects_reversed() -> None:
    with pytest.raises(ValueError):
        Interval(5, 1)
