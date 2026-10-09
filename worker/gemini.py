"""Gemini 호출은 여기서만 한다: STT(gemini-3.5-transcribe)와 CutModel 구현.

API 키: 환경변수 GEMINI_API_KEY (또는 .env).
무료 티어는 입력 내용(음성 포함)이 Google 제품 개선에 쓰일 수 있다.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from google import genai
from google.genai import errors, types

from worker import ffmpeg
from worker.pipeline.llm_cuts import Usage
from worker.pipeline.transcript import Word, words_from_offsets

STT_MODEL = "gemini-3.5-transcribe"
CUT_MODEL = "gemini-3.8-flash"
STT_BACKOFF_S = (5, 15, 30)
_RETRYABLE = {429, 503}


def transcribe(
    src: Path, *, language: str = "ko-KR", client: genai.Client | None = None
) -> list[Word]:
    """영상/오디오 → 단어 타임코드. 단어 타임스탬프 사용 시 최대 30분."""
    client = client or genai.Client()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.flac"
        ffmpeg.extract_audio(src, audio)
        uploaded = client.files.upload(file=str(audio))
    config = types.GenerateContentConfig(
        audio_transcription_config=types.AudioTranscriptionConfig(
            language_codes=[language],
            word_timestamp=True,
        )
    )
    try:
        # STT는 대체 모델이 없으니 과부하(503)·한도(429)면 잠시 기다렸다 다시 시도
        for wait_s in (*STT_BACKOFF_S, None):
            try:
                response = client.models.generate_content(
                    model=STT_MODEL, contents=[uploaded], config=config
                )
                break
            except errors.APIError as e:
                if e.code not in _RETRYABLE or wait_s is None:
                    raise
                time.sleep(wait_s)
    finally:
        if uploaded.name:
            client.files.delete(name=uploaded.name)
    return words_from_response(response)


def words_from_response(response: Any) -> list[Word]:
    items: list[tuple[str, str | None, str | None]] = []
    for cand in response.candidates or []:
        for part in (cand.content.parts if cand.content else None) or []:
            tr = part.audio_transcription
            for w in (tr.words if tr else None) or []:
                items.append((w.word or "", w.start_offset, w.end_offset))
    return words_from_offsets(items)


# 앞 모델이 과부하(503)·한도 초과(429)면 다음 모델로. 모두 무료 티어 모델.
CUT_FALLBACKS = ("gemini-3.7-flash", "gemini-3.5-flash")


class GeminiCutModel:
    def __init__(
        self,
        model: str = CUT_MODEL,
        *,
        fallbacks: tuple[str, ...] = CUT_FALLBACKS,
        client: genai.Client | None = None,
    ) -> None:
        self.models = (model, *[m for m in fallbacks if m != model])
        self.client = client or genai.Client()
        self.served_by: list[str] = []
        """호출마다 실제로 응답한 모델 (로그·평가 기록용)."""

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> tuple[str, Usage]:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        last: errors.APIError | None = None
        for model in self.models:
            try:
                response = self.client.models.generate_content(
                    model=model, contents=user, config=config
                )
            except errors.APIError as e:
                if e.code not in _RETRYABLE:
                    raise
                last = e
                continue
            self.served_by.append(model)
            meta = response.usage_metadata
            inp = (meta.prompt_token_count or 0) if meta else 0
            out = (
                ((meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0))
                if meta
                else 0
            )
            # 무료 티어 기준이라 비용은 0으로 기록 (토큰 수는 남김)
            return response.text or "", Usage(inp, out, 0.0)
        assert last is not None
        raise last
