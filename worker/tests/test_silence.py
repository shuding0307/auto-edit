from worker.pipeline.intervals import Interval
from worker.pipeline.silence import parse_silencedetect, seconds_to_ms

LOG = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'in.mp4':
[silencedetect @ 0x7f8] silence_start: 1.2345
[silencedetect @ 0x7f8] silence_end: 2.5 | silence_duration: 1.2655
[silencedetect @ 0x7f8] silence_start: 4
[silencedetect @ 0x7f8] silence_end: 5.0005 | silence_duration: 1.0005
size=N/A time=00:00:10.00 bitrate=N/A speed= 500x
"""


def test_seconds_to_ms_is_exact() -> None:
    assert seconds_to_ms("1.2345") == 1235
    assert seconds_to_ms("0.0005") == 1
    assert seconds_to_ms("4") == 4000
    assert seconds_to_ms("0.1") == 100


def test_parses_pairs() -> None:
    assert parse_silencedetect(LOG, 10_000) == [Interval(1235, 2500), Interval(4000, 5001)]


def test_unterminated_silence_runs_to_end() -> None:
    log = "[silencedetect @ 0x1] silence_start: 8.5\n"
    assert parse_silencedetect(log, 10_000) == [Interval(8500, 10_000)]


def test_negative_start_is_clamped() -> None:
    log = (
        "[silencedetect @ 0x1] silence_start: -0.023\n"
        "[silencedetect @ 0x1] silence_end: 1.2 | silence_duration: 1.223\n"
    )
    assert parse_silencedetect(log, 10_000) == [Interval(0, 1200)]


def test_end_beyond_duration_is_clamped() -> None:
    log = (
        "[silencedetect @ 0x1] silence_start: 9\n"
        "[silencedetect @ 0x1] silence_end: 10.04 | silence_duration: 1.04\n"
    )
    assert parse_silencedetect(log, 10_000) == [Interval(9000, 10_000)]


def test_empty_log() -> None:
    assert parse_silencedetect("", 10_000) == []
