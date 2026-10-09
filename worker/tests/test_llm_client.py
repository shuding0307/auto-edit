"""ClaudeCutModel 요청 형태·응답 처리 (네트워크 없이 가짜 클라이언트로)."""

from types import SimpleNamespace
from typing import Any

import pytest

from worker.llm_client import ClaudeCutModel, LlmRefusal
from worker.pipeline.llm_cuts import RESPONSE_SCHEMA


class StubMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def make(
    stop: str = "end_turn", model: str = "claude-opus-5-5"
) -> tuple[ClaudeCutModel, StubMessages]:
    response = SimpleNamespace(
        stop_reason=stop,
        stop_details=None,
        model=model,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text='{"cuts": []}'),
        ],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
    )
    stub = StubMessages(response)
    client = SimpleNamespace(beta=SimpleNamespace(messages=stub))
    return ClaudeCutModel(client=client), stub  # type: ignore[arg-type]


def test_request_shape() -> None:
    model, stub = make()
    text, usage = model.complete("sys", "user text", RESPONSE_SCHEMA)
    assert text == '{"cuts": []}'
    k = stub.kwargs
    assert k["model"] == "claude-opus-5-5"
    assert k["system"] == "sys"
    assert k["messages"] == [{"role": "user", "content": "user text"}]
    assert k["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
    }
    assert k["fallbacks"] == "default" and k["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in k  # Opus 5.5는 thinking 파라미터 없이 adaptive


def test_cost_uses_model_price() -> None:
    _, usage = make()[0].complete("s", "u", RESPONSE_SCHEMA)
    assert (usage.input_tokens, usage.output_tokens) == (1000, 200)
    assert usage.cost_usd == pytest.approx((1000 * 4 + 200 * 20) / 1e6)


def test_cost_follows_fallback_model() -> None:
    _, usage = make(model="claude-opus-4-8")[0].complete("s", "u", RESPONSE_SCHEMA)
    assert usage.cost_usd == pytest.approx((1000 * 5 + 200 * 25) / 1e6)


def test_refusal_raises() -> None:
    with pytest.raises(LlmRefusal):
        make(stop="refusal")[0].complete("s", "u", RESPONSE_SCHEMA)


def test_max_tokens_raises() -> None:
    with pytest.raises(RuntimeError, match="max_tokens"):
        make(stop="max_tokens")[0].complete("s", "u", RESPONSE_SCHEMA)
