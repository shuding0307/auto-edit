"""Gemini 어댑터: 요청 설정과 응답 파싱 (네트워크 없이)."""

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors, types

from worker.gemini import GeminiCutModel, words_from_response
from worker.pipeline.llm_cuts import RESPONSE_SCHEMA


def test_words_from_response_uses_sdk_types() -> None:
    response = types.GenerateContentResponse.model_validate(
        {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "audioTranscription": {
                                    "words": [
                                        {
                                            "word": "안녕",
                                            "startOffset": "0.100s",
                                            "endOffset": "0.450s",
                                        },
                                        {
                                            "word": "하세요",
                                            "startOffset": "0.5s",
                                            "endOffset": "0.9s",
                                        },
                                    ]
                                }
                            },
                            {"text": "안녕 하세요"},
                        ],
                    }
                }
            ]
        }
    )
    words = words_from_response(response)
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
        ("안녕", 100, 450),
        ("하세요", 500, 900),
    ]


def test_words_from_empty_response() -> None:
    assert words_from_response(types.GenerateContentResponse.model_validate({})) == []


class StubModels:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def generate_content(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(
            text='{"cuts": []}',
            usage_metadata=SimpleNamespace(
                prompt_token_count=900, candidates_token_count=40, thoughts_token_count=60
            ),
        )


def test_cut_model_request_and_usage() -> None:
    stub = StubModels()
    model = GeminiCutModel(client=SimpleNamespace(models=stub))  # type: ignore[arg-type]
    text, usage = model.complete("sys", "user", RESPONSE_SCHEMA)
    assert text == '{"cuts": []}'
    assert stub.kwargs["model"] == "gemini-3.8-flash" and stub.kwargs["contents"] == "user"
    cfg = stub.kwargs["config"]
    assert cfg.system_instruction == "sys"
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == RESPONSE_SCHEMA
    assert (usage.input_tokens, usage.output_tokens, usage.cost_usd) == (900, 100, 0.0)


class FlakyModels(StubModels):
    """첫 모델은 503, 그다음은 정상."""

    def __init__(self, fail: dict[str, int]) -> None:
        super().__init__()
        self.fail = fail
        self.tried: list[str] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.tried.append(kwargs["model"])
        code = self.fail.get(kwargs["model"])
        if code:
            cls = errors.ServerError if code >= 500 else errors.ClientError
            raise cls(code, {"error": {"code": code, "message": "x", "status": "X"}}, None)
        return super().generate_content(**kwargs)


def test_falls_back_on_overload() -> None:
    stub = FlakyModels({"gemini-3.8-flash": 503, "gemini-3.7-flash": 429})
    model = GeminiCutModel(client=SimpleNamespace(models=stub))  # type: ignore[arg-type]
    text, _ = model.complete("s", "u", RESPONSE_SCHEMA)
    assert text == '{"cuts": []}'
    assert stub.tried == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash"]
    assert model.served_by == ["gemini-3.5-flash"]


def test_non_retryable_error_raises_immediately() -> None:
    stub = FlakyModels({"gemini-3.8-flash": 400})
    model = GeminiCutModel(client=SimpleNamespace(models=stub))  # type: ignore[arg-type]
    with pytest.raises(errors.ClientError):
        model.complete("s", "u", RESPONSE_SCHEMA)
    assert stub.tried == ["gemini-3.8-flash"]


def test_all_overloaded_raises_last() -> None:
    stub = FlakyModels(
        {m: 503 for m in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash")}
    )
    model = GeminiCutModel(client=SimpleNamespace(models=stub))  # type: ignore[arg-type]
    with pytest.raises(errors.ServerError):
        model.complete("s", "u", RESPONSE_SCHEMA)
