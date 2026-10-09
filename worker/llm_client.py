"""CutModel의 Claude 구현. 네트워크 호출은 여기서만 한다.

자격 증명은 SDK 기본 순서(ANTHROPIC_API_KEY → `ant auth login` 프로필 …)로 찾는다.
"""

from __future__ import annotations

from typing import Any, Literal

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam

from worker.pipeline.llm_cuts import Usage

DEFAULT_MODEL = "claude-opus-5-5"

Effort = Literal["low", "medium", "high", "xhigh", "max"]

# USD / 1M 토큰 (input, output). 비용 로그용 추정치.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


class LlmRefusal(RuntimeError):
    pass


class ClaudeCutModel:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        effort: Effort = "medium",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.client = client or anthropic.Anthropic()

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> tuple[str, Usage]:
        # 안전 분류기가 거절하면 서버가 다른 모델로 자동 재시도한다 (fallbacks="default").
        messages: list[BetaMessageParam] = [{"role": "user", "content": user}]
        output_config: BetaOutputConfigParam = {
            "effort": self.effort,
            "format": {"type": "json_schema", "schema": schema},
        }
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise LlmRefusal(f"모델이 거절함: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("max_tokens 도달 — 창(window) 크기를 줄여야 한다")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return text, _usage(response.model, response.usage)


def _usage(model: str, usage: Any) -> Usage:
    inp = int(usage.input_tokens or 0) + int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    out = int(usage.output_tokens or 0)
    price_in, price_out = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return Usage(inp, out, (inp * price_in + out * price_out) / 1_000_000)
