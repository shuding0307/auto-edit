"""FCPXML 1.10 (실험적). 원본 영상을 참조하고 유지 구간을 클립으로 이어 붙인 타임라인.

CapCut 등 편집기에서 '컷 단위로' 이어서 편집할 수 있는지 검증하기 위한 것.
MP4 + SRT가 기본 경로이고, 이건 가져오기가 되는지 확인용이다 (개발 계획 F7).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

from worker.pipeline.intervals import Interval
from worker.pipeline.probe import MediaInfo


def _frames(ms: int, fps: Fraction) -> int:
    return round(Fraction(ms) * fps / 1000)


def _t(frames: int, fps: Fraction) -> str:
    """프레임 수 → FCPXML 유리수 시간 ('1001/30000s' 단위)."""
    sec = Fraction(frames) / fps
    return f"{sec.numerator}/{sec.denominator}s" if sec.denominator != 1 else f"{sec.numerator}s"


def build_fcpxml(source: Path, info: MediaInfo, keeps: list[Interval], *, title: str) -> str:
    fps = info.fps
    frame = Fraction(1) / fps
    root = ET.Element("fcpxml", version="1.10")
    res = ET.SubElement(root, "resources")
    ET.SubElement(
        res,
        "format",
        id="r1",
        frameDuration=f"{frame.numerator}/{frame.denominator}s",
        width=str(info.width),
        height=str(info.height),
    )
    total = _frames(info.duration_ms, fps)
    asset = ET.SubElement(
        res,
        "asset",
        id="r2",
        name=source.stem,
        start="0s",
        duration=_t(total, fps),
        hasVideo="1",
        hasAudio="1" if info.has_audio else "0",
        format="r1",
    )
    ET.SubElement(asset, "media-rep", kind="original-media", src=source.resolve().as_uri())

    clips: list[tuple[int, int]] = []
    for k in keeps:
        a, b = _frames(k.start_ms, fps), _frames(k.end_ms, fps)
        if b > a:
            clips.append((a, b))
    edited = sum(b - a for a, b in clips)

    event = ET.SubElement(ET.SubElement(root, "library"), "event", name="AI Cut Editor")
    project = ET.SubElement(event, "project", name=title)
    seq = ET.SubElement(
        project, "sequence", format="r1", duration=_t(edited, fps), tcStart="0s", tcFormat="NDF"
    )
    spine = ET.SubElement(seq, "spine")
    offset = 0
    for i, (a, b) in enumerate(clips, 1):
        ET.SubElement(
            spine,
            "asset-clip",
            ref="r2",
            name=f"{source.stem} #{i}",
            offset=_t(offset, fps),
            start=_t(a, fps),
            duration=_t(b - a, fps),
            format="r1",
        )
        offset += b - a

    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n{body}\n'
